"""Settings, keys and tokens, GitHub Copilot sign-in, AI-credit usage and the status line (kb/publish/settings.py does the work)."""
from __future__ import annotations

import time

from kb.knowledge import catalog, pages
from kb.publish import settings
from kb.publish.server import WRITE_LOCK, chat_api, ingest_api
from kb.publish.server.http import route

USAGE: dict = {"at": 0.0, "data": None}  # billing state, cached: reading it starts the Copilot runtime (seconds)


@route("GET", r"/api/settings")
def get_settings(h):
    return h.send(200, settings.state())


@route("POST", r"/api/settings")
def save_settings(h):
    body = h.json_body()
    out = settings.save(body)
    if {"model", "profile", "repos"} & set(body):
        chat_api.close_live(fresh=True)  # sessions were opened with the old model, Jira tools or repositories
    return h.send(200, out)


@route("GET", r"/api/settings/check")
def check(h):
    return h.send(200, settings.check(h.gw, h.query("what", "all")))


@route("GET", r"/api/settings/(models|account)")
def copilot_info(h, what):
    try:
        return h.send(200, settings.models_available(h.gw) if what == "models" else settings.account(h.gw))
    except Exception as e:
        return h.send(502, {"error": f"{type(e).__name__}: {e}"[:500]})


@route("POST", r"/api/settings/login")
def login(h):
    return h.send(200, settings.login())


@route("POST", r"/api/secrets/([a-z0-9-]{1,40})(/delete)?")
def secret(h, name, delete):
    return h.send(200, settings.secret_delete(name) if delete else settings.secret_set(name, str(h.json_body().get("value") or "")))


@route("GET", r"/api/usage")
def usage(h):
    if h.query("refresh") or not USAGE["data"] or time.time() - USAGE["at"] > 300:  # real reading from GitHub: every 5 min
        USAGE.update(at=time.time(), data=settings.usage(h.gw))
    return h.send(200, settings.usage_estimate(USAGE["data"]))  # + what kb used since then


@route("GET", r"/api/status")
def status(h):
    srcs = catalog.all_sources()
    return h.send(200, {"sources": len(srcs), "pages": sum(1 for _ in pages.wiki().rglob("*.md")) if pages.wiki().exists() else 0,
                        "busy": WRITE_LOCK.locked(), "queued": max(0, len(ingest_api.QUEUE) - 1), "model": settings.effective_model()})
