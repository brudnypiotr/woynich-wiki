"""Inbox connector: everything dropped into a local folder becomes a candidate source."""
from __future__ import annotations

import mimetypes
import shutil
from pathlib import Path

from kb.core.ports import Connector, FetchedItem

KIND_BY_EXT = {
    ".pdf": "document", ".docx": "document", ".doc": "document", ".md": "document", ".txt": "document", ".html": "web",
    ".htm": "web", ".xlsx": "spreadsheet", ".xlsm": "spreadsheet", ".csv": "spreadsheet", ".eml": "email", ".msg": "email",
    ".vtt": "transcript", ".srt": "transcript", ".png": "image", ".jpg": "image", ".jpeg": "image",
    ".py": "code", ".cs": "code", ".java": "code", ".js": "code", ".ts": "code", ".sql": "code", ".ps1": "code", ".xml": "code", ".xsd": "code",
}


class FolderInbox(Connector):
    name = "folder_inbox"

    def __init__(self, path: str | Path = "instance/inbox", **options):
        super().__init__(**options)
        self.root = Path(path)

    def list(self):
        if not self.root.exists():
            return []
        return sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*") if p.is_file() and not p.name.startswith("."))

    def fetch(self, ref, dest_dir):
        src = self.root / ref
        dest_dir.mkdir(parents=True, exist_ok=True)
        dst = dest_dir / ("original" + src.suffix.lower())
        shutil.copy2(src, dst)
        return FetchedItem(path=dst, title=src.stem, kind=KIND_BY_EXT.get(src.suffix.lower(), "other"), ref=ref,
                           mime=mimetypes.guess_type(src.name)[0])
