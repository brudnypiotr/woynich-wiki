"""Updates of this copy of the app from its Git remote, and the changelog read from Git history.

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
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from kb.core import config

RESTART_CODE = 3          # `kb serve` exit code that asks the launcher to start it again
CHECK_EVERY_S = 3600      # background check while `kb serve` runs
DEFAULT = {"remote": "https://github.com/brudnypiotr/woynich-wiki.git", "branch": "main"}

_LOCK = threading.Lock()
_LAST: dict | None = None
RESTART = threading.Event()  # set after apply/rollback: `kb serve` stops and exits with RESTART_CODE


class UpdateError(RuntimeError):
    pass


def _root() -> Path:
    return config.paths().root


def _local() -> Path:
    d = _root() / "local"
    d.mkdir(exist_ok=True)
    return d


def settings() -> dict:
    """Where updates come from: setup/sources.json → "update" (the one place to change for a company mirror)."""
    try:
        s = json.loads((_root() / "setup" / "sources.json").read_text(encoding="utf-8")).get("update") or {}
    except (OSError, ValueError):
        s = {}
    return {**DEFAULT, **{k: v for k, v in s.items() if k in DEFAULT and v}}


def git_exe() -> str | None:
    """git on PATH, or the Portable Git setup unpacked (its PATH entry reaches only windows opened after setup)."""
    found = shutil.which("git")
    if found:
        return found
    p = Path(os.environ.get("LOCALAPPDATA", "")) / "woynich-wiki" / "git" / "cmd" / "git.exe"
    return str(p) if os.environ.get("LOCALAPPDATA") and p.exists() else None


def _git(*args: str, check: bool = True, timeout: int = 120) -> str:
    exe = git_exe()
    if not exe:
        raise UpdateError("Git is not installed: run setup.cmd again")
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}  # never wait for a password in a hidden window
    r = subprocess.run([exe, "-C", str(_root()), *args], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, env=env)
    if check and r.returncode != 0:
        raise UpdateError(f"git {args[0]}: {(r.stderr or r.stdout).strip()[:400]}")
    return r.stdout.strip()


def launched() -> bool:
    """Started by `Wiki.cmd`, which restarts the app after an update."""
    return bool(os.environ.get("KB_LAUNCHER"))


def is_clone() -> bool:
    return (_root() / ".git").exists()


def attach() -> dict:
    """Make a ZIP copy a clone of the official remote, or add the remote when a clone has none. Never changes an
    existing origin (a developer's SSH remote stays). Ignored files (instance/, .venv, kb.cmd) are untouched."""
    s = settings()
    if not is_clone():
        _git("init", "-q", "-b", s["branch"])
        _git("remote", "add", "origin", s["remote"])
        _git("fetch", "-q", "origin", s["branch"], timeout=600)
        _git("reset", "-q", "--hard", f"origin/{s['branch']}")
        _git("branch", "-q", "-u", f"origin/{s['branch']}")
        return {"attached": True, "remote": s["remote"], "commit": _git("rev-parse", "--short", "HEAD")}
    if "origin" not in _git("remote").split():
        _git("remote", "add", "origin", s["remote"])
        return {"attached": True, "remote": s["remote"]}
    return {"attached": False, "remote": _git("remote", "get-url", "origin")}


def _commits(rng: str, limit: int = 0) -> list[dict]:
    fmt = "%h\x1f%cs\x1f%s"
    out = _git("log", f"--format={fmt}", *([f"-{limit}"] if limit else []), rng)
    return [parse(*line.split("\x1f", 2)) for line in out.splitlines() if line.count("\x1f") == 2]


_CC = re.compile(r"^(?P<type>[A-Za-z]+)(?:\((?P<scope>[^)]*)\))?!?:\s*(?P<text>.+)$")
KINDS = {"feat": "Features", "fix": "Fixes"}


def parse(commit: str, date: str, subject: str) -> dict:
    """A Conventional Commit subject (`type(scope): text`) as a changelog entry."""
    m = _CC.match(subject)
    typ, scope, text = (m["type"].lower(), m["scope"] or "", m["text"]) if m else ("other", "", subject)
    return {"commit": commit, "date": date, "type": typ, "scope": scope, "text": text,
            "kind": KINDS.get(typ, "Other")}


def check(fetch: bool = True) -> dict:
    """Is there a newer version on the remote? Fetches (unless fetch=False) and lists the incoming commits."""
    global _LAST
    s = settings()
    with _LOCK:
        if not is_clone():
            _LAST = {"available": False, "clone": False, "error": "this copy has no Git history: run setup.cmd again",
                     "checked_at": time.time()}
            return _LAST
        out = {"available": False, "clone": True, "behind": 0, "ahead": 0, "incoming": [], "error": None,
               "branch": s["branch"], "launcher": launched(), "checked_at": time.time()}
        try:
            if fetch:
                _git("fetch", "-q", "origin", s["branch"], timeout=90)
            up = f"origin/{s['branch']}"
            ahead, behind = (int(x) for x in _git("rev-list", "--left-right", "--count", f"HEAD...{up}").split())
            out.update(ahead=ahead, behind=behind, available=behind > 0, current=_git("rev-parse", "--short", "HEAD"),
                       latest=_git("rev-parse", "--short", up), incoming=_commits(f"HEAD..{up}", 200),
                       dirty=bool(_git("status", "--porcelain", "--untracked-files=no")),
                       latest_version=_version_at(up), current_version=_version_at("HEAD"))
        except (UpdateError, subprocess.TimeoutExpired, ValueError) as e:
            out["error"] = str(e)[:400]
        _LAST = out
        return out


def last() -> dict | None:
    return _LAST


def _version_at(rev: str) -> str | None:
    m = re.search(r'(?m)^version\s*=\s*"([^"]+)"', _git("show", f"{rev}:pyproject.toml", check=False))
    return m[1] if m else None


def _requirements_changed(old: str, new: str) -> bool:
    return bool(_git("diff", "--name-only", old, new, "--", "requirements.txt", check=False))


def apply() -> dict:
    """Move this copy to the newest version. Local edits are stashed, local commits saved on a backup branch.
    Returns what happened; the caller restarts the app (and `kb update --finish` installs packages if needed)."""
    s = settings()
    with _LOCK:
        if not is_clone():
            raise UpdateError("this copy has no Git history: run setup.cmd again")
        up = f"origin/{s['branch']}"
        _git("fetch", "-q", "origin", s["branch"], timeout=300)
        old = _git("rev-parse", "HEAD")
        new = _git("rev-parse", up)
        if old == new:
            return {"updated": False, "message": "Already up to date."}
        notes = []
        if _git("status", "--porcelain", "--untracked-files=no"):
            _git("stash", "push", "-m", f"kb update {time.strftime('%Y-%m-%d %H:%M')}")
            notes.append("local edits were put aside (git stash)")
        (_local() / "update-previous").write_text(old, encoding="utf-8")
        _git("merge", "-q", "--ff-only", up, check=False)
        if _git("rev-parse", "HEAD") != new:  # local commits: keep them on a branch and take the official version
            backup = f"backup/{time.strftime('%Y%m%d-%H%M%S')}"
            _git("branch", backup, old)
            _git("reset", "-q", "--hard", up)
            notes.append(f"local commits kept on branch {backup}")
        deps = _requirements_changed(old, new)
        if deps:
            (_local() / "update-deps").write_text(new, encoding="utf-8")
        return {"updated": True, "from": old[:7], "to": new[:7], "version": _version_at("HEAD"),
                "packages": deps, "notes": notes, "restart": True}


def rollback() -> dict:
    """Back to the commit before the last update (for when a new version breaks something)."""
    f = _local() / "update-previous"
    if not f.exists():
        raise UpdateError("no earlier version recorded on this computer")
    prev = f.read_text(encoding="utf-8").strip()
    with _LOCK:
        cur = _git("rev-parse", "HEAD")
        if _git("status", "--porcelain", "--untracked-files=no"):
            _git("stash", "push", "-m", f"kb rollback {time.strftime('%Y-%m-%d %H:%M')}")
        _git("reset", "-q", "--hard", prev)
        if _requirements_changed(cur, prev):
            (_local() / "update-deps").write_text(prev, encoding="utf-8")
        f.unlink()
    return {"rolled_back": True, "to": prev[:7], "version": _version_at("HEAD"), "restart": True}


def finish(python: str | None = None) -> dict:
    """After an update: install packages when requirements.txt changed (in a fresh process, before the app starts)."""
    marker = _local() / "update-deps"
    if not marker.exists():
        return {"packages": False}
    r = subprocess.run([python or sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r",
                        str(_root() / "requirements.txt")], timeout=1800)
    if r.returncode != 0:
        raise UpdateError(f"pip exit code {r.returncode}: packages not updated (internet or proxy?); run setup.cmd")
    marker.unlink()
    return {"packages": True}


def changelog(limit: int = 500) -> list[dict]:
    """Every commit of this copy, newest first, grouped by the app version (pyproject.toml) at that commit."""
    if not is_clone():
        return []
    commits = [ln.split("\x1f", 3) for ln in _git("log", "--topo-order", f"-{limit}", "--format=%H\x1f%h\x1f%cs\x1f%s").splitlines()]
    pos = {c[0]: i for i, c in enumerate(commits)}
    bumps = [h for h in _git("log", "--topo-order", "--format=%H", "-G", r"^version = ", "--", "pyproject.toml").splitlines() if h in pos]
    bounds = [(pos[h], _version_at(h) or "?") for h in bumps]  # newest first; a bump starts its version
    groups: list[dict] = []
    b = 0
    for i, (_, short, date, subject) in enumerate(commits):
        while b < len(bounds) and i > bounds[b][0]:
            b += 1  # older than this bump: an earlier version
        ver = bounds[b][1] if b < len(bounds) else (f"before {bounds[-1][1]}" if bounds else "unversioned")
        if not groups or groups[-1]["version"] != ver:
            groups.append({"version": ver, "date": date, "entries": []})
        groups[-1]["entries"].append(parse(short, date, subject))
    return groups


def changelog_markdown(groups: list[dict], all_types: bool = False) -> str:
    out = ["# Changelog", "", "Generated from Git history (`kb changelog --md`).", ""]
    for g in groups:
        entries = [e for e in g["entries"] if all_types or e["kind"] != "Other"]
        if not entries:
            continue
        out += [f"## {g['version']}", ""]
        for kind in ("Features", "Fixes", "Other"):
            ks = [e for e in entries if e["kind"] == kind]
            if ks:
                out += [f"### {kind}", ""] + [f"- {e['date']} {e['text']}" + (f" ({e['scope']})" if e["scope"] else "")
                                              + f" `{e['commit']}`" for e in ks] + [""]
    return "\n".join(out)


def background(stop: threading.Event) -> None:
    """`kb serve`: check at start and every CHECK_EVERY_S; failures (offline) only show in About."""
    while not stop.is_set():
        try:
            check()
        except Exception:  # noqa: BLE001  a check must never stop the app
            pass
        stop.wait(CHECK_EVERY_S)
