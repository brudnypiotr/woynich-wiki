"""The inbox (feedback and usage for the app's author, kb/publish/inbox.py): state, the usage switch, opening the share."""
from __future__ import annotations

import webbrowser

from kb.publish import inbox
from kb.publish.server.http import route


@route("GET", r"/api/inbox")
def state(h):
    return h.send(200, inbox.status())


@route("POST", r"/api/inbox")
def save(h):
    b = h.json_body()
    return h.send(200, inbox.set_prefs(share_usage=bool(b.get("share_usage", True))))


@route("POST", r"/api/inbox/open-share")
def open_share(h):
    url = str(inbox.config().get("share_url") or "")
    if not url.startswith("https://"):
        raise ValueError("no share link in the branding (inbox.share_url)")
    webbrowser.open(url)
    return h.send(200, {"ok": True})
