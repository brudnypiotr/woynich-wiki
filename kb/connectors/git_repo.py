"""Git repository connector: registers files of a repository at a fixed ref as sources (kind `code` or document).

Citations become `path:line@commit`, so an answer always names the exact code version it read.
For questions answered straight from code without ingesting it, see `kb code-ask` (kb/knowledge/code.py).
"""
from __future__ import annotations

import fnmatch
import subprocess
import tempfile
from pathlib import Path

from kb.core.ports import Connector, FetchedItem

DEFAULT_GLOBS = ["*.md", "docs/**"]


class GitRepo(Connector):
    name = "git_repo"

    def __init__(self, path: str | Path, ref: str = "HEAD", globs: list[str] | None = None, **options):
        super().__init__(**options)
        self.path, self.ref, self.globs = Path(path).expanduser(), ref, globs or DEFAULT_GLOBS

    def _git(self, *args) -> str:
        return subprocess.run(["git", "-C", str(self.path), *args], capture_output=True, text=True, check=True,
                              encoding="utf-8", errors="replace").stdout

    def commit(self) -> str:
        return self._git("rev-parse", self.ref).strip()

    def list(self):
        files = self._git("ls-tree", "-r", "--name-only", self.ref).splitlines()
        return [f for f in files if any(fnmatch.fnmatch(f, g) for g in self.globs)]

    def fetch(self, ref, dest_dir):
        dest_dir.mkdir(parents=True, exist_ok=True)
        data = subprocess.run(["git", "-C", str(self.path), "show", f"{self.ref}:{ref}"], capture_output=True, check=True).stdout
        dst = dest_dir / Path(ref).name
        dst.write_bytes(data)
        return FetchedItem(path=dst, title=ref, kind="code", ref=ref, mime=None)


def collect(path: str, ref: str = "HEAD", globs: list[str] | None = None, limit: int | None = None):
    from kb.connectors.folder_inbox import KIND_BY_EXT
    from kb.knowledge import catalog
    repo = GitRepo(path, ref, globs)
    commit = repo.commit()
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, f in enumerate(repo.list()):
            if limit and i >= limit:
                break
            item = repo.fetch(f, Path(tmp) / str(i))
            kind = KIND_BY_EXT.get(Path(f).suffix.lower(), "code")
            out.append(catalog.add_file(item.path, connector="git_repo", ref=f, title=f"{repo.path.name}/{f}", kind=kind,
                                        version=commit, found_via=[f"git:{repo.path.name}@{commit[:7]}"]))
    return out
