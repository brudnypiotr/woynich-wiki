"""Full-text search with SQLite FTS5 (ADR-0008): built into Python, offline, deterministic, no tokens.

Indexes every located segment of every source (raw/<id>/text.md) and every wiki page. Rebuilt on demand;
the index is a derived file in .cache/ (git-ignored).
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from kb.extractors.base import segments
from kb.knowledge import catalog

MAX_SEGMENT_CHARS = 1500


def db_path() -> Path:
    p = catalog.instance() / ".cache" / "search.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def ensure_fresh() -> None:
    """Rebuild the index only when a source text or a wiki page is newer than it (cheap: file times only)."""
    db, inst = db_path(), catalog.instance()
    files = list((inst / "raw").glob("*/text.md")) + list((inst / "wiki").rglob("*.md"))
    newest = max((f.stat().st_mtime for f in files), default=0.0)
    if not db.exists() or db.stat().st_mtime < newest or db.stat().st_size == 0:
        rebuild()


def rebuild() -> int:
    con = sqlite3.connect(db_path())
    con.execute("DROP TABLE IF EXISTS seg")
    con.execute("CREATE VIRTUAL TABLE seg USING fts5(kind, source_id, title, locator, text, tokenize='porter unicode61')")
    n = 0
    for rec in catalog.all_sources():
        tm = catalog.instance() / "raw" / rec["id"] / "text.md"
        if not tm.exists():
            continue
        for loc, txt in segments(tm.read_text(encoding="utf-8")):
            for i in range(0, len(txt), MAX_SEGMENT_CHARS):
                con.execute("INSERT INTO seg VALUES (?,?,?,?,?)", ("source", rec["id"], rec["title"], loc, txt[i:i + MAX_SEGMENT_CHARS]))
                n += 1
    wiki = catalog.instance() / "wiki"
    for page in sorted(wiki.rglob("*.md")) if wiki.exists() else []:
        rel = page.relative_to(wiki).as_posix()
        if rel in ("log.md",):
            continue
        con.execute("INSERT INTO seg VALUES (?,?,?,?,?)", ("page", rel, page.stem, "", page.read_text(encoding="utf-8")[:20000]))
        n += 1
    con.commit(); con.close()
    return n


def _fts_query(q: str) -> str:
    words = [w for w in re.findall(r"[\w\-]+", q.lower()) if len(w) > 1]
    stop = {"the", "a", "an", "of", "is", "are", "what", "why", "how", "does", "do", "in", "to", "for", "and", "or", "on", "it", "this", "that", "be", "with", "when", "which", "who"}
    words = [w for w in words if w not in stop] or words
    return " OR ".join(f'"{w}"' for w in words)


def search(q: str, limit: int = 8, kind: str | None = "source") -> list[dict]:
    if not db_path().exists():
        rebuild()
    con = sqlite3.connect(db_path())
    sql = "SELECT kind, source_id, title, locator, text, bm25(seg) AS score FROM seg WHERE seg MATCH ?"
    args: list = [_fts_query(q)]
    if kind:
        sql += " AND kind = ?"; args.append(kind)
    sql += " ORDER BY score LIMIT ?"; args.append(limit)
    try:
        rows = con.execute(sql, args).fetchall()
    except sqlite3.OperationalError:
        rows = []
    con.close()
    return [{"kind": r[0], "source_id": r[1], "title": r[2], "locator": r[3], "text": r[4], "score": r[5]} for r in rows]
