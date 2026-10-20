"""Add sources: uploads become jobs, ingested one at a time in upload order (single writer), with visible steps."""
from __future__ import annotations

import json
import shutil
import tempfile
import threading
import time
import traceback
import uuid
from pathlib import Path
from urllib.parse import unquote

from kb.knowledge import catalog, verify, wiki
from kb.llm.gateway import Gateway
from kb.publish import site
from kb.publish.server import WRITE_LOCK, chat_api
from kb.publish.server.http import Handler, route

MAX_UPLOAD = 200_000_000
JOBS: dict[str, dict] = {}
STEPS = ["saved", "extracted", "writing", "checking", "verify", "done"]
QUEUE: list[str] = []  # job ids in upload order; the first one is being ingested (one at a time)
QCOND = threading.Condition()


def _job_step(job: dict, step: str, detail: str = "") -> None:
    if job.get("cancel"):
        raise wiki.Cancelled()
    job["step"] = "writing" if step == "reading" else step  # the model reads and writes in one step
    job["log"].append({"at": time.strftime("%H:%M:%S"), "step": step, "detail": detail})


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
                chat_api.tell_discussions(job["result"])
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


@route("POST", r"/api/upload")
def upload(h):
    name = Path(unquote(h.headers.get("X-Filename") or "upload.bin")).name
    n = int(h.headers.get("Content-Length") or 0)
    if not n or n > MAX_UPLOAD:
        return h.send(400, {"error": f"file size must be between 1 byte and {MAX_UPLOAD // 1_000_000} MB"})
    tmp = Path(tempfile.mkdtemp(prefix="kb-upload-")) / name
    with tmp.open("wb") as f:
        left = n
        while left:
            chunk = h.rfile.read(min(left, 1 << 20))
            if not chunk:
                break
            f.write(chunk); left -= len(chunk)
    job = {"id": uuid.uuid4().hex[:12], "filename": name, "bytes": n, "state": "queued", "step": "queued",
           "started": catalog.now(), "seq": len(JOBS), "log": [], "steps": STEPS}
    JOBS[job["id"]] = job
    with QCOND:
        QUEUE.append(job["id"])
    threading.Thread(target=run_ingest_job, args=(job, tmp, h.gw), daemon=True).start()
    return h.send(200, _job_view(job))


@route("GET", r"/api/jobs")
def jobs(h):  # everything waiting or running, plus the 30 most recent finished
    js = sorted(JOBS.values(), key=lambda j: j["seq"], reverse=True)
    live = [j for j in js if j["state"] in ("queued", "running")]
    return h.send(200, [_job_view(j) for j in live + [j for j in js if j not in live][:30]])


@route("GET", r"/api/jobs/([^/]+)")
def job(h, jid):
    j = JOBS.get(jid)
    return h.send(200, _job_view(j)) if j else h.send(404, {"error": "no such job"})


@route("POST", r"/api/jobs/([0-9a-f]{12})/cancel")
def cancel(h, jid):
    j = JOBS.get(jid)
    if not j or j["state"] not in ("queued", "running"):
        return h.send(409, {"error": "job is not running"})
    j["cancel"] = True
    j["remove_on_cancel"] = bool(h.json_body().get("remove"))
    return h.send(200, {"ok": True, "note": "stops after the current step (a model call can take ~30 s)"})


@route("POST", r"/api/sources/([0-9a-f]{12})/remove")
def remove_source(h, sid):
    if not WRITE_LOCK.acquire(timeout=1):
        return h.send(409, {"error": "an ingest is running; cancel it first"})
    try:
        r = catalog.remove(sid)
    finally:
        WRITE_LOCK.release()
    for j in JOBS.values():
        if j.get("source_id") == sid:
            j["removed"] = True
    return h.send(200, r)
