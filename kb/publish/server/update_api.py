"""Updates of the app (check, apply, roll back; kb/publish/updater.py does the work) and the changelog."""
from __future__ import annotations

import threading

from kb.publish import changelog, updater
from kb.publish.server import WRITE_LOCK, chat_api, ingest_api
from kb.publish.server.http import route


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
def changelog_groups(h):
    return h.send(200, changelog.groups())
