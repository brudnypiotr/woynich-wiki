"""Pre-commit guard: blocks secrets and invalid records. Installed by `git config core.hooksPath .githooks`."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

PATTERNS = {
    "GitHub token": re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})\b"),
    "Atlassian API token": re.compile(r"\bATATT[A-Za-z0-9_\-=]{30,}\b"),
    "Azure / Graph client secret": re.compile(r"\b[A-Za-z0-9~._\-]{3}8Q~[A-Za-z0-9~._\-]{31,}\b"),
    "Private key": re.compile(r"-----BEGIN (RSA |EC |OPENSSH |)PRIVATE KEY-----"),
    "Password assignment": re.compile(r"(?i)\b(password|passwd|secret|api[_-]?key|token)\s*[:=]\s*['\"][^'\"\s]{8,}['\"]"),
}
RECORD_SCHEMAS = {"catalog/records/": "source_record", "queue/": "queue_item"}


def schema_for(path: str) -> str | None:
    path = path.replace("\\", "/")
    if re.search(r"(^|/)raw/[0-9a-f]{12}/source\.json$", path):
        return "source_record"
    return next((name for prefix, name in RECORD_SCHEMAS.items() if prefix in path and path.endswith(".json")), None)


def staged() -> list[str]:
    out = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"], capture_output=True, text=True, check=True)
    return [l for l in out.stdout.splitlines() if l]


def scan_text(text: str) -> list[str]:
    return [name for name, rx in PATTERNS.items() if rx.search(text)]


def main(files: list[str] | None = None) -> int:
    from kb.core import schemas
    problems = []
    for f in files if files is not None else staged():
        p = Path(f)
        if not p.is_file() or p.stat().st_size > 5_000_000:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for hit in scan_text(text):
            problems.append(f"{f}: looks like a {hit}; secrets belong in Windows Credential Manager (kb secrets set ...)")
        name = schema_for(f)
        if name:
            for e in schemas.errors(name, json.loads(text)):
                problems.append(f"{f}: {e}")
    for pr in problems:
        print("pre-commit:", pr, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
