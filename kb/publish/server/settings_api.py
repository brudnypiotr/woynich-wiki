"""Settings, keys and tokens, GitHub Copilot sign-in, AI-credit usage and the status line (kb/publish/settings.py does the work)."""
from __future__ import annotations

import threading
import time

from kb.knowledge import catalog, pages
from kb.publish import branding, diagnostics, settings, updater
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


@route("GET", r"/api/setup")
def setup(h):
    return h.send(200, settings.setup_state())


@route("POST", r"/api/setup/(done|reset)")
def setup_mark(h, what):
    return h.send(200, settings.setup_done(what == "done"))


@route("GET", r"/api/about")
def about(h):
    return h.send(200, diagnostics.version())


@route("GET", r"/api/diagnostics")
def diagnostics_report(h):
    return h.send(200, diagnostics.report(h.gw, list(ingest_api.JOBS.values())))


def update_blocker() -> str | None:
    """Why an update must wait: a restart would cut an ingest (queued sources included) or an answer being written."""
    n = len(ingest_api.QUEUE)
    if n or WRITE_LOCK.locked():
        return f"Sources are being added to the wiki{f' ({n} in the queue)' if n else ''}. Update when Add sources is done."
    if any(c.lock.locked() for c in list(chat_api.LIVE.values())):
        return "An answer is being written. Update when it is done."
    return None


@route("GET", r"/api/update")
def update_state(h):
    u = updater.check() if h.query("refresh") or not updater.last() else updater.last()
    return h.send(200, {**u, "blocked": update_blocker()})


@route("POST", r"/api/update/(apply|rollback)")
def update_run(h, what):
    if (why := update_blocker()):
        raise ValueError(why)
    try:
        out = updater.apply() if what == "apply" else updater.rollback()
    except updater.UpdateError as e:
        raise ValueError(str(e)) from e
    if out.get("restart"):
        out["launcher"] = updater.launched()
        if out["launcher"]:  # the launcher starts the app again with the same address and token
            updater.RESTART.set()
            threading.Timer(0.5, h.server.shutdown).start()
    return h.send(200, out)


@route("GET", r"/api/changelog")
def changelog(h):
    return h.send(200, updater.changelog())


@route("GET", r"/api/branding")
def branding_state(h):
    return h.send(200, branding.state())


@route("POST", r"/api/branding")
def branding_import(h):
    n = int(h.headers.get("Content-Length") or 0)
    if not n or n > branding.MAX_ZIP:
        raise ValueError("choose a branding .zip file")
    return h.send(200, branding.import_zip(h.rfile.read(n)))


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
