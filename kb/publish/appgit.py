"""Git for the app's own copy (not the instance): find git, run it in the repository root, read the version at a commit.
Shared by the updater, the changelog and diagnostics."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from kb.core import config


class GitError(RuntimeError):
    pass


def root() -> Path:
    return config.paths().root


def local() -> Path:
    """The copy's own state that is not in Git (update markers, restart token, update channel)."""
    d = root() / "local"
    d.mkdir(exist_ok=True)
    return d


def git_exe() -> str | None:
    """git on PATH, or the Portable Git setup unpacked (its PATH entry reaches only windows opened after setup)."""
    found = shutil.which("git")
    if found:
        return found
    p = Path(os.environ.get("LOCALAPPDATA", "")) / "woynich-wiki" / "git" / "cmd" / "git.exe"
    return str(p) if os.environ.get("LOCALAPPDATA") and p.exists() else None


def git(*args: str, check: bool = True, timeout: int = 120) -> str:
    exe = git_exe()
    if not exe:
        raise GitError("Git is not installed: run setup.cmd again")
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}  # never wait for a password in a hidden window
    try:
        r = subprocess.run([exe, "-C", str(root()), *args], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, env=env)
    except subprocess.TimeoutExpired as e:
        raise GitError(f"git {args[0]}: no answer in {timeout} s (internet or proxy?)") from e
    if check and r.returncode != 0:
        raise GitError(f"git {args[0]}: {(r.stderr or r.stdout).strip()[:400]}")
    return r.stdout.strip()


def is_clone() -> bool:
    return (root() / ".git").exists()


def version_at(rev: str) -> str | None:
    """The app version (pyproject.toml) at a commit."""
    m = re.search(r'(?m)^version\s*=\s*"([^"]+)"', git("show", f"{rev}:pyproject.toml", check=False))
    return m[1] if m else None
