"""Discussions: one long agent session per discussion (ADR-0019), kept in instance/sessions/<id>.json.

Follow-up questions build on what the model already read; after an ingest the open sessions are told which pages
changed; idle sessions close after IDLE_S and are resumed (or rebuilt from the saved turns) on the next question.
TRACE holds what the model is doing for the current question (the live view polls it).
"""
from __future__ import annotations

import base64
import json
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

from kb.core import gitops
from kb.knowledge import catalog, chat, pages, wiki
from kb.publish.server import WRITE_LOCK
from kb.publish.server.http import Handler, route

LIVE: dict[str, chat.Conversation] = {}  # discussion id -> open agent session
LIVE_LOCK = threading.Lock()
IDLE_S = 1800
TRACE: dict[str, dict] = {}  # discussion id -> {"running", "events"} for the current question


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


def reaper() -> None:
    while True:
        time.sleep(60)
        try:
            close_live(idle_only=True)
        except Exception:
            pass


def tell_discussions(result: dict | None) -> None:
    changed = (result or {}).get("created", []) + (result or {}).get("updated", [])
    if changed:
        with LIVE_LOCK:
            for c in LIVE.values():
                c.wiki_changed(changed)


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


@route("GET", r"/api/sessions")
def list_sessions(h):
    items = []
    for f in sorted(_sessions_dir().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:30]:
        s = json.loads(f.read_text(encoding="utf-8"))
        items.append({"id": s["id"], "topic": s["topic"], "turns": len(s["turns"]), "updated": s.get("updated")})
    return h.send(200, items)


@route("POST", r"/api/sessions")
def create_session(h):
    topic = (h.json_body().get("topic") or "").strip()[:200]
    if not topic:
        return h.send(400, {"error": "topic is required"})
    s = {"id": uuid.uuid4().hex[:12], "topic": topic, "created": catalog.now(), "updated": catalog.now(), "turns": []}
    _save_session(s)
    return h.send(200, s)


@route("GET", r"/api/sessions/([0-9a-f]{12})/progress")
def progress(h, sid):
    t = TRACE.get(sid) or {"running": False, "events": []}
    since = int(h.query("since", "0") or 0)
    return h.send(200, {"running": t["running"], "events": t["events"][since:], "total": len(t["events"])})


@route("GET", r"/api/sessions/([^/]+)")
def get_session(h, sid):
    return h.send(200, _load_session(sid))


@route("POST", r"/api/sessions/([0-9a-f]{12})/stop")
def stop(h, sid):
    conv = LIVE.get(sid)
    if not conv or not conv.stop():
        return h.send(409, {"error": "nothing is running in this discussion"})
    return h.send(200, {"ok": True})


@route("POST", r"/api/sessions/([0-9a-f]{12})/delete")
def delete(h, sid):
    """Delete a discussion: its saved turns, attached screenshots and open agent session. Wiki pages saved from it stay."""
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
    return h.send(200, {"deleted": sid})


@route("POST", r"/api/sessions/([0-9a-f]{12})/ask")
def ask(h, sid):
    s = _load_session(sid)
    body = h.json_body()
    q = (body.get("question") or "").strip()[:2000]
    if not q:
        return h.send(400, {"error": "question is required"})
    att = []
    for i, img in enumerate((body.get("images") or [])[:4]):
        ext = (Path(str(img.get("name") or "image.png")).suffix.lower() or ".png")
        if ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
            return h.send(400, {"error": f"unsupported image type {ext}"})
        data = base64.b64decode(str(img.get("data") or "").split(",")[-1])
        if len(data) > 10_000_000:
            return h.send(400, {"error": "image larger than 10 MB"})
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
    return h.send(200, turn)


@route("POST", r"/api/sessions/([0-9a-f]{12})/save")
def save_page(h, sid):
    s = _load_session(sid)
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
    return h.send(200, {"saved": str(p.relative_to(catalog.instance()))})
