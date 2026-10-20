"""The browser app (kb/publish/web: index.html template, CSS, ES modules) and the wiki dashboard."""
from __future__ import annotations

import html
import json
from pathlib import Path
from urllib.parse import quote, unquote

from kb.core import config
from kb.publish import site
from kb.publish.server.http import route

WEB = Path(__file__).resolve().parent.parent / "web"
# explicit types: Python's mimetypes reads the Windows registry, which can map .js to text/plain and break the app
MIME = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png"}
EMBED_CSS = (b"<style>header{display:none}.wrap{min-height:100vh}nav{background:var(--card);border-right:1px solid var(--line)}"
             b"nav button{color:var(--ink2)}nav button:hover{background:var(--vio-soft);color:var(--vio)}</style>")
MARK = ('<svg class="mark" viewBox="0 0 32 32" aria-hidden="true"><defs><linearGradient id="mk" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#764bff"/><stop offset="1" stop-color="#2969f2"/></linearGradient></defs>'
        '<rect width="32" height="32" rx="9" fill="url(#mk)"/><path d="M8 10h5.5a2.5 2.5 0 0 1 2.5 2.5V23a2 2 0 0 0-2-2H8zM24 10h-5.5'
        'a2.5 2.5 0 0 0-2.5 2.5V23a2 2 0 0 1 2-2h6z" fill="none" stroke="#fff" stroke-width="1.8" stroke-linejoin="round"/></svg>')


@route("GET", r"/")
def index(h):
    title = (config.load("profile").get("instance") or {}).get("title") or "Knowledge base"
    brand = site._branding()
    if "<img" not in brand:  # no company logo in instance/branding: neutral mark
        brand = MARK + brand
    icon = site.branding_file("icon")  # company icon from instance/branding, else the neutral mark
    mark = f'<img class="mark" src="{site._data_uri(icon)}" alt="">' if icon else MARK
    fav = site._data_uri(icon) if icon else "data:image/svg+xml," + quote(MARK.replace('class="mark" ', ""))
    cfg = json.dumps({"access": h.token, "mark": mark}).replace("</", "<\\/")  # safe inside <script>
    page = ((WEB / "index.html").read_text(encoding="utf-8").replace("__CONFIG__", cfg)
            .replace("__TITLE__", html.escape(title)).replace("__LOGO__", brand).replace("__FAVICON__", fav))
    return h.send(200, page, "text/html; charset=utf-8")


@route("GET", r"/static/(.+)", public=True)  # the app's own code: no data, so no token (the server is 127.0.0.1 only)
def static(h, rel):
    f = (WEB / unquote(rel)).resolve()
    if WEB not in f.parents or not f.is_file() or f.suffix not in MIME:
        return h.send(404, {"error": "not found"})
    return h.send(200, f.read_bytes(), MIME[f.suffix])


@route("GET", r"/dashboard")
def dashboard(h):
    page = site.build().read_bytes()
    if h.query("embed"):  # inside the app: the app already shows the logo and title
        page = page.replace(b"</head>", EMBED_CSS + b"</head>", 1)
    return h.send(200, page, "text/html; charset=utf-8")
