"""Search in the knowledge base: the full-text index (kb.knowledge.search, SQLite FTS5) instead of grepping file by
file. Deterministic, no model, no AI credits."""
from __future__ import annotations

from pydantic import BaseModel, Field


def available() -> bool:
    return True


def context() -> str:
    return "SEARCH: `kb_search` finds where something is mentioned in the wiki and the sources (words, not meaning); use it before reading files."


class KbSearch(BaseModel):
    query: str = Field(description="Words to look for (names, terms, ticket keys); several words find passages with any of them, best first")
    scope: str = Field(default="all", description="'sources' (original documents, with page/time), 'pages' (wiki pages) or 'all'")
    limit: int = Field(default=10, description="Maximum number of hits (1-20)")


def tools() -> list:
    from copilot import define_tool
    from kb.knowledge.tools import off_loop
    from kb.knowledge import search, wiki

    @define_tool(description="Full-text search in the knowledge base: wiki pages and the original sources, best matches "
                             "first, each with where it is (wiki page path, or source page and page/time locator) and a "
                             "fragment. Use it to find where something is mentioned before reading files; it matches words, "
                             "not meaning, so try other words (or English and Polish) if nothing comes back. Read-only.")
    @off_loop
    def kb_search(params: KbSearch) -> str:
        search.ensure_fresh()
        kind = {"sources": "source", "pages": "page"}.get(params.scope.strip().lower())
        hits = search.search(params.query, limit=max(1, min(20, params.limit)), kind=kind)
        if not hits:
            return "no matches; try other words"
        slugs = {sid: slug for slug, sid in wiki.source_pages().items()}
        out = []
        for h in hits:
            frag = " ".join(h["text"].split())[:300]
            if h["kind"] == "page":
                out.append(f"wiki/{h['source_id']}\n    {frag}")
            else:
                page = f"[[{slugs[h['source_id']]}]]" if h["source_id"] in slugs else "(no wiki page yet)"
                out.append(f"source {h['title']} {page} {h['locator'] or ''} → raw/{h['source_id']}/text.md\n    {frag}")
        return "\n".join(out)

    return [kb_search]
