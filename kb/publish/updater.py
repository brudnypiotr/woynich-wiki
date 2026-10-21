"""Updates of this copy of the app from its Git remote (the changelog is in kb/publish/changelog.py).

One click for people who are not technical: `check()` fetches and counts the new commits, `apply()` fast-forwards (local
edits are stashed, local commits kept on a backup branch), notes whether requirements.txt changed and asks for a restart;
the launcher (`Wiki.cmd`) starts the app again when it exits with RESTART_CODE and runs `kb update --finish`
first (packages). `rollback()` goes back to the commit before the last update.

A copy unpacked from a ZIP has no .git: `attach()` makes it a clone of the official remote (setup/sources.json → update)
without touching the instance or other ignored files.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

from kb.publish import appgit, changelog

RESTART_CODE = 3          # `kb serve` exit code that asks the launcher to start it again
CHECK_EVERY_S = 3600      # background check while `kb serve` runs
DEFAULT = {"remote": "https://github.com/brudnypiotr/woynich-wiki.git", "branch": "main"}

UpdateError = appgit.GitError  # what update callers catch

_LOCK = threading.Lock()
_LAST: dict | None = None
RESTART = threading.Event()  # set after apply/rollback: `kb serve` stops and exits with RESTART_CODE


def settings() -> dict:
    """Where updates come from: setup/sources.json → "update" (the one place to change for a company mirror)."""
    try:
        s = json.loads((appgit.root() / "setup" / "sources.json").read_text(encoding="utf-8")).get("update") or {}
    except (OSError, ValueError):
        s = {}
    return {**DEFAULT, **{k: v for k, v in s.items() if k in DEFAULT and v}}


def launched() -> bool:
    """Started by `Wiki.cmd`, which restarts the app after an update."""
    return bool(os.environ.get("KB_LAUNCHER"))


def attach() -> dict:
    """Make a ZIP copy a clone of the official remote, or add the remote when a clone has none. Never changes an
    existing origin (a developer's SSH remote stays). Ignored files (instance/, .venv, kb.cmd) are untouched."""
    s = settings()
    if not appgit.is_clone():
        appgit.git("init", "-q", "-b", s["branch"])
        appgit.git("remote", "add", "origin", s["remote"])
        appgit.git("fetch", "-q", "origin", s["branch"], timeout=600)
        appgit.git("reset", "-q", "--hard", f"origin/{s['branch']}")
        appgit.git("branch", "-q", "-u", f"origin/{s['branch']}")
        return {"attached": True, "remote": s["remote"], "commit": appgit.git("rev-parse", "--short", "HEAD")}
    if "origin" not in appgit.git("remote").split():
        appgit.git("remote", "add", "origin", s["remote"])
        return {"attached": True, "remote": s["remote"]}
    return {"attached": False, "remote": appgit.git("remote", "get-url", "origin")}


def check(fetch: bool = True) -> dict:
    """Is there a newer version on the remote? Fetches (unless fetch=False) and lists the incoming commits."""
    global _LAST
    s = settings()
    with _LOCK:
        if not appgit.is_clone():
            _LAST = {"available": False, "clone": False, "error": "this copy has no Git history: run setup.cmd again",
                     "checked_at": time.time()}
            return _LAST
        out = {"available": False, "clone": True, "behind": 0, "ahead": 0, "incoming": [], "error": None,
               "branch": s["branch"], "launcher": launched(), "checked_at": time.time()}
        try:
            if fetch:
                appgit.git("fetch", "-q", "origin", s["branch"], timeout=90)
            up = f"origin/{s['branch']}"
            ahead, behind = (int(x) for x in appgit.git("rev-list", "--left-right", "--count", f"HEAD...{up}").split())
            out.update(ahead=ahead, behind=behind, available=behind > 0, current=appgit.git("rev-parse", "--short", "HEAD"),
                       latest=appgit.git("rev-parse", "--short", up), incoming=changelog.commits(f"HEAD..{up}", 200),
                       dirty=bool(appgit.git("status", "--porcelain", "--untracked-files=no")),
                       latest_version=appgit.version_at(up), current_version=appgit.version_at("HEAD"))
        except (UpdateError, ValueError) as e:
            out["error"] = str(e)[:400]
        _LAST = out
        return out


def last() -> dict | None:
    return _LAST


def _requirements_changed(old: str, new: str) -> bool:
    return bool(appgit.git("diff", "--name-only", old, new, "--", "requirements.txt", check=False))


def apply() -> dict:
    """Move this copy to the newest version. Local edits are stashed, local commits saved on a backup branch.
    Returns what happened; the caller restarts the app (and `kb update --finish` installs packages if needed)."""
    s = settings()
    with _LOCK:
        if not appgit.is_clone():
            raise UpdateError("this copy has no Git history: run setup.cmd again")
        up = f"origin/{s['branch']}"
        appgit.git("fetch", "-q", "origin", s["branch"], timeout=300)
        old = appgit.git("rev-parse", "HEAD")
        new = appgit.git("rev-parse", up)
        if old == new:
            return {"updated": False, "message": "Already up to date."}
        notes = []
        if appgit.git("status", "--porcelain", "--untracked-files=no"):
            appgit.git("stash", "push", "-m", f"kb update {time.strftime('%Y-%m-%d %H:%M')}")
            notes.append("local edits were put aside (git stash)")
        (appgit.local() / "update-previous").write_text(old, encoding="utf-8")
        appgit.git("merge", "-q", "--ff-only", up, check=False)
        if appgit.git("rev-parse", "HEAD") != new:  # local commits: keep them on a branch and take the official version
            backup = f"backup/{time.strftime('%Y%m%d-%H%M%S')}"
            appgit.git("branch", backup, old)
            appgit.git("reset", "-q", "--hard", up)
            notes.append(f"local commits kept on branch {backup}")
        deps = _requirements_changed(old, new)
        if deps:
            (appgit.local() / "update-deps").write_text(new, encoding="utf-8")
        return {"updated": True, "from": old[:7], "to": new[:7], "version": appgit.version_at("HEAD"),
                "packages": deps, "notes": notes, "restart": True}


def rollback() -> dict:
    """Back to the commit before the last update (for when a new version breaks something)."""
    f = appgit.local() / "update-previous"
    if not f.exists():
        raise UpdateError("no earlier version recorded on this computer")
    prev = f.read_text(encoding="utf-8").strip()
    with _LOCK:
        cur = appgit.git("rev-parse", "HEAD")
        if appgit.git("status", "--porcelain", "--untracked-files=no"):
            appgit.git("stash", "push", "-m", f"kb rollback {time.strftime('%Y-%m-%d %H:%M')}")
        appgit.git("reset", "-q", "--hard", prev)
        if _requirements_changed(cur, prev):
            (appgit.local() / "update-deps").write_text(prev, encoding="utf-8")
        f.unlink()
    return {"rolled_back": True, "to": prev[:7], "version": appgit.version_at("HEAD"), "restart": True}


def finish(python: str | None = None) -> dict:
    """After an update: install packages when requirements.txt changed (in a fresh process, before the app starts)."""
    marker = appgit.local() / "update-deps"
    if not marker.exists():
        return {"packages": False}
    r = subprocess.run([python or sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r",
                        str(appgit.root() / "requirements.txt")], timeout=1800)
    if r.returncode != 0:
        raise UpdateError(f"pip exit code {r.returncode}: packages not updated (internet or proxy?); run setup.cmd")
    marker.unlink()
    return {"packages": True}


def background(stop: threading.Event) -> None:
    """`kb serve`: check at start and every CHECK_EVERY_S; failures (offline) only show in About."""
    while not stop.is_set():
        try:
            check()
        except Exception:  # noqa: BLE001  a check must never stop the app
            pass
        stop.wait(CHECK_EVERY_S)
