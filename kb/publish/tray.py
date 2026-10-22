"""`kb tray`: the app without a console window. Wiki.cmd starts it with pythonw; it shows an icon in the notification
area and runs `kb serve` as a hidden child process:

- the first start opens the browser (kb serve does), the icon's default action opens it again;
- after Update the child exits with RESTART_CODE: the tray runs `kb update --finish` and starts it again (the same
  address and token, so the open page comes back by itself); this is what the console loop in Wiki.cmd did;
- when the app stops with an error the icon turns red and says so; the menu offers Update and restart and Show log;
- a second double-click finds the running app (local/tray.json) and only opens the browser.

Logs: the child's output goes to local/logs/serve.log (applog), the tray's own events to local/logs/tray.log.
`Wiki.cmd --console` keeps the old way: the app in a console window.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

from kb.publish import appgit, applog, branding, updater

URL = re.compile(r"running at (http://127\.0\.0\.1:\d+/\?t=[\w-]+)")
NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW


def log(msg: str) -> None:
    with (applog.folder() / "tray.log").open("a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")


def state_file() -> Path:
    """One per copy and knowledge base (Wiki.cmd C:\\kb\\other-instance runs its own app next to the default one)."""
    inst = os.environ.get("KB_INSTANCE", "")
    tag = re.sub(r"[^\w-]+", "-", inst).strip("-")[-60:] if inst else ""
    return appgit.local() / (f"tray-{tag}.json" if tag else "tray.json")


def kb_command(*args: str) -> list[str]:
    """This copy's own code, as kb.cmd runs it; python.exe (not pythonw) so the child has normal stdout."""
    py = Path(sys.executable)
    if py.name.lower() == "pythonw.exe" and (py.parent / "python.exe").exists():
        py = py.parent / "python.exe"
    root = str(appgit.root())
    return [str(py), "-c", f"import sys; sys.path.insert(0, {root!r}); from kb.cli import main; sys.exit(main())", *args]


def running_url() -> str | None:
    """The address of an app this copy already runs (a second double-click), when it still answers."""
    try:
        url = json.loads(state_file().read_text(encoding="utf-8"))["url"]
        urllib.request.urlopen(url, timeout=2).close()
        return url
    except (OSError, ValueError, KeyError):
        return None


