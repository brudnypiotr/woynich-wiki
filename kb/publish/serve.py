"""Local web app: `kb serve` (127.0.0.1 only, standard library, no extra packages).

- Add sources: upload files from the browser; each goes through visible steps
  (saved → text extracted → facts → summary → topic pages → glossary → citation check) as a background job.
- Discuss: one long agent session per discussion (ADR-0019): follow-up questions build on what the model already
  read; after an ingest the session is told which pages changed; idle sessions close after 30 minutes and are
  resumed (or rebuilt from the saved turns) on the next question. Discussions are kept in
  instance/sessions/<id>.json and can be saved as a wiki page.
- Settings: models, GitHub Copilot sign-in, keys and tokens (never sent back to the browser), Jira and title.
- Wiki: the same static dashboard, rebuilt on request and shown inside the app (`/dashboard?embed=1`).

One job writes at a time (single writer, ADR on the queue). Every request needs the session token printed at start,
so other web pages open in the browser cannot call the local API.
"""
from __future__ import annotations

import html
import json
import os
import re
import secrets
import shutil
import socket
import tempfile
import threading
import time
import traceback
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from kb.core import config, gitops
from kb.knowledge import catalog, chat, pages, verify, wiki
from kb.llm.gateway import Gateway
from kb.publish import settings, site

WEB = Path(__file__).with_name("web")  # the browser app: index.html (template), CSS and JS, no build step
# explicit types: Python's mimetypes reads the Windows registry, which can map .js to text/plain and break the app
MIME = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png"}
MAX_UPLOAD = 200_000_000
WRITE_LOCK = threading.Lock()
JOBS: dict[str, dict] = {}
LIVE: dict[str, chat.Conversation] = {}  # discussion id -> open agent session
LIVE_LOCK = threading.Lock()
IDLE_S = 1800
TRACE: dict[str, dict] = {}
USAGE: dict = {"at": 0.0, "data": None}  # billing state, cached: reading it starts the Copilot runtime (seconds)  # discussion id -> what the model is doing for the current question (live view)


def _tracer(sid: str):
    TRACE[sid] = {"running": True, "events": []}
    t0 = time.time()

    def say(step: str, detail: str = "") -> None:
        ev = TRACE[sid]["events"]
        kind = {"reading": "read", "writing": "write"}.get(step, step)
        text = str(detail or "")[:1500]
        if ev and ev[-1]["kind"] == kind == "thinking" and text.startswith(ev[-1]["text"][:200]):
            ev[-1]["text"] = text  # streamed thinking grows in place
            return
        if len(ev) < 80:
            ev.append({"s": round(time.time() - t0, 1), "kind": kind, "text": text})
    return say


def _conversation(s: dict) -> chat.Conversation:
    with LIVE_LOCK:
        conv = LIVE.get(s["id"])
        if conv is None:
            hist = [{"question": t["question"], "answer_text": t["answer_text"]} for t in s["turns"]]
            conv = LIVE[s["id"]] = chat.Conversation(topic=s["topic"], history=hist, runner=Handler.runner,
                                                     resume=s.get("agent_session"))
        return conv


def close_live(idle_only: bool = False, fresh: bool = False) -> int:
    """Close open discussion sessions (all, or those idle for IDLE_S); they resume on the next question.
    fresh=True: the settings a session was opened with changed (model, Jira, repositories), so the next question
    starts a new session (full prompt with the current tools and context, plus a summary of the earlier turns)."""
    with LIVE_LOCK:
        ids = [k for k, c in LIVE.items() if not idle_only or (time.time() - c.used > IDLE_S and not c.lock.locked())]
        convs = [LIVE.pop(k) for k in ids]
    for c in convs:
        c.close()
    if fresh:
        for f in _sessions_dir().glob("*.json"):
            try:
                s = json.loads(f.read_text(encoding="utf-8"))
                if s.pop("agent_session", None):
                    f.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
            except (OSError, ValueError):
                pass
    return len(convs)


def _reaper() -> None:
    while True:
        time.sleep(60)
        try:
            close_live(idle_only=True)
        except Exception:
            pass


def _tell_discussions(result: dict | None) -> None:
    changed = (result or {}).get("created", []) + (result or {}).get("updated", [])
    if changed:
        with LIVE_LOCK:
            for c in LIVE.values():
                c.wiki_changed(changed)
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


