"""Sources view: every ingested source with its quality assessment; assess the chosen ones again (read-only for the
wiki: it only writes raw/<id>/assessment.json). One run at a time, as the single writer, with progress and cancel."""
from __future__ import annotations

import threading
import time
import traceback

from kb.knowledge import assess
from kb.publish.server import WRITE_LOCK
from kb.publish.server.http import Handler, route

RUN: dict = {}  # the current or last run: state, total, done, log, cancel


def _run(ids: list[str], with_model: bool) -> None:
    say = lambda st, d: RUN["log"].append({"at": time.strftime("%H:%M:%S"), "step": st, "detail": d})  # noqa: E731
    try:
        with WRITE_LOCK:
            RUN["state"] = "running"

            def progress(st, d):
                say(st, d)
                if st == "assessed":
                    RUN["done"] += 1
            out = assess.backfill(with_model=with_model, ids=ids, force=True, runner=Handler.runner if with_model else None,
                                  progress=progress, cancelled=lambda: bool(RUN.get("cancel")))
        RUN["state"] = "cancelled" if RUN.get("cancel") and len(out) < RUN["total"] else "done"
    except Exception as e:  # shown in the view; details in the log
        RUN["state"] = "error"
        RUN["error"] = f"{type(e).__name__}: {e}"[:500]
        say("error", traceback.format_exc()[-1500:])


@route("GET", r"/api/sources/quality")
def quality(h):
    return h.send(200, {**assess.overview(), "run": RUN or None})


@route("POST", r"/api/sources/assess")
def start(h):
    """Assess the chosen sources again: {"ids": [...], "model": true} runs the model (AI credits per source);
    "model": false only measures again (free) and keeps the model's judgement."""
    body = h.json_body()
    ids = [i for i in body.get("ids") or [] if isinstance(i, str)][:2000]
    if not ids:
        return h.send(400, {"error": "choose at least one source"})
    if RUN.get("state") in ("queued", "running"):
        return h.send(409, {"error": "an assessment is already running"})
    RUN.clear()
    RUN.update({"state": "queued", "model": bool(body.get("model")), "total": len(ids), "done": 0, "log": [],
                "started": time.strftime("%H:%M:%S")})
    threading.Thread(target=_run, args=(ids, RUN["model"]), daemon=True).start()
    return h.send(200, RUN)


@route("POST", r"/api/sources/assess/cancel")
def cancel(h):
    if RUN.get("state") not in ("queued", "running"):
        return h.send(409, {"error": "no assessment is running"})
    RUN["cancel"] = True
    return h.send(200, {"ok": True, "note": "stops after the source being assessed now"})
