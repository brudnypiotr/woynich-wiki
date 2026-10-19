"""Local web app: `kb serve` (127.0.0.1 only, standard library, no extra packages).

- Add sources: upload files from the browser; each goes through visible steps
  (saved → text extracted → facts → summary → topic pages → glossary → citation check) as a background job.
- Discuss: open a session on a topic and ask follow-up questions; every answer is cited and checked like `kb ask`.
  Sessions are kept in instance/sessions/<id>.json and can be saved as a wiki page.
- Wiki: the same static dashboard, rebuilt on request and shown inside the app (`/dashboard?embed=1`).

One job writes at a time (single writer, ADR on the queue). Every request needs the session token printed at start,
so other web pages open in the browser cannot call the local API.
"""
from __future__ import annotations

import html
import json
import re
import secrets
import tempfile
import threading
import time
import traceback
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from kb.core import config, gitops
from kb.knowledge import catalog, chat, pages, verify, wiki
from kb.llm.gateway import Gateway
from kb.publish import site

MAX_UPLOAD = 200_000_000
WRITE_LOCK = threading.Lock()
JOBS: dict[str, dict] = {}
STEPS = ["saved", "extracted", "writing", "checking", "verify", "done"]


def _sessions_dir() -> Path:
    d = catalog.instance() / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_session(sid: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{12}", sid):
        raise KeyError(sid)
    return json.loads((_sessions_dir() / f"{sid}.json").read_text(encoding="utf-8"))


def _save_session(s: dict) -> None:
    (_sessions_dir() / f"{s['id']}.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")


def _job_step(job: dict, step: str, detail: str = "") -> None:
    if job.get("cancel"):
        raise wiki.Cancelled()
    job["step"] = "writing" if step == "reading" else step  # the model reads and writes in one step
    job["log"].append({"at": time.strftime("%H:%M:%S"), "step": step, "detail": detail})


def run_ingest_job(job: dict, path: Path, gw: Gateway) -> None:
    try:
        with WRITE_LOCK:
            _job_step(job, "saved", path.name)
            rec, created = catalog.add_file(path, connector="upload", ref=job["filename"], title=Path(job["filename"]).stem,
                                            found_via=["upload"])
            job["source_id"] = rec["id"]
            info = json.loads((catalog.instance() / "raw" / rec["id"] / "extract.json").read_text(encoding="utf-8"))
            detail = f"{info.get('extractor') or 'no extractor'}, {info.get('chars', 0):,} characters"
            if info.get("pages"):
                detail += f", {info['pages']} pages"
            ocr = [q["page"] for q in info.get("quality", []) if q.get("needs_ocr")]
            if ocr:
                detail += f"; pages without text layer (scan?): {', '.join(map(str, ocr[:10]))}"
            if not created:
                detail += " (already in the knowledge base: same content)"
            _job_step(job, "extracted", detail)
            if rec["status"] == "error":
                raise RuntimeError(info.get("error") or "extraction failed")
            if created or rec["status"] == "extracted":
                res = wiki.ingest_pending([rec["id"]], runner=Handler.runner, cancelled=lambda: bool(job.get("cancel")),
                                          progress=lambda st, d: _job_step(job, st, d) if not job.get("cancel") else None)
                if job.get("cancel"):
                    raise wiki.Cancelled()
                job["result"] = res[0] if res else None
            v = verify.verify_all()
            _job_step(job, "verify", f"{v['citations_ok']}/{v['citations']} citations found in sources, {v['broken_links']} broken links, "
                                     f"{v['contradictions']} contradictions")
            site.build()
        _job_step(job, "done", rec["title"])
        job["state"] = "done"
    except wiki.Cancelled:
        with WRITE_LOCK:
            catalog.rollback()
            note = "cancelled; unfinished changes rolled back"
            if job.get("remove_on_cancel") and job.get("source_id"):
                catalog.remove(job["source_id"]); job["removed"] = True
                note += "; source removed"
            elif job.get("source_id"):
                note += "; the source stays registered (ingest it later or remove it)"
        job["state"] = "cancelled"
        job["log"].append({"at": time.strftime("%H:%M:%S"), "step": "cancelled", "detail": note})
    except Exception as e:  # shown in the UI; details in the job log
        job["state"] = "error"
        job["error"] = f"{type(e).__name__}: {e}"[:500]
        job["log"].append({"at": time.strftime("%H:%M:%S"), "step": "error", "detail": traceback.format_exc()[-1500:]})


class Handler(BaseHTTPRequestHandler):
    server_version = "woynich-wiki"
    token = ""
    gw: Gateway | None = None
    runner = None  # agent runner (tests replace it)

    def log_message(self, fmt, *args):  # quiet console
        pass

    # ------------------------------------------------------------------ helpers
    def _send(self, code: int, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else (json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
                                                      if not isinstance(body, str) else body.encode("utf-8"))
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _authorised(self) -> bool:
        q = parse_qs(urlparse(self.path).query)
        return secrets.compare_digest(self.headers.get("X-KB-Token", "") or (q.get("t") or [""])[0], self.token)

    def _json_body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n).decode("utf-8") or "{}") if n else {}

    # ------------------------------------------------------------------ routes
    def do_GET(self):
        url = urlparse(self.path)
        if not self._authorised():
            return self._send(403, "Open the link printed by `kb serve` (it contains the access token).", "text/plain; charset=utf-8")
        if url.path == "/":
            title = (config.load("profile").get("instance") or {}).get("title") or "Knowledge base"
            brand = site._branding()
            if "<img" not in brand:  # no company logo in instance/branding: neutral mark
                brand = MARK + brand
            page = (APP.replace("__ACCESS__", self.token).replace("__TITLE__", html.escape(title))
                    .replace("__LOGO__", brand).replace("__MARK__", MARK))
            return self._send(200, page, "text/html; charset=utf-8")
        if url.path == "/dashboard":
            page = site.build().read_bytes()
            if parse_qs(url.query).get("embed"):  # inside the app: the app already shows the logo and title
                page = page.replace(b"</head>", EMBED_CSS + b"</head>", 1)
            return self._send(200, page, "text/html; charset=utf-8")
        if url.path.startswith("/api/jobs/"):
            job = JOBS.get(url.path.rsplit("/", 1)[-1])
            return self._send(200, job) if job else self._send(404, {"error": "no such job"})
        if url.path == "/api/jobs":
            return self._send(200, sorted(JOBS.values(), key=lambda j: j["started"], reverse=True)[:20])
        if url.path == "/api/sessions":
            items = []
            for f in sorted(_sessions_dir().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:30]:
                s = json.loads(f.read_text(encoding="utf-8"))
                items.append({"id": s["id"], "topic": s["topic"], "turns": len(s["turns"]), "updated": s.get("updated")})
            return self._send(200, items)
        if url.path.startswith("/api/sessions/"):
            try:
                return self._send(200, _load_session(url.path.rsplit("/", 1)[-1]))
            except (KeyError, FileNotFoundError):
                return self._send(404, {"error": "no such session"})
        if url.path == "/api/status":
            srcs = catalog.all_sources()
            return self._send(200, {"sources": len(srcs), "pages": sum(1 for _ in pages.wiki().rglob("*.md")) if pages.wiki().exists() else 0, "busy": WRITE_LOCK.locked(),
                                    "model": self.gw.model_for("query")[1]})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        url = urlparse(self.path)
        if not self._authorised():
            return self._send(403, {"error": "missing or wrong token"})
        try:
            if url.path == "/api/upload":
                return self._upload()
            if url.path == "/api/sessions":
                body = self._json_body()
                topic = (body.get("topic") or "").strip()[:200]
                if not topic:
                    return self._send(400, {"error": "topic is required"})
                s = {"id": uuid.uuid4().hex[:12], "topic": topic, "created": catalog.now(), "updated": catalog.now(), "turns": []}
                _save_session(s)
                return self._send(200, s)
            m = re.fullmatch(r"/api/jobs/([0-9a-f]{12})/cancel", url.path)
            if m:
                job = JOBS.get(m.group(1))
                if not job or job["state"] != "running":
                    return self._send(409, {"error": "job is not running"})
                job["cancel"] = True
                job["remove_on_cancel"] = bool(self._json_body().get("remove"))
                return self._send(200, {"ok": True, "note": "stops after the current step (a model call can take ~30 s)"})
            m = re.fullmatch(r"/api/sources/([0-9a-f]{12})/remove", url.path)
            if m:
                if not WRITE_LOCK.acquire(timeout=1):
                    return self._send(409, {"error": "an ingest is running; cancel it first"})
                try:
                    r = catalog.remove(m.group(1))
                finally:
                    WRITE_LOCK.release()
                for j in JOBS.values():
                    if j.get("source_id") == m.group(1):
                        j["removed"] = True
                return self._send(200, r)
            m = re.fullmatch(r"/api/sessions/([0-9a-f]{12})/(ask|save)", url.path)
            if m:
                s = _load_session(m.group(1))
                return self._ask(s) if m.group(2) == "ask" else self._save_page(s)
        except Exception as e:
            return self._send(500, {"error": f"{type(e).__name__}: {e}"[:500]})
        return self._send(404, {"error": "not found"})

    def _upload(self):
        name = Path(unquote(self.headers.get("X-Filename") or "upload.bin")).name
        n = int(self.headers.get("Content-Length") or 0)
        if not n or n > MAX_UPLOAD:
            return self._send(400, {"error": f"file size must be between 1 byte and {MAX_UPLOAD // 1_000_000} MB"})
        tmp = Path(tempfile.mkdtemp(prefix="kb-upload-")) / name
        with tmp.open("wb") as f:
            left = n
            while left:
                chunk = self.rfile.read(min(left, 1 << 20))
                if not chunk:
                    break
                f.write(chunk); left -= len(chunk)
        job = {"id": uuid.uuid4().hex[:12], "filename": name, "bytes": n, "state": "running", "step": "queued",
               "started": catalog.now(), "log": [], "steps": STEPS}
        JOBS[job["id"]] = job
        threading.Thread(target=run_ingest_job, args=(job, tmp, self.gw), daemon=True).start()
        return self._send(200, job)

    def _ask(self, s: dict):
        import base64
        body = self._json_body()
        q = (body.get("question") or "").strip()[:2000]
        if not q:
            return self._send(400, {"error": "question is required"})
        att = []
        for i, img in enumerate((body.get("images") or [])[:4]):
            ext = (Path(str(img.get("name") or "image.png")).suffix.lower() or ".png")
            if ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
                return self._send(400, {"error": f"unsupported image type {ext}"})
            data = base64.b64decode(str(img.get("data") or "").split(",")[-1])
            if len(data) > 10_000_000:
                return self._send(400, {"error": "image larger than 10 MB"})
            p = _sessions_dir() / s["id"] / f"{len(s['turns']) + 1:03d}-{i + 1}{ext}"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data); att.append(p)
        hist = [{"question": t["question"], "answer_text": t["answer_text"]} for t in s["turns"]]
        r = chat.ask(q, runner=Handler.runner, history=hist, topic=s["topic"], attachments=att,
                     focus="code" if body.get("focus") == "code" else "wiki")
        turn = {"question": q, "at": catalog.now(), "not_found": r["not_found"], "seconds": r["seconds"],
                "answer_text": r["answer_text"], "markdown": r["answer_text"], "pages_read": r["pages_read"],
                "tools_used": r["tools_used"], "premium": r["premium"], "images": [p.name for p in att]}
        s["turns"].append(turn); s["updated"] = catalog.now()
        _save_session(s)
        return self._send(200, turn)

    def _save_page(self, s: dict):
        slug = re.sub(r"[^a-z0-9]+", "-", s["topic"].lower()).strip("-")[:50] or "discussion"
        p = pages.wiki() / "answers" / f"discussion-{slug}-{s['id'][:6]}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        body = [pages.frontmatter(type="discussion", status="draft", topic=s["topic"], updated=pages.today()), f"# Discussion: {s['topic']}", ""]
        for t in s["turns"]:
            body += [f"## {t['question']}", "", t["markdown"], ""]
        with WRITE_LOCK:
            p.write_text("\n".join(body), encoding="utf-8")
            wiki._log_line(f"discussion saved: [[{p.stem}]] ({len(s['turns'])} questions)")
            gitops.commit(catalog.instance(), [pages.wiki()], gitops.message("ingest", f"discussion: {s['topic'][:80]}", scope="answer"))
        return self._send(200, {"saved": str(p.relative_to(catalog.instance()))})


