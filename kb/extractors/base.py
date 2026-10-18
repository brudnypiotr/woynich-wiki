"""Extractors turn one original file into text.md with locator markers.

Markers (one per line, before the content they locate):
  <!-- p. N -->            page of a PDF
  <!-- ¶ N -->            paragraph of a document / web page / email
  <!-- t. HH:MM:SS -->     time stamp of a transcript
  <!-- #c N -->           Jira comment N (#description for the description)
  <!-- L N -->            line N of a code file
Citations use the same text: `p. 12`, `¶ 3`, `t. 00:42:10`, `PROJ-1#c5`, `src/x.py:120@abc1234`.
"""
from __future__ import annotations

import re
from pathlib import Path

from kb.core.ports import Extractor

MARKER = re.compile(r"^<!-- (p\.|¶|t\.|#c|#description|L) ?([\d:]*) -->$")


def marker(kind: str, value) -> str:
    return f"<!-- {kind} {value} -->" if value != "" else f"<!-- {kind} -->"


def paragraphs_to_md(paras: list[str]) -> str:
    out, n = [], 0
    for p in paras:
        p = re.sub(r"[ \t]+", " ", p).strip()
        if not p:
            continue
        n += 1
        out += [marker("¶", n), p, ""]
    return "\n".join(out)


def segments(text: str) -> list[tuple[str, str]]:
    """Split text.md into (locator, text) segments using the markers."""
    segs: list[tuple[str, list[str]]] = []
    cur = None
    for line in text.splitlines():
        m = MARKER.match(line.strip())
        if m:
            kind, val = m.group(1), m.group(2)
            loc = {"p.": f"p. {val}", "¶": f"¶ {val}", "t.": f"t. {val}", "#c": f"#c{val}",
                   "#description": "#description", "L": f"L{val}"}[kind]
            cur = [loc, []]; segs.append(cur); continue
        if cur is None:
            cur = ["top", []]; segs.append(cur)  # text before the first marker (title, header)
        cur[1].append(line)
    return [(loc, "\n".join(lines).strip()) for loc, lines in segs if "\n".join(lines).strip()]


class PlainText(Extractor):
    extensions = (".txt", ".md", ".csv")

    def extract(self, path: Path) -> dict:
        text = path.read_text(encoding="utf-8", errors="replace")
        return {"text": paragraphs_to_md(re.split(r"\n\s*\n", text)), "meta": {}}
