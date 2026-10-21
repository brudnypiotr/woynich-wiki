"""The HTTP layer of `kb serve`: a route table and the request handler. No knowledge of the API itself.

Modules register their routes with `@route(method, pattern)`; the handler is called as `fn(h, *groups)` where `h` is the
request (reply with `h.send`, read with `h.json_body`). Exceptions become JSON errors: ValueError → 400,
KeyError/FileNotFoundError → 404, anything else → 500. Every route needs the session token unless `public=True`.
"""
from __future__ import annotations

import json
import re
import secrets
import sys
import time
import traceback
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from kb.llm.gateway import Gateway

ROUTES: list[tuple[str, re.Pattern, object, bool]] = []
SLOW_OK = ("/ask", "/upload", "/api/usage", "/api/settings/account", "/api/settings/models", "/api/settings/check", "/api/update", "/api/pack/export", "/api/pack/import", "/api/feedback/chat", "/api/feedback/package")  # slow by nature


def route(method: str, pattern: str, public: bool = False):
    def deco(fn):
        ROUTES.append((method, re.compile(pattern), fn, public))
        return fn
    return deco


class Handler(BaseHTTPRequestHandler):
    server_version = "woynich-wiki"
    token = ""
    gw: Gateway | None = None
    runner = None  # agent runner (tests replace it)

    def log_message(self, fmt, *args):  # quiet console
        pass

    @property
    def url(self):
        return urlparse(self.path)

    def query(self, name: str, default: str = "") -> str:
        return (parse_qs(self.url.query).get(name) or [default])[0]

    def send(self, code: int, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else (json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
                                                      if not isinstance(body, str) else body.encode("utf-8"))
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def json_body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n).decode("utf-8") or "{}") if n else {}

    def authorised(self) -> bool:
        return secrets.compare_digest(self.headers.get("X-KB-Token", "") or self.query("t"), self.token)

    def handle_one_request(self):
        t0 = time.perf_counter()
        super().handle_one_request()
        took = time.perf_counter() - t0
        path = urlparse(getattr(self, "path", "") or "").path
        if took > 2 and not path.endswith(SLOW_OK):
            print(f"slow request: {getattr(self, 'command', '')} {path} took {took:.1f} s", flush=True)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def _dispatch(self, method: str):
        path = self.url.path
        for meth, rx, fn, public in ROUTES:
            m = rx.fullmatch(path) if meth == method else None
            if not m:
                continue
            if not public and not self.authorised():
                if path == "/":
                    return self.send(403, "Open the link printed by `kb serve` (it contains the access token).", "text/plain; charset=utf-8")
                return self.send(403, {"error": "missing or wrong token"})
            try:
                return fn(self, *m.groups())
            except ValueError as e:
                return self.send(400, {"error": str(e)[:500]})
            except (KeyError, FileNotFoundError):
                return self.send(404, {"error": "no such discussion"})
            except Exception as e:
                traceback.print_exc()  # into the app log (local/logs/serve.log) for support and feedback packages
                print(f"error in {method} {path}: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
                return self.send(500, {"error": f"{type(e).__name__}: {e}"[:500]})
        if not self.authorised():
            return self.send(403, {"error": "missing or wrong token"})
        return self.send(404, {"error": "not found"})
