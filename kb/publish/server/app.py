"""The `kb serve` server: binds 127.0.0.1, loads every route module, starts the idle-session reaper."""
from __future__ import annotations

import json
import os
import secrets
import socket
import time
import threading
import webbrowser
from http.server import ThreadingHTTPServer

from kb.core import config, singleton
from kb.knowledge import catalog
from kb.llm.gateway import Gateway
from kb.publish import applog, updater
from kb.publish.server import chat_api, feedback_api, ingest_api, pack_api, settings_api, update_api, web  # noqa: F401  (importing registers their routes)
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


def _restart_file():
    return config.paths().root / "local" / "restart.json"


def _resumed() -> dict | None:
    """After an update the launcher starts the app again: same port and token, so the open browser tab keeps working."""
    f = _restart_file()
    try:
        r = json.loads(f.read_text(encoding="utf-8"))
        f.unlink()
        return r if time.time() - r.get("at", 0) < 300 else None
    except (OSError, ValueError):
        return None


def make_server(port: int = 8765, gw: Gateway | None = None, adapter: str | None = None, token: str | None = None) -> ThreadingHTTPServer:
    catalog.init()
    Handler.token = token or secrets.token_urlsafe(16)
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


def _warm_up() -> None:
    """Do the slow first-time work now, not when someone opens Settings or Wiki: load the Windows secret store, read
    the state of the code repositories (git status), build the dashboard if the wiki changed."""
    from kb.knowledge import chat
    from kb.publish import settings, site
    for step in (settings.secrets_state, chat.repos, lambda: site.build(force=False)):
        try:
            step()
        except Exception:  # noqa: BLE001  warming up must never stop the app
            pass


ALREADY_RUNNING = 4  # exit code: another kb serve already runs this knowledge base (its address was opened instead)


def _running_file():
    return catalog.instance() / ".cache" / "serve.json"


def running_url(wait: float = 0) -> str | None:
    """The address of the kb serve that holds this knowledge base, waiting up to `wait` s while it starts."""
    end = time.time() + wait
    while True:
        try:
            return json.loads(_running_file().read_text(encoding="utf-8"))["url"]
        except (OSError, ValueError, KeyError):
            if time.time() >= end:
                return None
            time.sleep(0.5)


def serve(port: int = 8765, open_browser: bool = True, adapter: str | None = None) -> int:
    """Runs until Ctrl+C (0) or an update asks for a restart (updater.RESTART_CODE, for the launcher). One per
    knowledge base: a second start (a double double-click, Wiki.cmd --console next to the tray, kb serve in a terminal)
    opens the running one and exits with ALREADY_RUNNING, so two servers never write the same wiki."""
    lock = singleton.Lock(catalog.instance() / ".cache" / "serve.lock")
    if not lock.acquire():
        url = running_url(wait=60)
        print(f"this knowledge base is already open: {url or 'the other copy is still starting'}", flush=True)
        if url and open_browser:
            webbrowser.open(url)
        return ALREADY_RUNNING
    try:
        return _serve(port, open_browser, adapter)
    finally:
        try:
            _running_file().unlink()
        except OSError:
            pass
        lock.release()


def _serve(port: int, open_browser: bool, adapter: str | None) -> int:
    log = applog.start()
    print(f"log: {log}", flush=True)
    resumed = _resumed()
    httpd = make_server(resumed["port"] if resumed else port, adapter=adapter, token=resumed and resumed["token"])
    port = httpd.server_address[1]
    url = f"http://127.0.0.1:{port}/?t={Handler.token}"
    _running_file().write_text(json.dumps({"url": url, "pid": os.getpid()}), encoding="utf-8")
    print(f"woynich-wiki is running at {url}\nKeep this window open; press Ctrl+C to stop.", flush=True)
    if open_browser and not resumed:
        webbrowser.open(url)
    stop = threading.Event()
    threading.Thread(target=updater.background, args=(stop,), daemon=True, name="kb-update-check").start()
    threading.Thread(target=_warm_up, daemon=True, name="kb-warm-up").start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("stopped")
    finally:
        stop.set()
        chat_api.close_live()
        httpd.server_close()
    if updater.RESTART.is_set():
        f = _restart_file()
        f.parent.mkdir(exist_ok=True)
        f.write_text(json.dumps({"port": port, "token": Handler.token, "at": time.time()}), encoding="utf-8")
        print("Updated: restarting…", flush=True)
        return updater.RESTART_CODE
    return 0
