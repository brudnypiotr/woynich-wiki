"""Commits are made by scripts, never by editor/agent hooks. One logical change = one commit, conventional message."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

TYPES = {"source", "ingest", "fix", "glossary", "decision", "lint", "catalog", "config", "docs"}
TRAILER = "Generated-by: woynich-wiki"


def message(kind: str, subject: str, scope: str | None = None, body: str = "") -> str:
    if kind not in TYPES:
        raise ValueError(f"commit type {kind!r} not in {sorted(TYPES)}")
    subject = re.sub(r"\s+", " ", subject).strip()
    head = f"{kind}({scope}): {subject}" if scope else f"{kind}: {subject}"
    return head[:200] + (f"\n\n{body.strip()}" if body.strip() else "") + f"\n\n{TRAILER}"


class GitError(subprocess.CalledProcessError):
    """A failed git command that says why: git's own message (or the pre-commit hook's), not only the exit status."""

    def __str__(self) -> str:
        why = " ".join(((self.stderr or "") + "\n" + (self.stdout or "")).split())[-800:]
        return f"git {self.cmd[3] if len(self.cmd) > 3 else ''} failed (exit {self.returncode}): {why or 'no message'}"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        raise GitError(r.returncode, r.args, r.stdout, r.stderr)
    return r


def commit(repo: Path, paths: list[Path], msg: str) -> str | None:
    """Stage exactly `paths` and commit. Returns the commit hash, or None if nothing changed."""
    rel = [str(Path(p).resolve().relative_to(repo.resolve())) for p in paths]
    _git(repo, "add", "--", *rel)
    if subprocess.run(["git", "-C", str(repo), "diff", "--cached", "--quiet", "--", *rel]).returncode == 0:
        return None
    _git(repo, "commit", "-q", "-m", msg, "--", *rel)
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
