"""Feedback: Luna's short interview and the package on the Desktop (kb/publish/feedback.py does the work)."""
from __future__ import annotations

from pathlib import Path

from kb.publish import feedback
from kb.publish.server import ingest_api
from kb.publish.server.http import route


@route("POST", r"/api/feedback/chat")
def chat(h):
    msgs = h.json_body().get("messages") or []
    if not msgs or msgs[0].get("role") != "user" or not str(msgs[0].get("text") or "").strip():
        raise ValueError("write what happened first")
    return h.send(200, feedback.converse(h.gw, msgs[-12:]))


@route("POST", r"/api/feedback/package")
def package(h):
    b = h.json_body()
    return h.send(200, feedback.package(str(b.get("text") or ""), b.get("report"), b.get("messages") or [],
                                        b.get("screenshots") or [], h.gw, ingest_api.JOBS.values()))


@route("POST", r"/api/feedback/reveal")
def reveal(h):
    p = str(h.json_body().get("path") or "")
    if not p.endswith(".zip") or not Path(p).name.startswith("wiki-feedback-") or not Path(p).exists():
        raise ValueError("no such feedback package")
    feedback.reveal(p)
    return h.send(200, {"ok": True})