class Supervisor:
    """Runs `kb serve` until it stops for good; restarts it after an update. No GUI here, so it is testable."""

    def __init__(self, command=None, finish=None, on_state=None):
        self.command = command or kb_command("serve")
        self.finish = finish or kb_command("update", "--finish")
        self.on_state = on_state or (lambda state, detail: None)
        self.url: str | None = None
        self.proc: subprocess.Popen | None = None
        self.quitting = False
        self.code: int | None = None

    def _env(self) -> dict:
        return {**os.environ, "KB_LAUNCHER": "1", "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}

    def _read(self, proc) -> None:
        for line in proc.stdout:
            m = URL.search(line)
            if m:  # every start, also a restart with the same address
                self.url = m[1]
                state_file().write_text(json.dumps({"url": self.url, "pid": os.getpid()}), encoding="utf-8")
                self.on_state("running", self.url)

    def run(self) -> int:
        """Blocks; returns the last exit code of kb serve (0 after Quit)."""
        while True:
            self.on_state("starting", "")
            log(f"start: {' '.join(self.command[:1] + self.command[3:])}")
            self.proc = subprocess.Popen(self.command, cwd=str(appgit.root()), env=self._env(), stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True,
                                         encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
            reader = threading.Thread(target=self._read, args=(self.proc,), daemon=True)
            reader.start()
            self.code = self.proc.wait()
            reader.join(timeout=2)
            log(f"kb serve exited with {self.code}")
            if self.code == updater.RESTART_CODE and not self.quitting:
                self.on_state("updating", "restarting (installing the update, if any)")
                r = subprocess.run(self.finish, cwd=str(appgit.root()), env=self._env(), capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
                log(f"update --finish: {r.returncode} {(r.stdout + r.stderr).strip()[-300:]}")
                continue
            if self.quitting or self.code == 0:
                self.on_state("stopped", "")
                return 0
            self.on_state("error", f"the app stopped with an error ({self.code})")
            return self.code

    def quit(self, timeout: float = 15) -> None:
        """Ask kb serve to stop cleanly (it closes the model sessions), else end it."""
        self.quitting = True
        p = self.proc
        if not p or p.poll() is not None:
            return
        if self.url:
            try:
                base, token = self.url.split("/?t=")
                req = urllib.request.Request(f"{base}/api/app/quit", data=b"{}", method="POST",
                                             headers={"X-KB-Token": token, "Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=5).close()
                p.wait(timeout=timeout)
                return
            except (OSError, ValueError, subprocess.TimeoutExpired):
                pass
        p.terminate()

    def restart(self) -> None:
        """Stop kb serve; run() starts it again (as after an update)."""
        p = self.proc
        if p and p.poll() is None and self.url:
            base, token = self.url.split("/?t=")
            req = urllib.request.Request(f"{base}/api/app/restart", data=b"{}", method="POST",
                                         headers={"X-KB-Token": token, "Content-Type": "application/json"})
            try:
                urllib.request.urlopen(req, timeout=5).close()
            except OSError:
                p.terminate()


# ------------------------------------------------------------------ the icon (Windows; pystray + Pillow)

COLORS = {"starting": (150, 150, 158), "updating": (240, 160, 30), "running": (40, 170, 90), "error": (220, 50, 60),
          "stopped": (150, 150, 158)}


def icon_image(state: str):
    """The app's icon (branding, else the neutral one) with a small status dot in the corner."""
    from PIL import Image, ImageDraw
    base = None
    for p in (Path(os.environ.get("LOCALAPPDATA", "")) / "woynich-wiki" / "app.ico", appgit.root() / "setup" / "app.ico"):
        try:
            base = Image.open(p).convert("RGBA").resize((64, 64))
            break
        except OSError:
            continue
    img = base or Image.new("RGBA", (64, 64), (60, 70, 160, 255))
    d = ImageDraw.Draw(img)
    d.ellipse((40, 40, 63, 63), fill=COLORS.get(state, COLORS["starting"]) + (255,), outline=(255, 255, 255, 255), width=3)
    return img


def run() -> int:
    """`kb tray`: one per copy; a second start just opens the browser."""
    url = running_url()
    if url:
        webbrowser.open(url)
        return 0
    import pystray
    name = branding.app_name()
    sup: Supervisor
    icon: pystray.Icon

    def on_state(state: str, detail: str) -> None:
        log(f"state {state} {detail[:80] if state != 'running' else ''}")
        try:
            icon.icon = icon_image(state)
            icon.title = f"{name}: {detail or state}"[:120]
            if state == "error":
                icon.notify(f"{detail}. Right-click the icon: Show log, or Update and restart.", name)
            icon.update_menu()
        except Exception:  # noqa: BLE001  the icon may not be up yet
            pass

    def open_app(_=None, __=None):
        if sup.url:
            webbrowser.open(sup.url)

    def start_supervisor():
        code = sup.run()
        if code == 0:
            icon.stop()

    def restart(_=None, __=None):
        if sup.proc and sup.proc.poll() is None:
            sup.restart()
        else:
            sup.quitting = False
            threading.Thread(target=start_supervisor, daemon=True).start()

    def update_restart(_=None, __=None):
        r = subprocess.run(kb_command("update"), cwd=str(appgit.root()), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
        log(f"update: {r.returncode} {(r.stdout + r.stderr).strip()[-300:]}")
        restart()

    def show_log(_=None, __=None):
        f = applog.folder() / "serve.log"
        if hasattr(os, "startfile"):
            os.startfile(str(f if f.exists() else applog.folder()))  # noqa: S606

    def quit_app(_=None, __=None):
        sup.quit()
        icon.stop()

    error = lambda _item: sup.code not in (None, 0, updater.RESTART_CODE) and (not sup.proc or sup.proc.poll() is not None)
    menu = pystray.Menu(
        pystray.MenuItem(f"Open {name}", open_app, default=True),
        pystray.MenuItem("Update and restart", update_restart, visible=error),
        pystray.MenuItem("Restart", restart),
        pystray.MenuItem("Show log", show_log),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", quit_app),
    )
    icon = pystray.Icon("woynich-wiki", icon_image("starting"), name, menu)
    sup = Supervisor(on_state=on_state)
    log("tray started")
    threading.Thread(target=start_supervisor, daemon=True).start()
    icon.run()
    try:
        state_file().unlink()
    except OSError:
        pass
    log("tray stopped")
    return 0
