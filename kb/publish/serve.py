"""Local web app: `kb serve` (127.0.0.1 only, standard library, no extra packages).

- Add sources: upload files from the browser; each goes through visible steps
  (saved → text extracted → facts → summary → topic pages → glossary → citation check) as a background job.
- Discuss: open a session on a topic and ask follow-up questions; every answer is cited and checked like `kb ask`.
  Sessions are kept in instance/sessions/<id>.json and can be saved as a wiki page.
- Dashboard: the same static dashboard, rebuilt on request.

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
            page = APP.replace("__ACCESS__", self.token).replace("__TITLE__", html.escape(title)).replace("__LOGO__", site._branding())
            return self._send(200, page, "text/html; charset=utf-8")
        if url.path == "/dashboard":
            return self._send(200, site.build().read_bytes(), "text/html; charset=utf-8")
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


APP = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Knowledge base</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Red+Hat+Display:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
:root{--navy:#06103d;--navy2:#181a3a;--navy3:#14152f;--blue:#2969f2;--vio:#764bff;--vio-soft:#efeaff;--bg:#f8f8f8;--card:#fff;--ink:#111827;
  --mute:#6b7280;--line:#e5e7eb;--ok:#1f9d6b;--bad:#c23b3b;--r:12px}
@media (prefers-color-scheme:dark){:root{--bg:#0d0f24;--card:#14152f;--ink:#eef0fa;--mute:#9aa3c7;--line:#262949;--vio-soft:rgba(118,75,255,.18)}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 'Red Hat Display',system-ui,'Segoe UI',sans-serif}
header{background:var(--navy2);color:#fff;padding:16px 28px;display:flex;gap:18px;align-items:center;border-bottom:3px solid var(--vio)}
header h1{font-size:19px;margin:0;font-weight:800}header img{height:28px;width:auto}header{background-size:cover;background-position:center;background-image:var(--hdr-bg,none)}header .m{margin-left:auto;font-size:12px;color:#b9c1ea}
.wrap{display:grid;grid-template-columns:210px 1fr;min-height:calc(100vh - 62px)}
nav{background:var(--navy3);padding:16px 10px;display:flex;flex-direction:column;gap:2px}
nav button{border:0;background:none;color:#c3c9ea;padding:9px 14px;border-radius:8px;cursor:pointer;font:inherit;font-weight:600;text-align:left}
nav button:hover{background:rgba(255,255,255,.06);color:#fff}nav button.on{background:var(--vio);color:#fff}
main{padding:26px 30px;max-width:1100px;width:100%}
.kicker{font-size:11px;font-weight:700;letter-spacing:.16em;text-transform:uppercase;color:var(--vio);margin-bottom:4px}
h2{font-size:22px;margin:0 0 4px;font-weight:800;color:var(--navy)}@media (prefers-color-scheme:dark){h2{color:#fff}}
.sub{color:var(--mute);margin:0 0 18px}
.panel{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:18px 20px;margin-bottom:16px}
.drop{border:2px dashed var(--vio);border-radius:var(--r);padding:34px;text-align:center;background:var(--vio-soft);cursor:pointer}
.drop.over{background:rgba(118,75,255,.3)}
button.pri{background:var(--vio);color:#fff;border:0;border-radius:10px;padding:10px 18px;font:inherit;font-weight:700;cursor:pointer}
button.sec{background:none;color:var(--vio);border:1px solid var(--vio);border-radius:10px;padding:8px 14px;font:inherit;font-weight:700;cursor:pointer}
button:disabled{opacity:.5;cursor:default}
input[type=text],textarea{width:100%;padding:11px 13px;border:1px solid var(--line);border-radius:10px;background:var(--card);color:var(--ink);font:inherit;outline:none}
input:focus,textarea:focus{border-color:var(--vio);box-shadow:0 0 0 3px var(--vio-soft)}
.steps{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0}.steps span{padding:3px 10px;border-radius:999px;font-size:12px;font-weight:700;background:var(--line);color:var(--mute)}
.steps span.done{background:#e3f6ee;color:var(--ok)}.steps span.now{background:var(--vio);color:#fff}.steps span.err{background:#fde8e8;color:var(--bad)}
.log{font-size:13px;color:var(--mute);max-height:180px;overflow:auto;font-family:ui-monospace,Consolas,monospace;white-space:pre-wrap}
.row{display:flex;gap:10px;align-items:center}.row>*:first-child{flex:1}
.turn{margin-bottom:18px}.q{font-weight:700;color:var(--navy);margin-bottom:6px}@media (prefers-color-scheme:dark){.q{color:#fff}}
.a p{margin:4px 0}.cite{font-size:12px;font-weight:700;color:var(--vio);cursor:pointer;white-space:nowrap;margin-left:4px}
.ex{display:none;font-size:13px;color:var(--mute);border-left:3px solid var(--vio);padding:4px 10px;margin:4px 0 8px}
.nf{color:#b86e0b}.list a{display:block;padding:8px 0;border-bottom:1px solid var(--line);color:var(--blue);cursor:pointer;font-weight:600}
.list small{color:var(--mute);font-weight:500}
@media (max-width:760px){.wrap{grid-template-columns:1fr}nav{flex-direction:row;flex-wrap:wrap}main{padding:18px 16px}}
</style></head><body>
<header>__LOGO__<h1>__TITLE__</h1><span class="m" id="st"></span></header>
<div class="wrap"><nav id="nav"><button data-v="discuss" class="on">Discuss</button><button data-v="add">Add sources</button><button data-v="dash">Dashboard ↗</button></nav>
<main id="main"></main></div>
<script>
const ACCESS='__ACCESS__',H={'X-KB-Token':ACCESS};const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const api=(p,o={})=>fetch(p,{...o,headers:{...H,...(o.headers||{})}}).then(async r=>{const j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(j.error||r.status);return j});
let STEPS=['saved','extracted','writing','checking','verify','done'];
async function status(){try{const s=await api('/api/status');$('#st').textContent=`${s.sources} sources · ${s.pages} pages · model ${s.model}${s.busy?' · working…':''}`}catch(e){}}
setInterval(status,5000);status();
$('#nav').onclick=e=>{const b=e.target.closest('button');if(!b)return;if(b.dataset.v==='dash'){window.open('/dashboard?t='+ACCESS);return}
  document.querySelectorAll('nav button').forEach(x=>x.classList.toggle('on',x===b));V[b.dataset.v]()};
let S=null;
const V={
 discuss(){$('#main').innerHTML=`<div class="kicker">Discuss</div><h2>Open a discussion on a topic</h2>
   <p class="sub">Ask follow-up questions. Every answer uses only the knowledge base and shows its sources.</p>
   <div class="panel"><div class="row"><input type="text" id="topic" placeholder="Topic, e.g. Minimum rest at home base"><button class="pri" id="new">Start</button></div></div>
   <div class="panel"><b>Recent discussions</b><div class="list" id="sl"></div></div>`;
   $('#new').onclick=async()=>{const t=$('#topic').value.trim();if(!t)return;S=await api('/api/sessions',{method:'POST',body:JSON.stringify({topic:t})});chat()};
   $('#topic').onkeydown=e=>{if(e.key==='Enter')$('#new').click()};
   api('/api/sessions').then(l=>{$('#sl').innerHTML=l.length?l.map(s=>`<a data-id="${s.id}">${esc(s.topic)} <small>· ${s.turns} questions · ${esc((s.updated||'').slice(0,16))}</small></a>`).join(''):'<p class="sub">None yet.</p>';
     $('#sl').querySelectorAll('a').forEach(a=>a.onclick=async()=>{S=await api('/api/sessions/'+a.dataset.id);chat()})})},
 add(){$('#main').innerHTML=`<div class="kicker">Add sources</div><h2>Add documents to the knowledge base</h2>
   <p class="sub">PDF, Word, e-mail (.eml), Teams transcripts (.vtt), Jira exports (.jira.json), text or code. Each file is saved unchanged; the model reads it and writes or updates the wiki pages; links and citations are checked; everything is committed. Cancel at any time.</p>
   <div class="drop" id="drop"><b>Drop files here</b> or click to choose<input type="file" id="file" multiple hidden></div><div id="jobs"></div>`;
   const d=$('#drop'),f=$('#file');d.onclick=()=>f.click();f.onchange=()=>upload([...f.files]);
   d.ondragover=e=>{e.preventDefault();d.classList.add('over')};d.ondragleave=()=>d.classList.remove('over');
   d.ondrop=e=>{e.preventDefault();d.classList.remove('over');upload([...e.dataTransfer.files])};
   api('/api/jobs').then(js=>js.forEach(j=>showJob(j,true)))}
};
async function upload(files){for(const file of files){const j=await api('/api/upload',{method:'POST',headers:{'X-Filename':encodeURIComponent(file.name)},body:file}).catch(e=>({error:e.message,filename:file.name,state:'error',log:[]}));showJob(j)}}
function showJob(j,once){let el=document.getElementById('job-'+j.id);if(!el){el=document.createElement('div');el.className='panel';el.id='job-'+j.id;$('#jobs')&&$('#jobs').prepend(el)}
  if(j.steps)STEPS=j.steps;const at=STEPS.indexOf(j.step);
  el.innerHTML=`<b>${esc(j.filename)}</b> <small class="sub">${j.bytes?Math.round(j.bytes/1024)+' KB':''}</small>
   <div class="steps">${STEPS.map((s,i)=>`<span class="${(j.state==='error'||j.state==='cancelled')&&i===Math.max(at,0)?'err':(i<at||j.state==='done'?'done':(i===at?'now':''))}">${s}</span>`).join('')}</div>
   ${j.error?`<p style="color:var(--bad)">${esc(j.error)}</p>`:''}
   <div style="display:flex;gap:8px;margin:6px 0">${j.state==='running'?`<button class="sec" onclick="cancelJob('${j.id}',false)">Cancel</button><button class="sec" onclick="cancelJob('${j.id}',true)">Cancel and remove file</button>`:
     (j.source_id&&!j.removed?`<button class="sec" onclick="removeSrc('${j.id}','${j.source_id}')">Remove from knowledge base</button>`:(j.removed?'<span class="sub">removed</span>':''))}</div>
   <div class="log">${(j.log||[]).map(l=>`${l.at} ${l.step}: ${esc(l.detail)}`).join('\n')}</div>`;
  if(j.state==='running'&&!once)setTimeout(()=>api('/api/jobs/'+j.id).then(x=>showJob(x)),1500);
  else if(j.state==='running'&&once)setTimeout(()=>api('/api/jobs/'+j.id).then(x=>showJob(x)),1500)}
window.cancelJob=async(id,rm)=>{if(rm&&!confirm('Stop and delete this file from the knowledge base?'))return;
  await api('/api/jobs/'+id+'/cancel',{method:'POST',body:JSON.stringify({remove:rm})}).catch(e=>alert(e.message))};
window.removeSrc=async(jid,sid)=>{if(!confirm('Delete this source, its facts and pages from the knowledge base? (one commit, can be undone with Git)'))return;
  try{await api('/api/sources/'+sid+'/remove',{method:'POST'});api('/api/jobs/'+jid).then(x=>showJob(x))}catch(e){alert(e.message)}};
function mdl(src){return esc(src).replace(/\*\*(.+?)\*\*/g,'<b>$1</b>').replace(/`([^`]+)`/g,'<code>$1</code>')
  .replace(/\[\[([^\]|#]+)(?:[|#]([^\]]*))?\]\]/g,(m,a,l)=>`<a class="cite" href="/dashboard?t=${ACCESS}#w:${encodeURIComponent(a.trim())}" target="_blank">${esc(l||a.trim())}</a>`)
  .split(/\n{2,}/).map(p=>/^\s*[-*] /m.test(p)?'<ul>'+p.split('\n').filter(x=>x.trim()).map(x=>'<li>'+x.replace(/^\s*[-*] /,'')+'</li>').join('')+'</ul>':'<p>'+p.replace(/\n/g,'<br>')+'</p>').join('')}
function renderTurn(t,i){if(t.markdown)return `<div class="turn"><div class="q">${esc(t.question)}</div><div class="a ${t.not_found?'nf':''}">${mdl(t.markdown)}</div>${t.images&&t.images.length?`<div class="sub" style="font-size:12px">🖼 ${t.images.map(esc).join(', ')}</div>`:''}${t.pages_read&&t.pages_read.length?`<div class="sub" style="font-size:12px">read: ${t.pages_read.slice(0,12).map(esc).join(', ')}${t.pages_read.length>12?' …':''}</div>`:''}</div>`;
  return `<div class="turn"><div class="q">${esc(t.question)}</div><div class="a">${t.not_found?'<p class="nf">No answer found in the knowledge base. Try other words, or add a source that covers it.</p>':
  t.sentences.map((s,k)=>`<p>${esc(s.text)}${s.cites.map((c,m)=>`<span class="cite" onclick="tg('${i}-${k}-${m}')">[${esc(c.title)} · ${esc(c.locator)}]</span>`).join('')}</p>`+
   s.cites.map((c,m)=>`<div class="ex" id="ex-${i}-${k}-${m}">${esc(c.excerpt)}…</div>`).join('')).join('')}</div></div>`}
window.tg=id=>{const e=document.getElementById('ex-'+id);e.style.display=e.style.display==='block'?'none':'block'};
function chat(){history.replaceState(null,'','#s='+S.id);$('#main').innerHTML=`<div class="kicker">Discussion</div><h2>${esc(S.topic)}</h2><p class="sub">Click a citation to see the excerpt it comes from.</p>
  <div class="panel" id="turns">${S.turns.map(renderTurn).join('')||'<p class="sub">Ask the first question.</p>'}</div>
  <div class="panel"><div class="row"><input type="text" id="q" placeholder="Your question… (paste a screenshot with Ctrl+V)"><button class="sec" id="att" title="Attach screenshot">📎</button><input type="file" id="img" accept="image/*" multiple hidden><button class="pri" id="ask">Ask</button></div>
  <div style="margin-top:8px;display:flex;gap:14px;align-items:center"><label class="sub" style="margin:0"><input type="checkbox" id="code"> question about the code</label><span id="imgs" class="sub" style="margin:0"></span></div>
  <div style="margin-top:10px;display:flex;gap:8px"><button class="sec" id="save">Save as wiki page</button><button class="sec" id="back">All discussions</button><span id="msg" class="sub" style="margin:6px 0 0 6px"></span></div></div>`;
  $('#back').onclick=()=>{history.replaceState(null,'','#');V.discuss()};
  $('#save').onclick=async()=>{const r=await api('/api/sessions/'+S.id+'/save',{method:'POST'}).catch(e=>({error:e.message}));$('#msg').textContent=r.saved?'saved: '+r.saved:r.error};
  let IM=[];const showIm=()=>$('#imgs').textContent=IM.length?('attached: '+IM.map(x=>x.name).join(', ')):'';
  const addFiles=fs=>{for(const f of fs){if(!f.type.startsWith('image/'))continue;const r=new FileReader();r.onload=()=>{IM.push({name:f.name||'screenshot.png',data:r.result});showIm()};r.readAsDataURL(f)}};
  $('#att').onclick=()=>$('#img').click();$('#img').onchange=()=>addFiles([...$('#img').files]);
  $('#q').onpaste=e=>{const fs=[...(e.clipboardData||{}).files||[]];if(fs.length){e.preventDefault();addFiles(fs)}};
  const go=async()=>{const q=$('#q').value.trim();if(!q)return;$('#ask').disabled=true;$('#msg').textContent='thinking… (the model reads the wiki'+($('#code').checked?' and the code':'')+')';
    try{const t=await api('/api/sessions/'+S.id+'/ask',{method:'POST',body:JSON.stringify({question:q,images:IM,focus:$('#code').checked?'code':'wiki'})});IM=[];showIm();S.turns.push(t);
      $('#turns').innerHTML=S.turns.map(renderTurn).join('');$('#q').value='';$('#msg').textContent=t.seconds?t.seconds+' s':''}
    catch(e){$('#msg').textContent=e.message}finally{$('#ask').disabled=false;$('#q').focus()}};
  $('#ask').onclick=go;$('#q').onkeydown=e=>{if(e.key==='Enter')go()};$('#q').focus()}
const hs=location.hash.match(/s=([0-9a-f]{12})/);
if(hs)api('/api/sessions/'+hs[1]).then(x=>{S=x;chat()}).catch(()=>V.discuss());else if(location.hash==='#add'){document.querySelectorAll('nav button').forEach(x=>x.classList.toggle('on',x.dataset.v==='add'));V.add()}else V.discuss();
</script></body></html>
"""
