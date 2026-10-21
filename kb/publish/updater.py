"""Updates of this copy of the app from its Git remote (the changelog is in kb/publish/changelog.py).

Channels: a copy follows one branch of the remote, `main` by default (setup/sources.json → update.branch). Admin mode
(local/update.json, per copy) lets it follow any branch to try a feature before it is merged; when that branch is
merged and deleted, the next Update returns to main. A copy checked out on another branch than its channel (a
developer's clone) is never moved.

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


def _prefs_file():
    return appgit.local() / "update.json"


def prefs() -> dict:
    """This copy's own update settings (local/update.json, not in Git): the channel and whether admin mode is on.
    Admin mode lists every branch of the repository as a channel, to try a feature before it is merged."""
    try:
        p = json.loads(_prefs_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        p = {}
    return {"channel": p.get("channel") or settings()["branch"], "admin": bool(p.get("admin"))}


def set_prefs(**kw) -> dict:
    p = {**prefs(), **{k: v for k, v in kw.items() if v is not None}}
    _prefs_file().write_text(json.dumps(p, indent=2), encoding="utf-8")
    return p


def _branch() -> str:
    return appgit.git("rev-parse", "--abbrev-ref", "HEAD")


def _fetch(channel: str, timeout: int = 90) -> bool:
    """Fetch the channel's branch; False when it is gone from the remote (merged and deleted)."""
    try:
        appgit.git("fetch", "-q", "--prune", "origin", f"+refs/heads/{channel}:refs/remotes/origin/{channel}", timeout=timeout)
        return True
    except UpdateError as e:
        if "couldn't find remote ref" in str(e).lower():
            appgit.git("update-ref", "-d", f"refs/remotes/origin/{channel}", check=False)
            return False
        raise


def check(fetch: bool = True) -> dict:
    """Is there a newer version on this copy's channel? Fetches (unless fetch=False) and lists the incoming commits.
    A copy whose checked-out branch is not its channel (a developer's clone on a feature branch) is never touched."""
    global _LAST
    s, p = settings(), prefs()
    with _LOCK:
        out = {"available": False, "clone": appgit.is_clone(), "behind": 0, "ahead": 0, "incoming": [], "error": None,
               "channel": p["channel"], "default_channel": s["branch"], "admin": p["admin"], "on_branch": None,
               "off_channel": False, "gone": False, "launcher": launched(), "checked_at": time.time()}
        if not out["clone"]:
            out["error"] = "this copy has no Git history: run setup.cmd again"
        else:
            try:
                out["on_branch"] = _branch()
                out["current"], out["current_version"] = appgit.git("rev-parse", "--short", "HEAD"), appgit.version_at("HEAD")
                if out["on_branch"] != p["channel"]:
                    out["off_channel"] = True  # updates are off: nothing to do with this checkout
                elif fetch and not _fetch(p["channel"]):
                    out.update(gone=True, available=p["channel"] != s["branch"])  # merged: Update returns to the default
                else:
                    up = f"origin/{p['channel']}"
                    ahead, behind = (int(x) for x in appgit.git("rev-list", "--left-right", "--count", f"HEAD...{up}").split())
                    out.update(ahead=ahead, behind=behind, available=behind > 0,
                               latest=appgit.git("rev-parse", "--short", up), incoming=changelog.commits(f"HEAD..{up}", 200),
                               dirty=bool(appgit.git("status", "--porcelain", "--untracked-files=no")),
                               latest_version=appgit.version_at(up))
            except (UpdateError, ValueError) as e:
                out["error"] = str(e)[:400]
        _LAST = out
        return out


def last() -> dict | None:
    return _LAST


def branches() -> list[dict]:
    """Admin mode: every branch on the remote, newest first, as channels to choose from."""
    appgit.git("fetch", "-q", "--prune", "origin", "+refs/heads/*:refs/remotes/origin/*", timeout=120)
    out = appgit.git("for-each-ref", "--sort=-committerdate", "refs/remotes/origin",
                     "--format=%(refname:lstrip=3)\x1f%(committerdate:short)\x1f%(subject)")
    return [dict(zip(("name", "date", "subject"), ln.split("\x1f", 2))) for ln in out.splitlines()
            if ln.count("\x1f") == 2 and not ln.startswith("HEAD\x1f")]


def _requirements_changed(old: str, new: str) -> bool:
    return bool(appgit.git("diff", "--name-only", old, new, "--", "requirements.txt", check=False))


