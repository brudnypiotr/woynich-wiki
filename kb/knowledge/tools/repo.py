"""Shared by the repository tools (git, code): the configured repositories and one safe git command.

Every call runs one fixed git command in a configured repository with checked arguments: no shell, no pager, no
external diff or text conversion, a time limit and a size limit on the output.
"""
from __future__ import annotations

import re
import subprocess

GIT_OUT = 40_000
HASH = re.compile(r"[0-9a-fA-F]{4,40}")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/\-~^]{0,120}")  # branch, tag, commit, HEAD~2, origin/main


def repos() -> list[dict]:
    from kb.knowledge import chat
    return [r for r in chat.repos() if r["exists"]]


def git(repo: str, *args: str) -> str:
    r = next((x for x in repos() if x["name"] == repo), None)
    if r is None:
        return f"unknown repository {repo!r}; use one of: " + ", ".join(x["name"] for x in repos())
    try:
        p = subprocess.run(["git", "-c", "core.pager=cat", "-c", "color.ui=false", "-C", str(r["path"]), *args],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    except subprocess.TimeoutExpired:
        return "git took longer than 30 s; narrow it down (path, since, limit)"
    out = (p.stdout if p.returncode == 0 else p.stderr).strip()
    return (out[:GIT_OUT] + "\n… (cut)" if len(out) > GIT_OUT else out) or "no output"


def relpath(path: str) -> str:
    p = path.strip().replace("\\", "/").lstrip("/")
    if not p or p.startswith("-") or ".." in p.split("/") or re.match(r"[A-Za-z]:", p):
        raise ValueError(f"not a path inside the repository: {path!r}")
    return p


def ref(ref: str) -> str:
    ref = ref.strip() or "HEAD"
    if not REF.fullmatch(ref) or ".." in ref:
        raise ValueError(f"not a branch, tag or commit: {ref!r}")
    return ref


def short(repo: str, ref: str) -> str:
    """The short commit a ref points to, for citations (repo/path:line@commit)."""
    out = git(repo, "rev-parse", "--short", f"{ref}^{{commit}}")
    return out if HASH.fullmatch(out) else ""