def _delete_session(sid: str) -> dict:
    """Delete a discussion: its saved turns, attached screenshots and open agent session. Wiki pages saved from it stay."""
    import shutil
    with LIVE_LOCK:
        conv = LIVE.pop(sid, None)
    if conv:
        conv.close()
    TRACE.pop(sid, None)
    f = _sessions_dir() / f"{sid}.json"
    if not f.exists():
        raise KeyError(sid)
    f.unlink()
    shutil.rmtree(_sessions_dir() / sid, ignore_errors=True)
    return {"deleted": sid}


def _job_step(job: dict, step: str, detail: str = "") -> None:
    if job.get("cancel"):
        raise wiki.Cancelled()
    job["step"] = "writing" if step == "reading" else step  # the model reads and writes in one step
    job["log"].append({"at": time.strftime("%H:%M:%S"), "step": step, "detail": detail})


QUEUE: list[str] = []  # job ids in upload order; the first one is being ingested (one at a time)
QCOND = threading.Condition()


def _wait_turn(job: dict) -> bool:
    with QCOND:
        while QUEUE and QUEUE[0] != job["id"]:
            if job.get("cancel"):
                QUEUE.remove(job["id"]); QCOND.notify_all()
                return False
            QCOND.wait(1)
    return True


def _done_turn(job: dict) -> None:
    with QCOND:
        if job["id"] in QUEUE:
            QUEUE.remove(job["id"])
        QCOND.notify_all()


def run_ingest_job(job: dict, path: Path, gw: Gateway) -> None:
    """Wait for this file's turn (uploads are ingested one by one, in order), then ingest it."""
    if not _wait_turn(job):
        job["state"] = "cancelled"
        job["log"].append({"at": time.strftime("%H:%M:%S"), "step": "cancelled", "detail": "removed from the queue before it started"})
        shutil.rmtree(path.parent, ignore_errors=True)
        return
    job["state"] = "running"
    try:
        _ingest_job(job, path, gw)
    finally:
        _done_turn(job)


def _ingest_job(job: dict, path: Path, gw: Gateway) -> None:
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
                _tell_discussions(job["result"])
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