def _move(channel: str, kind: str) -> dict:
    """Put this copy on origin/<channel>: record where it was (rollback), put local edits aside, keep local commits on a
    backup branch, check the branch out at the remote's commit. The caller holds _LOCK and restarts the app."""
    up = f"origin/{channel}"
    old, old_branch = appgit.git("rev-parse", "HEAD"), _branch()
    new = appgit.git("rev-parse", up)
    notes = []
    if appgit.git("status", "--porcelain", "--untracked-files=no"):
        appgit.git("stash", "push", "-m", f"kb {kind} {time.strftime('%Y-%m-%d %H:%M')}")
        notes.append("local edits were put aside (git stash)")
    (appgit.local() / "update-previous").write_text(json.dumps({"branch": old_branch, "commit": old}), encoding="utf-8")
    local = appgit.git("rev-parse", "-q", "--verify", f"refs/heads/{channel}", check=False)
    if local and appgit.git("rev-list", "--count", f"{new}..{local}") != "0":  # commits only here: keep them
        backup = f"backup/{time.strftime('%Y%m%d-%H%M%S')}"
        appgit.git("branch", backup, local)
        notes.append(f"local commits kept on branch {backup}")
    appgit.git("checkout", "-q", "-B", channel, up)
    appgit.git("branch", "-q", "-u", up)
    set_prefs(channel=channel)
    deps = _requirements_changed(old, new)
    if deps:
        (appgit.local() / "update-deps").write_text(new, encoding="utf-8")
    return {"updated": True, "from": old[:7], "to": new[:7], "channel": channel, "version": appgit.version_at("HEAD"),
            "packages": deps, "notes": notes, "restart": True}


def apply() -> dict:
    """Move this copy to the newest version of its channel (back to the default channel when that branch is gone).
    Returns what happened; the caller restarts the app (and `kb update --finish` installs packages if needed)."""
    s, p = settings(), prefs()
    with _LOCK:
        if not appgit.is_clone():
            raise UpdateError("this copy has no Git history: run setup.cmd again")
        if _branch() != p["channel"]:
            raise UpdateError(f"this copy is on branch {_branch()}, not on its update channel {p['channel']}: "
                              "updates are off (switch the channel in admin mode, or git switch yourself)")
        channel = p["channel"]
        if not _fetch(channel, timeout=300):
            if channel == s["branch"]:
                raise UpdateError(f"branch {channel} is not on the remote")
            channel = s["branch"]  # the feature was merged (or dropped): back to the default channel
            _fetch(channel, timeout=300)
        if channel == p["channel"] and appgit.git("rev-parse", "HEAD") == appgit.git("rev-parse", f"origin/{channel}"):
            return {"updated": False, "message": "Already up to date."}
        return _move(channel, "update")


def switch(channel: str) -> dict:
    """Admin mode (or back to the default channel): follow another branch from now on, and move to it now."""
    s, p = settings(), prefs()
    if channel != s["branch"] and not p["admin"]:
        raise UpdateError("other channels need admin mode (kb update --admin on)")
    with _LOCK:
        if not appgit.is_clone():
            raise UpdateError("this copy has no Git history: run setup.cmd again")
        if not _fetch(channel, timeout=300):
            raise UpdateError(f"branch {channel} is not on the remote")
        if _branch() == channel and appgit.git("rev-parse", "HEAD") == appgit.git("rev-parse", f"origin/{channel}"):
            set_prefs(channel=channel)
            return {"updated": False, "message": f"Already on {channel}."}
        return _move(channel, "switch")


def rollback() -> dict:
    """Back to the branch and commit before the last update or channel switch (for when a version breaks something)."""
    f = appgit.local() / "update-previous"
    if not f.exists():
        raise UpdateError("no earlier version recorded on this computer")
    raw = f.read_text(encoding="utf-8").strip()
    prev = json.loads(raw) if raw.startswith("{") else {"branch": None, "commit": raw}  # older copies: commit only
    with _LOCK:
        cur = appgit.git("rev-parse", "HEAD")
        if appgit.git("status", "--porcelain", "--untracked-files=no"):
            appgit.git("stash", "push", "-m", f"kb rollback {time.strftime('%Y-%m-%d %H:%M')}")
        if prev["branch"] and prev["branch"] != "HEAD":
            appgit.git("checkout", "-q", "-B", prev["branch"], prev["commit"])
            set_prefs(channel=prev["branch"])
        else:
            appgit.git("reset", "-q", "--hard", prev["commit"])
        if _requirements_changed(cur, prev["commit"]):
            (appgit.local() / "update-deps").write_text(prev["commit"], encoding="utf-8")
        f.unlink()
    return {"rolled_back": True, "to": prev["commit"][:7], "channel": prefs()["channel"], "version": appgit.version_at("HEAD"),
            "restart": True}


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