def make_server(port: int = 8765, gw: Gateway | None = None, adapter: str | None = None) -> ThreadingHTTPServer:
    catalog.init()
    Handler.token = secrets.token_urlsafe(16)
    Handler.gw = gw or Gateway(adapter=adapter)
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve(port: int = 8765, open_browser: bool = True, adapter: str | None = None) -> None:
    httpd = make_server(port, adapter=adapter)
    port = httpd.server_address[1]
    url = f"http://127.0.0.1:{port}/?t={Handler.token}"
    print(f"woynich-wiki is running at {url}\nKeep this window open; press Ctrl+C to stop.", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("stopped")
    finally:
        httpd.server_close()


EMBED_CSS = (b"<style>header{display:none}.wrap{min-height:100vh}nav{background:var(--card);border-right:1px solid var(--line)}"
             b"nav button{color:var(--ink2)}nav button:hover{background:var(--vio-soft);color:var(--vio)}</style>")
MARK = ('<svg class="mark" viewBox="0 0 32 32" aria-hidden="true"><defs><linearGradient id="mk" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#764bff"/><stop offset="1" stop-color="#2969f2"/></linearGradient></defs>'
        '<rect width="32" height="32" rx="9" fill="url(#mk)"/><path d="M8 10h5.5a2.5 2.5 0 0 1 2.5 2.5V23a2 2 0 0 0-2-2H8zM24 10h-5.5'
        'a2.5 2.5 0 0 0-2.5 2.5V23a2 2 0 0 1 2-2h6z" fill="none" stroke="#fff" stroke-width="1.8" stroke-linejoin="round"/></svg>')

APP = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Red+Hat+Display:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
:root{--side:#14152f;--side2:#1d1f45;--side-ink:#c3c9ea;--navy:#06103d;--blue:#2969f2;--vio:#764bff;--vio-soft:#efeaff;
  --bg:#fff;--card:#fff;--soft:#f6f6fa;--bubble:#f0eefb;--ink:#111827;--ink2:#374151;--mute:#6b7280;--line:#e6e6ef;
  --ok:#1f9d6b;--ok-soft:#e3f6ee;--bad:#c23b3b;--bad-soft:#fde8e8;--warn:#b86e0b}
@media (prefers-color-scheme:dark){:root{--bg:#0d0f24;--card:#14152f;--soft:#151733;--bubble:#22244a;--ink:#eef0fa;--ink2:#d6dcf7;
  --mute:#9aa3c7;--line:#262949;--vio-soft:rgba(118,75,255,.18);--ok-soft:rgba(31,157,107,.18);--bad-soft:rgba(194,59,59,.2)}}
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 'Red Hat Display',system-ui,'Segoe UI',sans-serif;-webkit-font-smoothing:antialiased;
  display:grid;grid-template-columns:268px 1fr;overflow:hidden}
button{font:inherit;color:inherit;cursor:pointer}
button:disabled{opacity:.45;cursor:default}
svg.i{width:18px;height:18px;flex:none}
svg.mark{width:30px;height:30px;flex:none}

/* sidebar */
aside{background:var(--side);color:var(--side-ink);display:flex;flex-direction:column;min-height:0;z-index:20}
header{display:flex;align-items:center;gap:10px;padding:16px 16px 14px;background:var(--side) var(--hdr-bg,none) center/cover;border-bottom:1px solid rgba(255,255,255,.07)}
header img{height:26px;width:auto;max-width:120px}
header h1{margin:0;font-size:15px;font-weight:800;color:#fff;line-height:1.2;letter-spacing:-.01em}
header small{display:block;font-size:11px;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:#b9a6ff}
.navp{padding:12px 10px 4px;display:flex;flex-direction:column;gap:2px}
.navp button,.sl a{display:flex;align-items:center;gap:10px;border:0;background:none;padding:9px 12px;border-radius:10px;text-align:left;font-weight:600;color:var(--side-ink);text-decoration:none}
.navp button:hover,.sl a:hover{background:rgba(255,255,255,.06);color:#fff}
.navp button.on,.sl a.on{background:var(--side2);color:#fff}
.navp button.new{border:1px solid rgba(255,255,255,.14);margin-bottom:6px}
.label{padding:16px 22px 6px;font-size:11px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:#7f88b5}
.sl{flex:1;overflow:auto;padding:0 10px 10px}
.sl a{font-weight:500;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:block;cursor:pointer}
.sl .none{padding:4px 12px;font-size:13px;color:#7f88b5}
.foot{padding:12px 18px;border-top:1px solid rgba(255,255,255,.07);font-size:12px;color:#8e97c4;display:flex;align-items:center;gap:8px}
.dot{width:8px;height:8px;border-radius:50%;background:var(--ok);flex:none}.dot.busy{background:#f0a83a;animation:pulse 1.2s infinite}

/* main */
main{display:flex;flex-direction:column;min-width:0;min-height:0;height:100vh}
.top{height:54px;flex:none;display:flex;align-items:center;gap:10px;padding:0 18px;border-bottom:1px solid var(--line)}
.top .ttl{font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1}
.ghost{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);background:var(--card);border-radius:10px;padding:6px 12px;font-weight:600;font-size:13px;color:var(--ink2);text-decoration:none;white-space:nowrap}
.ghost:hover{border-color:var(--vio);color:var(--vio)}
.icon{display:inline-grid;place-items:center;width:36px;height:36px;border:0;background:none;border-radius:10px;color:var(--mute)}
.icon:hover{background:var(--soft);color:var(--ink)}
.menu{display:none}
.scroll{flex:1;overflow:auto;min-height:0}
.col{max-width:800px;margin:0 auto;padding:28px 24px 12px}
.col.wide{max-width:900px}
iframe{flex:1;border:0;width:100%;min-height:0;background:var(--bg)}

/* chat */
.hero{min-height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:40px 24px}
.hero svg.mark{width:48px;height:48px;margin-bottom:14px}
.hero h2{font-size:28px;font-weight:800;margin:0 0 6px;letter-spacing:-.02em}
.hero p{color:var(--mute);margin:0 0 22px;max-width:520px}
.chips{display:flex;flex-wrap:wrap;gap:8px;justify-content:center;max-width:640px}
.chips button{border:1px solid var(--line);background:var(--card);border-radius:999px;padding:8px 14px;font-size:14px;color:var(--ink2)}
.chips button:hover{border-color:var(--vio);color:var(--vio)}
.msg{margin:0 0 26px}
.msg.user{display:flex;flex-direction:column;align-items:flex-end}
.msg.user .bubble{background:var(--bubble);border-radius:20px 20px 6px 20px;padding:10px 16px;max-width:85%;white-space:pre-wrap;word-wrap:break-word}
.msg.user .att{font-size:12px;color:var(--mute);margin-top:4px}
.msg.bot{display:flex;gap:14px}
.msg.bot svg.mark{width:28px;height:28px;margin-top:2px}
.msg.bot .body{flex:1;min-width:0}
.md p{margin:0 0 10px}.md>:last-child{margin-bottom:0}
.md h3,.md h4,.md h5{margin:16px 0 6px;line-height:1.3}.md h3{font-size:18px}.md h4{font-size:16px}.md h5{font-size:15px}
.md ul,.md ol{margin:0 0 10px;padding-left:22px}.md li{margin:3px 0}
.md code{background:var(--soft);border:1px solid var(--line);padding:0 5px;border-radius:5px;font:13px ui-monospace,Consolas,monospace}
.md pre{background:var(--soft);border:1px solid var(--line);border-radius:12px;padding:12px 14px;overflow:auto}
.md pre code{border:0;padding:0;background:none}
.md blockquote{margin:0 0 10px;padding:2px 12px;border-left:3px solid var(--vio);color:var(--mute)}
.md .callout{border-left:4px solid #d98a1b;background:rgba(217,138,27,.09);padding:8px 12px;border-radius:0 10px 10px 0;margin:0 0 10px}
.md .tbl{overflow:auto;margin:0 0 10px}.md table{border-collapse:collapse;font-size:14px}
.md th,.md td{border:1px solid var(--line);padding:6px 10px;text-align:left;vertical-align:top}.md th{background:var(--soft)}
a.wl{display:inline-block;font-size:12.5px;font-weight:700;line-height:1.4;color:var(--vio);background:var(--vio-soft);border-radius:999px;padding:0 8px;text-decoration:none;vertical-align:1px}
a.wl:hover{background:var(--vio);color:#fff}
.nf{color:var(--warn)}
.meta{display:flex;flex-wrap:wrap;gap:6px 14px;margin-top:10px;font-size:12px;color:var(--mute)}
.meta details summary{cursor:pointer;list-style:none}.meta details summary::-webkit-details-marker{display:none}
.meta details[open] summary{color:var(--ink2)}
.meta details div{margin-top:4px}
.typing{display:flex;align-items:center;gap:10px;color:var(--mute);font-size:14px;padding-top:4px}
.typing i{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--vio);animation:blink 1.2s infinite}
.typing i:nth-child(2){animation-delay:.2s}.typing i:nth-child(3){animation-delay:.4s}
@keyframes blink{0%,80%,100%{opacity:.25}40%{opacity:1}}@keyframes pulse{50%{opacity:.4}}
.err{color:var(--bad)}

/* composer */
.cwrap{flex:none;padding:6px 24px 14px}
.composer{max-width:800px;margin:0 auto;border:1px solid var(--line);border-radius:24px;background:var(--card);padding:10px 10px 8px 16px;
  box-shadow:0 4px 18px rgba(6,16,61,.07);transition:border-color .15s}
.composer:focus-within{border-color:var(--vio)}
.composer textarea{width:100%;border:0;outline:0;resize:none;background:none;color:var(--ink);font:inherit;max-height:220px;padding:4px 0}
.tools{display:flex;align-items:center;gap:4px;margin-left:-8px}
.pill{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);background:none;border-radius:999px;padding:5px 12px;font-size:13px;font-weight:600;color:var(--mute)}
.pill[aria-pressed=true]{background:var(--vio-soft);border-color:var(--vio);color:var(--vio)}
.sp{flex:1}
.send{display:grid;place-items:center;width:36px;height:36px;border-radius:50%;border:0;background:var(--ink);color:var(--bg)}
.send:disabled{background:var(--line);color:var(--mute);opacity:1}
.imgs{display:flex;flex-wrap:wrap;gap:6px}.imgs:not(:empty){margin-bottom:6px}
.imgs span{display:inline-flex;align-items:center;gap:6px;background:var(--soft);border:1px solid var(--line);border-radius:8px;padding:3px 4px 3px 4px;font-size:12px}
.imgs img{width:28px;height:28px;object-fit:cover;border-radius:5px}.imgs b{cursor:pointer;padding:0 5px;color:var(--mute)}
.hint{max-width:800px;margin:8px auto 0;text-align:center;font-size:12px;color:var(--mute)}

/* add sources */
.pagehead .kicker{font-size:11px;font-weight:700;letter-spacing:.16em;text-transform:uppercase;color:var(--vio)}
.pagehead h2{font-size:26px;font-weight:800;margin:2px 0 4px;letter-spacing:-.02em}
.pagehead p{color:var(--mute);margin:0 0 20px}
.drop{border:2px dashed color-mix(in srgb,var(--vio) 55%,transparent);border-radius:20px;padding:38px 20px;text-align:center;cursor:pointer;
  background:linear-gradient(135deg,var(--vio-soft),transparent 70%);transition:background .15s,border-color .15s}
.drop:hover,.drop.over{border-color:var(--vio);background:var(--vio-soft)}
.drop .up{display:inline-grid;place-items:center;width:54px;height:54px;border-radius:16px;background:linear-gradient(135deg,var(--vio),var(--blue));color:#fff;margin-bottom:10px}
.drop .up svg{width:26px;height:26px}
.drop b{display:block;font-size:17px}.drop span{color:var(--mute);font-size:14px}
.types{display:flex;flex-wrap:wrap;gap:6px;justify-content:center;margin-top:14px}
.types em{font-style:normal;font-size:12px;font-weight:600;padding:3px 10px;border-radius:999px;background:var(--card);border:1px solid var(--line);color:var(--ink2)}
.how{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:16px 0 28px}
.how div{background:var(--soft);border-radius:14px;padding:12px 14px;font-size:13px;color:var(--mute)}
.how b{display:block;color:var(--ink);font-size:14px}
.how i{font-style:normal;display:inline-grid;place-items:center;width:20px;height:20px;border-radius:50%;background:var(--vio);color:#fff;font-size:11px;font-weight:800;margin-right:6px}
h3.sec{font-size:13px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--mute);margin:0 0 10px}
.job{border:1px solid var(--line);border-radius:16px;padding:14px 16px;margin-bottom:12px;background:var(--card)}
.job .hd{display:flex;align-items:center;gap:10px}
.job .hd .fi{display:inline-grid;place-items:center;width:34px;height:34px;border-radius:10px;background:var(--vio-soft);color:var(--vio)}
.job .hd .nm{flex:1;min-width:0}.job .hd .nm b{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.job .hd .nm small{color:var(--mute)}
.badge{font-size:12px;font-weight:700;padding:2px 10px;border-radius:999px;background:var(--vio-soft);color:var(--vio)}
.badge.done{background:var(--ok-soft);color:var(--ok)}.badge.error,.badge.cancelled{background:var(--bad-soft);color:var(--bad)}
.stepper{display:flex;list-style:none;padding:0;margin:16px 0 8px}
.stepper li{flex:1;position:relative;text-align:center;font-size:11.5px;font-weight:600;color:var(--mute);padding-top:20px}
.stepper li::before{content:"";position:absolute;top:5px;left:50%;width:12px;height:12px;margin-left:-6px;border-radius:50%;background:var(--line);z-index:1}
.stepper li::after{content:"";position:absolute;top:10px;left:-50%;width:100%;height:2px;background:var(--line)}
.stepper li:first-child::after{display:none}
.stepper li.done::before,.stepper li.done::after,.stepper li.now::after{background:var(--ok)}
.stepper li.done{color:var(--ink2)}
.stepper li.now{color:var(--vio)}.stepper li.now::before{background:var(--vio);box-shadow:0 0 0 4px var(--vio-soft);animation:pulse 1.2s infinite}
.stepper li.err{color:var(--bad)}.stepper li.err::before{background:var(--bad)}
.job .det{font-size:13px;color:var(--mute);margin:4px 0 0}
.job .acts{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap;align-items:center}
.job details{margin-top:8px;font-size:13px}.job summary{cursor:pointer;color:var(--mute)}
.job pre{font:12px/1.5 ui-monospace,Consolas,monospace;color:var(--mute);white-space:pre-wrap;max-height:200px;overflow:auto;background:var(--soft);border-radius:10px;padding:10px;margin:6px 0 0}
.empty{color:var(--mute);font-size:14px}

/* phone */
.scrim{display:none}
@media (max-width:820px){
  body{grid-template-columns:1fr}
  aside{position:fixed;inset:0 auto 0 0;width:280px;transform:translateX(-100%);transition:transform .2s}
  body.side aside{transform:none}body.side .scrim{display:block;position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:10}
  .menu{display:inline-grid}.col{padding:20px 16px 10px}.cwrap{padding:6px 12px 12px}.how{grid-template-columns:1fr}
  .stepper li{font-size:0}.top .ghost span{display:none}}
</style></head><body>
<aside>
 <header>__LOGO__<div><h1>__TITLE__</h1><small>Knowledge base</small></div></header>
 <div class="navp" id="navp">
  <button class="new" data-v="new"><svg class="i" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>New discussion</button>
  <button data-v="add"><svg class="i" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 16V4m0 0-4 4m4-4 4 4M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/></svg>Add sources</button>
  <button data-v="wiki"><svg class="i" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M3 5h6a3 3 0 0 1 3 3v12a2 2 0 0 0-2-2H3zM21 5h-6a3 3 0 0 0-3 3v12a2 2 0 0 1 2-2h7z"/></svg>Wiki</button>
 </div>
 <div class="label">Discussions</div>
 <div class="sl" id="sl"></div>
 <div class="foot"><span class="dot" id="dot"></span><span id="st">connecting…</span></div>
</aside>
<div class="scrim" onclick="document.body.classList.remove('side')"></div>
<main id="main"></main>
<script>
const ACCESS='__ACCESS__',H={'X-KB-Token':ACCESS},MARK=`__MARK__`;const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const api=(p,o={})=>fetch(p,{...o,headers:{...H,...(o.headers||{})}}).then(async r=>{const j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(j.error||r.status);return j});
const ic=(d,w=1.8)=>`<svg class="i" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round"><path d="${d}"/></svg>`;
const I={menu:'M4 6h16M4 12h16M4 18h16',clip:'m21 11-8.5 8.5a5 5 0 0 1-7-7L14 4a3.5 3.5 0 0 1 5 5l-8.5 8.5a2 2 0 0 1-3-3L15 7',code:'m8 8-4 4 4 4M16 8l4 4-4 4',
  send:'M12 19V5m0 0-6 6m6-6 6 6',save:'M5 4h11l3 3v13H5zM8 4v5h7V4M8 20v-6h8v6',ext:'M14 4h6v6M20 4l-9 9M18 14v6H4V6h6',file:'M6 3h8l5 5v13H6zM14 3v5h5',
  up:'M12 16V4m0 0-4 4m4-4 4 4M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2',redo:'M20 12a8 8 0 1 1-2.3-5.7M20 4v5h-5'};
const topbar=(title,acts='')=>`<div class="top"><button class="icon menu" onclick="document.body.classList.add('side')" title="Menu">${ic(I.menu)}</button><div class="ttl">${title}</div>${acts}</div>`;
let S=null,BUSY=false,STEPS=['saved','extracted','writing','checking','verify','done'];
const STEP_LABEL={saved:'Saved',extracted:'Text extracted',writing:'Writing wiki',checking:'Checking',verify:'Citations verified',done:'Done'};

async function status(){try{const s=await api('/api/status');$('#st').textContent=`${s.sources} sources · ${s.pages} pages · ${s.model}${s.busy?' · working…':''}`;
  $('#dot').classList.toggle('busy',s.busy)}catch(e){$('#st').textContent='not connected';$('#dot').classList.add('busy')}}
setInterval(status,5000);status();
async function loadSessions(){const l=await api('/api/sessions').catch(()=>[]);
  $('#sl').innerHTML=l.length?l.map(s=>`<a data-id="${s.id}" title="${esc(s.topic)} · ${s.turns} questions">${esc(s.topic)}</a>`).join(''):'<div class="none">No discussions yet.</div>';mark()}
function mark(v){v=v||(location.hash.slice(1).split('/')[0]||'new');const sid=(v.match(/^s=(\w+)/)||[])[1];
  document.querySelectorAll('#navp button').forEach(b=>b.classList.toggle('on',b.dataset.v===v));
  document.querySelectorAll('#sl a').forEach(a=>a.classList.toggle('on',a.dataset.id===sid))}
$('#sl').onclick=e=>{const a=e.target.closest('a');if(a)location.hash='s='+a.dataset.id};
$('#navp').onclick=e=>{const b=e.target.closest('button');if(!b)return;if(b.dataset.v==='new'&&!location.hash.slice(1))return V.chat(null);location.hash=b.dataset.v==='new'?'':b.dataset.v};

// ---------------------------------------------------------------- markdown (answers)
function inl(t){return esc(t).replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*(.+?)\*\*/g,'<b>$1</b>').replace(/(^|[^*\w])\*([^*\n]+)\*/g,'$1<i>$2</i>')
  .replace(/\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]/g,(m,a,l)=>`<a class="wl" href="#wiki/w:${encodeURIComponent(a.trim())}" title="Open in the wiki">${l||a.trim()}</a>`)}
const BLOCK=/^(```|#{1,4}\s|\s*\||\s*>|\s*([-*]|\d+\.)\s)/;
function mdl(src){const L=String(src||'').replace(/\r/g,'').split('\n');let o='',i=0,m;
  while(i<L.length){const l=L[i];
    if(/^```/.test(l)){const c=[];i++;while(i<L.length&&!/^```/.test(L[i]))c.push(L[i++]);i++;o+=`<pre><code>${esc(c.join('\n'))}</code></pre>`;continue}
    if(m=l.match(/^(#{1,4})\s+(.*)/)){const n=Math.min(m[1].length+2,5);o+=`<h${n}>${inl(m[2])}</h${n}>`;i++;continue}
    if(/^\s*\|/.test(l)){let r=[];while(i<L.length&&/^\s*\|/.test(L[i]))r.push(L[i++]);r=r.filter(x=>!/^\s*\|[\s:|-]+\|?\s*$/.test(x));
      o+='<div class="tbl"><table>'+r.map((x,k)=>'<tr>'+x.trim().replace(/^\||\|$/g,'').split('|').map(c=>k?`<td>${inl(c.trim())}</td>`:`<th>${inl(c.trim())}</th>`).join('')+'</tr>').join('')+'</table></div>';continue}
    if(/^\s*>/.test(l)){const q=[];while(i<L.length&&/^\s*>/.test(L[i]))q.push(L[i++].replace(/^\s*> ?/,''));const c=q[0].match(/^\[!(\w+)\]\s*(.*)/);
      o+=c?`<div class="callout"><b>${c[1]==='contradiction'?'⚖️ Contradiction':esc(c[1])}:</b> ${inl([c[2],...q.slice(1)].join(' '))}</div>`:`<blockquote>${inl(q.join(' '))}</blockquote>`;continue}
    if(/^\s*([-*]|\d+\.)\s/.test(l)){const ol=/^\s*\d+\./.test(l),it=[];while(i<L.length&&/^\s*([-*]|\d+\.)\s/.test(L[i]))it.push(L[i++].replace(/^\s*([-*]|\d+\.)\s+/,''));
      o+=`<${ol?'ol':'ul'}>${it.map(x=>`<li>${inl(x)}</li>`).join('')}</${ol?'ol':'ul'}>`;continue}
    if(!l.trim()){i++;continue}
    const p=[l];i++;while(i<L.length&&L[i].trim()&&!BLOCK.test(L[i]))p.push(L[i++]);o+=`<p>${inl(p.join('\n')).replace(/\n/g,'<br>')}</p>`}
  return o}

// ---------------------------------------------------------------- views
const V={
 chat(s){S=s;mark(s?'s='+s.id:'new');
  $('#main').innerHTML=topbar(s?esc(s.topic):'New discussion',s?`<button class="ghost" id="save" title="Save this discussion as a wiki page">${ic(I.save)}<span>Save as wiki page</span></button>`:'')+
   `<div class="scroll" id="scroll"><div class="col" id="turns"></div></div>
   <div class="cwrap"><div class="composer"><div class="imgs" id="imgs"></div>
     <textarea id="q" rows="1" placeholder="Ask anything about the knowledge base…"></textarea>
     <div class="tools"><button class="icon" id="att" title="Attach a screenshot (or paste one with Ctrl+V)">${ic(I.clip)}</button><input type="file" id="img" accept="image/*" multiple hidden>
       <button class="pill" id="code" aria-pressed="false" title="Also read the code repositories">${ic(I.code)}Code</button><span class="sp"></span>
       <button class="send" id="ask" title="Send (Enter)" disabled>${ic(I.send,2.2)}</button></div></div>
     <p class="hint">Answers use only the knowledge base and cite their sources. Shift+Enter for a new line.</p></div>`;
  renderTurns();
  if(s)$('#save').onclick=async()=>{const b=$('#save');b.disabled=true;try{const r=await api('/api/sessions/'+S.id+'/save',{method:'POST'});b.innerHTML=ic('M5 12l5 5 9-10',2)+'<span>Saved</span>';b.title=r.saved}
    catch(e){alert(e.message);b.disabled=false}};
  const q=$('#q'),ask=$('#ask'),fit=()=>{q.style.height='auto';q.style.height=q.scrollHeight+'px';ask.disabled=BUSY||!q.value.trim()};
  q.oninput=fit;q.onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();go()}};
  $('#code').onclick=e=>{const b=e.currentTarget;b.setAttribute('aria-pressed',b.getAttribute('aria-pressed')!=='true')};
  $('#att').onclick=()=>$('#img').click();$('#img').onchange=()=>{addImgs([...$('#img').files]);$('#img').value=''};
  q.onpaste=e=>{const fs=[...((e.clipboardData||{}).files||[])];if(fs.length){e.preventDefault();addImgs(fs)}};
  ask.onclick=go;IM=[];showImgs();q.focus()},
 add(){mark('add');
  $('#main').innerHTML=topbar('Add sources')+`<div class="scroll"><div class="col wide">
   <div class="pagehead"><div class="kicker">Add sources</div><h2>Feed the knowledge base</h2>
   <p>Each file is kept unchanged. The model reads it, writes or updates the wiki pages, then every citation and link is checked and the change is committed.</p></div>
   <div class="drop" id="drop"><div class="up">${ic(I.up)}</div><b>Drop files here</b><span>or click to choose from your computer</span>
     <div class="types"><em>PDF</em><em>Word</em><em>E-mail .eml</em><em>Teams .vtt</em><em>Jira .jira.json</em><em>Text &amp; code</em></div>
     <input type="file" id="file" multiple hidden></div>
   <div class="how"><div><b><i>1</i>Saved</b>Original stored as-is, text extracted.</div><div><b><i>2</i>Written</b>The model updates topic, entity and source pages.</div><div><b><i>3</i>Checked</b>Citations verified, everything committed. Cancel any time.</div></div>
   <h3 class="sec">Recent uploads</h3><div id="jobs"><p class="empty">Nothing uploaded in this session yet.</p></div></div></div>`;
  const d=$('#drop'),f=$('#file');d.onclick=e=>{if(e.target!==f)f.click()};f.onchange=()=>{upload([...f.files]);f.value=''};
  d.ondragover=e=>{e.preventDefault();d.classList.add('over')};d.ondragleave=()=>d.classList.remove('over');
  d.ondrop=e=>{e.preventDefault();d.classList.remove('over');upload([...e.dataTransfer.files])};
  api('/api/jobs').then(js=>js.reverse().forEach(j=>showJob(j)))},
 wiki(sub){mark('wiki');
  $('#main').innerHTML=topbar('Wiki',`<button class="icon" id="rl" title="Rebuild and reload">${ic(I.redo)}</button><a class="ghost" target="_blank" href="/dashboard?t=${ACCESS}${sub?'#'+sub:''}" title="Open in a new tab">${ic(I.ext)}<span>New tab</span></a>`)+
   `<iframe id="wf" src="/dashboard?t=${ACCESS}&embed=1${sub?'#'+sub:''}" title="Wiki"></iframe>`;
  $('#rl').onclick=()=>$('#wf').contentWindow.location.reload()}
};

// ---------------------------------------------------------------- chat
let IM=[];
function addImgs(fs){for(const f of fs){if(!f.type.startsWith('image/'))continue;const r=new FileReader();r.onload=()=>{IM.push({name:f.name||'screenshot.png',data:r.result});showImgs()};r.readAsDataURL(f)}}
function showImgs(){const el=$('#imgs');if(!el)return;el.innerHTML=IM.map((x,k)=>`<span><img src="${x.data}" alt="">${esc(x.name)}<b onclick="IM.splice(${k},1);showImgs()" title="Remove">×</b></span>`).join('')}
function userMsg(q,imgs){return `<div class="msg user"><div class="bubble">${esc(q)}</div>${imgs&&imgs.length?`<div class="att">📎 ${imgs.map(esc).join(', ')}</div>`:''}</div>`}
function botMsg(t){const md=t.markdown||(t.sentences||[]).map(s=>s.text).join(' ');
  const pr=t.pages_read||[],meta=[t.seconds?`${t.seconds} s`:'',t.tools_used&&t.tools_used.length?`tools: ${t.tools_used.map(esc).join(', ')}`:''].filter(Boolean);
  return `<div class="msg bot">${MARK}<div class="body"><div class="md ${t.not_found?'nf':''}">${t.not_found&&!md.trim()?'<p>No answer found in the knowledge base. Try other words, or add a source that covers it.</p>':mdl(md)}</div>
   <div class="meta">${meta.map(x=>`<span>${x}</span>`).join('')}${pr.length?`<details><summary>${pr.length} page${pr.length>1?'s':''} read ▾</summary><div>${pr.map(p=>`<a class="wl" href="#wiki/w:${encodeURIComponent(String(p).replace(/^.*\//,'').replace(/\.md$/,''))}">${esc(String(p).replace(/^.*\//,'').replace(/\.md$/,''))}</a>`).join(' ')}</div></details>`:''}</div></div></div>`}
const scrollEnd=()=>{const s=$('#scroll');if(s)s.scrollTop=s.scrollHeight};
function renderTurns(){const el=$('#turns');
  if(!S||!S.turns.length){el.className='hero';el.innerHTML=`${MARK}<h2>${S?esc(S.topic):'What would you like to know?'}</h2>
    <p>Ask a question. The assistant reads the wiki (and the code, Jira or your screenshots when useful) and cites every source it uses.</p>
    <div class="chips">${['What are the main topics in the wiki?','Which sources contradict each other?','Summarise the most recent source'].map(x=>`<button>${x}</button>`).join('')}</div>`;
    el.querySelectorAll('.chips button').forEach(b=>b.onclick=()=>{$('#q').value=b.textContent;$('#q').oninput();go()});return}
  el.className='col';el.innerHTML=S.turns.map(t=>userMsg(t.question,t.images)+botMsg(t)).join('');scrollEnd()}
async function go(){const q=$('#q').value.trim();if(!q||BUSY)return;BUSY=true;$('#ask').disabled=true;
  const code=$('#code').getAttribute('aria-pressed')==='true',imgs=IM;IM=[];showImgs();$('#q').value='';$('#q').oninput();$('#ask').disabled=true;
  const el=$('#turns');if(el.className==='hero'){el.className='col';el.innerHTML=''}
  el.insertAdjacentHTML('beforeend',userMsg(q,imgs.map(x=>x.name))+`<div class="msg bot" id="pending">${MARK}<div class="body"><div class="typing"><i></i><i></i><i></i> Reading the wiki${code?' and the code':''}…</div></div></div>`);scrollEnd();
  try{if(!S){S=await api('/api/sessions',{method:'POST',body:JSON.stringify({topic:q.replace(/\s+/g,' ').slice(0,80)})});
      history.replaceState(null,'','#s='+S.id);$('.top .ttl').textContent=S.topic;loadSessions()}
    const t=await api('/api/sessions/'+S.id+'/ask',{method:'POST',body:JSON.stringify({question:q,images:imgs,focus:code?'code':'wiki'})});
    S.turns.push(t);if(!$('#save'))V.chat(S);else renderTurns();loadSessions()}
  catch(e){const p=$('#pending');if(p)p.querySelector('.body').innerHTML=`<p class="err">${esc(e.message)}</p>`;if($('#q')&&!$('#q').value){$('#q').value=q;$('#q').oninput()}}
  finally{BUSY=false;if($('#q')){$('#q').oninput();$('#q').focus()}}}

// ---------------------------------------------------------------- uploads
async function upload(files){for(const file of files){const j=await api('/api/upload',{method:'POST',headers:{'X-Filename':encodeURIComponent(file.name)},body:file})
  .catch(e=>({id:'x'+Math.random().toString(16).slice(2),error:e.message,filename:file.name,state:'error',log:[]}));showJob(j)}}
function showJob(j){const box=$('#jobs');if(!box)return;box.querySelector('.empty')?.remove();
  let el=document.getElementById('job-'+j.id);if(!el){el=document.createElement('div');el.className='job';el.id='job-'+j.id;box.prepend(el)}
  const open=el.querySelector('details')?.open;if(j.steps)STEPS=j.steps;const at=STEPS.indexOf(j.step),bad=j.state==='error'||j.state==='cancelled';
  const last=(j.log||[]).slice(-1)[0];
  el.innerHTML=`<div class="hd"><span class="fi">${ic(I.file)}</span><div class="nm"><b>${esc(j.filename)}</b><small>${j.bytes?(j.bytes>1e6?(j.bytes/1e6).toFixed(1)+' MB':Math.max(1,Math.round(j.bytes/1024))+' KB'):''}</small></div>
    <span class="badge ${j.state}">${{running:'Working…',done:'Done',error:'Failed',cancelled:'Cancelled'}[j.state]||esc(j.state)}</span></div>
   <ol class="stepper">${STEPS.map((s,i)=>`<li class="${bad&&i===Math.max(at,0)?'err':(i<at||j.state==='done'?'done':(i===at?'now':''))}">${STEP_LABEL[s]||s}</li>`).join('')}</ol>
   ${j.error?`<p class="det err">${esc(j.error)}</p>`:(last?`<p class="det">${esc(last.detail)}</p>`:'')}
   <div class="acts">${j.state==='running'?`<button class="ghost" onclick="cancelJob('${j.id}',false)">Cancel</button><button class="ghost" onclick="cancelJob('${j.id}',true)">Cancel and remove file</button>`:
     (j.source_id&&!j.removed?`<button class="ghost" onclick="removeSrc('${j.id}','${j.source_id}')">Remove from knowledge base</button>`:(j.removed?'<span class="empty">removed</span>':''))}</div>
   ${(j.log||[]).length?`<details${open?' open':''}><summary>Details</summary><pre>${(j.log||[]).map(l=>`${l.at} ${l.step}: ${esc(l.detail)}`).join('\n')}</pre></details>`:''}`;
  if(j.state==='running')setTimeout(()=>{if(document.getElementById('job-'+j.id))api('/api/jobs/'+j.id).then(showJob).catch(()=>{})},1500)}
window.cancelJob=async(id,rm)=>{if(rm&&!confirm('Stop and delete this file from the knowledge base?'))return;
  await api('/api/jobs/'+id+'/cancel',{method:'POST',body:JSON.stringify({remove:rm})}).catch(e=>alert(e.message))};
window.removeSrc=async(jid,sid)=>{if(!confirm('Delete this source and its pages from the knowledge base? (one commit, can be undone with Git)'))return;
  try{await api('/api/sources/'+sid+'/remove',{method:'POST'});api('/api/jobs/'+jid).then(showJob)}catch(e){alert(e.message)}};

// ---------------------------------------------------------------- routing: #s=<id> · #add · #wiki[/<dashboard hash>] · (empty) new discussion
async function route(){document.body.classList.remove('side');const h=location.hash.slice(1),m=h.match(/^s=([0-9a-f]{12})$/);
  if(m){if(S&&S.id===m[1]&&$('#turns'))return;try{V.chat(await api('/api/sessions/'+m[1]))}catch(e){location.hash=''}}
  else if(h==='add')V.add();else if(h==='wiki'||h.startsWith('wiki/'))V.wiki(h.slice(5));else V.chat(null)}
window.onhashchange=route;loadSessions();route();
</script></body></html>
"""