def _job_view(job: dict) -> dict:
    with QCOND:
        ahead = QUEUE.index(job["id"]) if job["state"] == "queued" and job["id"] in QUEUE else None
    return {**job, "ahead": ahead}


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
    def handle_one_request(self):
        t0 = time.perf_counter()
        super().handle_one_request()
        took = time.perf_counter() - t0
        path = urlparse(getattr(self, "path", "") or "").path
        if took > 2 and not path.endswith(("/ask", "/upload", "/api/usage", "/api/settings/account", "/api/settings/models", "/api/settings/check")):  # questions and uploads are slow by nature
            print(f"slow request: {getattr(self, 'command', '')} {path} took {took:.1f} s", flush=True)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path.startswith("/static/"):  # the app's own code: no data, so no token (the server is 127.0.0.1 only)
            return self._static(url.path[len("/static/"):])
        if not self._authorised():
            return self._send(403, "Open the link printed by `kb serve` (it contains the access token).", "text/plain; charset=utf-8")
        if url.path == "/":
            title = (config.load("profile").get("instance") or {}).get("title") or "Knowledge base"
            brand = site._branding()
            if "<img" not in brand:  # no company logo in instance/branding: neutral mark
                brand = MARK + brand
            icon = site.branding_file("icon")  # company icon from instance/branding, else the neutral mark
            mark = f'<img class="mark" src="{site._data_uri(icon)}" alt="">' if icon else MARK
            fav = site._data_uri(icon) if icon else "data:image/svg+xml," + quote(MARK.replace('class="mark" ', ""))
            cfg = json.dumps({"access": self.token, "mark": mark}).replace("</", "<\\/")  # safe inside <script>
            page = ((WEB / "index.html").read_text(encoding="utf-8").replace("__CONFIG__", cfg)
                    .replace("__TITLE__", html.escape(title)).replace("__LOGO__", brand).replace("__FAVICON__", fav))
            return self._send(200, page, "text/html; charset=utf-8")
        if url.path == "/dashboard":
            page = site.build().read_bytes()
            if parse_qs(url.query).get("embed"):  # inside the app: the app already shows the logo and title
                page = page.replace(b"</head>", EMBED_CSS + b"</head>", 1)
            return self._send(200, page, "text/html; charset=utf-8")
        if url.path.startswith("/api/jobs/"):
            job = JOBS.get(url.path.rsplit("/", 1)[-1])
            return self._send(200, _job_view(job)) if job else self._send(404, {"error": "no such job"})
        if url.path == "/api/jobs":  # everything waiting or running, plus the 30 most recent finished
            js = sorted(JOBS.values(), key=lambda j: j["seq"], reverse=True)
            live = [j for j in js if j["state"] in ("queued", "running")]
            return self._send(200, [_job_view(j) for j in live + [j for j in js if j not in live][:30]])
        if url.path == "/api/sessions":
            items = []
            for f in sorted(_sessions_dir().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:30]:
                s = json.loads(f.read_text(encoding="utf-8"))
                items.append({"id": s["id"], "topic": s["topic"], "turns": len(s["turns"]), "updated": s.get("updated")})
            return self._send(200, items)
        m = re.fullmatch(r"/api/sessions/([0-9a-f]{12})/progress", url.path)
        if m:
            t = TRACE.get(m.group(1)) or {"running": False, "events": []}
            since = int((parse_qs(url.query).get("since") or ["0"])[0] or 0)
            return self._send(200, {"running": t["running"], "events": t["events"][since:], "total": len(t["events"])})
        if url.path.startswith("/api/sessions/"):
            try:
                return self._send(200, _load_session(url.path.rsplit("/", 1)[-1]))
            except (KeyError, FileNotFoundError):
                return self._send(404, {"error": "no such session"})
        if url.path == "/api/settings":
            return self._send(200, settings.state())
        if url.path == "/api/usage":
            fresh = parse_qs(url.query).get("refresh")
            if fresh or not USAGE["data"] or time.time() - USAGE["at"] > 300:  # real reading from GitHub: every 5 min
                USAGE.update(at=time.time(), data=settings.usage(self.gw))
            return self._send(200, settings.usage_estimate(USAGE["data"]))  # + what kb used since then
        if url.path == "/api/settings/check":
            return self._send(200, settings.check(self.gw, (parse_qs(url.query).get("what") or ["all"])[0]))
        if url.path in ("/api/settings/models", "/api/settings/account"):
            try:
                return self._send(200, settings.models_available(self.gw) if url.path.endswith("models") else settings.account(self.gw))
            except Exception as e:
                return self._send(502, {"error": f"{type(e).__name__}: {e}"[:500]})
        if url.path == "/api/status":
            srcs = catalog.all_sources()
            return self._send(200, {"sources": len(srcs), "pages": sum(1 for _ in pages.wiki().rglob("*.md")) if pages.wiki().exists() else 0, "busy": WRITE_LOCK.locked(),
                                    "queued": max(0, len(QUEUE) - 1), "model": settings.effective_model()})
        return self._send(404, {"error": "not found"})

    def _static(self, rel: str):
        f = (WEB / unquote(rel)).resolve()
        if WEB.resolve() not in f.parents or not f.is_file() or f.suffix not in MIME:
            return self._send(404, {"error": "not found"})
        return self._send(200, f.read_bytes(), MIME[f.suffix])

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
            if url.path == "/api/settings":
                body = self._json_body()
                out = settings.save(body)
                if {"model", "profile", "repos"} & set(body):
                    close_live(fresh=True)  # sessions were opened with the old model, Jira tools or repositories
                return self._send(200, out)
            if url.path == "/api/settings/login":
                return self._send(200, settings.login())
            m = re.fullmatch(r"/api/secrets/([a-z0-9-]{1,40})(/delete)?", url.path)
            if m:
                return self._send(200, settings.secret_delete(m.group(1)) if m.group(2) else
                                  settings.secret_set(m.group(1), str(self._json_body().get("value") or "")))
            m = re.fullmatch(r"/api/jobs/([0-9a-f]{12})/cancel", url.path)
            if m:
                job = JOBS.get(m.group(1))
                if not job or job["state"] not in ("queued", "running"):
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
            m = re.fullmatch(r"/api/sessions/([0-9a-f]{12})/stop", url.path)
            if m:
                conv = LIVE.get(m.group(1))
                if not conv or not conv.stop():
                    return self._send(409, {"error": "nothing is running in this discussion"})
                return self._send(200, {"ok": True})
            m = re.fullmatch(r"/api/sessions/([0-9a-f]{12})/delete", url.path)
            if m:
                return self._send(200, _delete_session(m.group(1)))
            m = re.fullmatch(r"/api/sessions/([0-9a-f]{12})/(ask|save)", url.path)
            if m:
                s = _load_session(m.group(1))
                return self._ask(s) if m.group(2) == "ask" else self._save_page(s)
        except ValueError as e:
            return self._send(400, {"error": str(e)[:500]})
        except (KeyError, FileNotFoundError):
            return self._send(404, {"error": "no such discussion"})
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
        job = {"id": uuid.uuid4().hex[:12], "filename": name, "bytes": n, "state": "queued", "step": "queued",
               "started": catalog.now(), "seq": len(JOBS), "log": [], "steps": STEPS}
        JOBS[job["id"]] = job
        with QCOND:
            QUEUE.append(job["id"])
        threading.Thread(target=run_ingest_job, args=(job, tmp, self.gw), daemon=True).start()
        return self._send(200, _job_view(job))

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
        conv = _conversation(s)
        say = _tracer(s["id"])
        try:
            r = conv.ask(q, attachments=att, focus="code" if body.get("focus") == "code" else "wiki", progress=say)
        finally:
            TRACE[s["id"]]["running"] = False
        c = r.get("check") or {}
        turn = {"question": q, "at": catalog.now(), "not_found": r["not_found"], "seconds": r["seconds"],
                "answer_text": r["answer_text"], "markdown": r["answer_text"], "pages_read": r["pages_read"],
                "tools_used": r["tools_used"], "premium": r["premium"], "credits": r.get("credits"), "images": [p.name for p in att], "session": r["session"], "stopped": r.get("stopped", False),
                "check": {"ok": len(c.get("ok", [])), "broken": c.get("broken", []), "unchecked": c.get("unchecked", [])},
                "trace": TRACE[s["id"]]["events"]}
        s = _load_session(s["id"])  # re-read: the question may have taken minutes
        s["turns"].append(turn); s["updated"] = catalog.now(); s["agent_session"] = conv.session_id
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


