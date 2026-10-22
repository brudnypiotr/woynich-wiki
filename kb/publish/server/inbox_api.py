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
    """{share_usage, user}: this user's choices; {inbox: {folder, share_url, contact}}: the team's inbox (branding)."""
    b = h.json_body()
    if isinstance(b.get("inbox"), dict):
        i = b["inbox"]
        inbox.configure(i.get("folder"), i.get("share_url"), i.get("contact"))
    if "share_usage" in b or "user" in b:
        inbox.set_prefs(share_usage=bool(b["share_usage"]) if "share_usage" in b else None,
                        user=str(b["user"]).strip() if "user" in b else None)
    return h.send(200, inbox.status())


@route("POST", r"/api/inbox/open-share")
def open_share(h):
    url = str(inbox.config().get("share_url") or "")
    if not url.startswith("https://"):
        raise ValueError("no share link in the branding (inbox.share_url)")
    webbrowser.open(url)
    return h.send(200, {"ok": True})
