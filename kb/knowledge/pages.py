"""Small helpers shared by the modules that read or write wiki pages (the pages themselves are written by the model)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from kb.knowledge import catalog


def wiki() -> Path:
    return catalog.instance() / "wiki"


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def frontmatter(**kv) -> str:
    lines = ["---"] + [f"{k}: {json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v}" for k, v in kv.items()] + ["---", ""]
    return "\n".join(lines)