class _Server(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second server bind a port another one already listens on, without an error;
    # the browser then reaches the old server, whose token differs ("open the link printed by kb serve").
    allow_reuse_address = os.name != "nt"
    daemon_threads = True

    def server_bind(self):
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def make_server(port: int = 8765, gw: Gateway | None = None, adapter: str | None = None) -> ThreadingHTTPServer:
    catalog.init()
    Handler.token = secrets.token_urlsafe(16)
    Handler.gw = gw or Gateway(adapter=adapter)
    for p in ([port] if port == 0 else range(port, port + 10)):
        try:
            httpd = _Server(("127.0.0.1", p), Handler)
            break
        except OSError:
            if p != port:
                continue
            print(f"port {port} is in use (another kb serve still running?); trying the next one", flush=True)
    else:
        raise OSError(f"ports {port}-{port + 9} are all in use; stop other kb serve windows")
    threading.Thread(target=_reaper, daemon=True, name="kb-reaper").start()
    return httpd


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
        close_live()
        httpd.server_close()


EMBED_CSS = (b"<style>header{display:none}.wrap{min-height:100vh}nav{background:var(--card);border-right:1px solid var(--line)}"
             b"nav button{color:var(--ink2)}nav button:hover{background:var(--vio-soft);color:var(--vio)}</style>")
MARK = ('<svg class="mark" viewBox="0 0 32 32" aria-hidden="true"><defs><linearGradient id="mk" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#764bff"/><stop offset="1" stop-color="#2969f2"/></linearGradient></defs>'
        '<rect width="32" height="32" rx="9" fill="url(#mk)"/><path d="M8 10h5.5a2.5 2.5 0 0 1 2.5 2.5V23a2 2 0 0 0-2-2H8zM24 10h-5.5'
        'a2.5 2.5 0 0 0-2.5 2.5V23a2 2 0 0 1 2-2h6z" fill="none" stroke="#fff" stroke-width="1.8" stroke-linejoin="round"/></svg>')

