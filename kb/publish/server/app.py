"""The `kb serve` server: binds 127.0.0.1, loads every route module, starts the idle-session reaper."""
from __future__ import annotations

import os
import secrets
import socket
import threading
import webbrowser
from http.server import ThreadingHTTPServer

from kb.knowledge import catalog
from kb.llm.gateway import Gateway
from kb.publish.server import chat_api, ingest_api, settings_api, web  # noqa: F401  (importing registers their routes)
from kb.publish.server.http import Handler


class _Server(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second server bind a port another one already listens on, without an error;
    # the browser then reaches the old server, whose token differs ("open the link printed by kb serve").
    allow_reuse_address = os.name != "nt"
    daemon_threads = True

    def server_bind(self):
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def make_server(port: int = 8765, gw: Gateway | None = None, adapter: str | None = None) -> ThreadingHTTPServer:
    catalog.init()
    Handler.token = secrets.token_urlsafe(16)
    Handler.gw = gw or Gateway(adapter=adapter)
    for p in ([port] if port == 0 else range(port, port + 10)):
        try:
            httpd = _Server(("127.0.0.1", p), Handler)
            break
        except OSError:
            if p != port:
                continue
            print(f"port {port} is in use (another kb serve still running?); trying the next one", flush=True)
    else:
        raise OSError(f"ports {port}-{port + 9} are all in use; stop other kb serve windows")
    threading.Thread(target=chat_api.reaper, daemon=True, name="kb-reaper").start()
    return httpd


def serve(port: int = 8765, open_browser: bool = True, adapter: str | None = None) -> None:
    httpd = make_server(port, adapter=adapter)
    port = httpd.server_address[1]
    url = f"http://127.0.0.1:{port}/?t={Handler.token}"
    print(f"woynich-wiki is running at {url}\nKeep this window open; press Ctrl+C to stop.", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("stopped")
    finally:
        chat_api.close_live()
        httpd.server_close()
