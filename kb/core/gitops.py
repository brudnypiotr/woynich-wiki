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


def commit(repo: Path, paths: list[Path], msg: str) -> str | None:
    """Stage exactly `paths` and commit. Returns the commit hash, or None if nothing changed."""
    rel = [str(Path(p).resolve().relative_to(repo.resolve())) for p in paths]
    subprocess.run(["git", "-C", str(repo), "add", "--", *rel], check=True)
    if subprocess.run(["git", "-C", str(repo), "diff", "--cached", "--quiet", "--", *rel]).returncode == 0:
        return None
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", msg, "--", *rel], check=True)
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
