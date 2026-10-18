"""Citation verifier: every fact line on a wiki page must cite an existing source at an existing locator, and its
verbatim quote must appear there. Runs after each ingest and on demand (`kb verify`)."""
from __future__ import annotations

import json
import re

from kb.extractors.base import segments
from kb.knowledge import catalog, llmjson, pages

FACT = re.compile(r"^- (?P<text>.+?) — \[(?P<title>[^\]]+)\]\((?:\.\.?/)?sources/(?P<sid>[0-9a-f]{12})\.md\) · (?P<loc>.+)$")
QUOTE = re.compile(r'^\s+> "(?P<q>.*)"$')


LINK = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
CITE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]\s*(p\.\s*\d+|t\.\s*\d{1,2}:\d{2}(?::\d{2})?|#c\s*\d+|#description|L\s*\d+|¶\s*\d+)")
NO_CITE_TYPES = {"index", "log", "hot", "glossary", "meta", "answer", "discussion", "lint"}


def _seconds(t: str) -> int:
    parts = [int(x) for x in t.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def _locator_ok(loc: str, segs: dict) -> bool:
    loc = re.sub(r"\s+", " ", loc.strip())
    keys = set(segs)
    if loc.startswith("p.") or loc.startswith("¶"):
        return re.sub(r"^(p\.|¶)\s*", r"\1 ", loc) in keys
    if loc.startswith("t."):
        want = _seconds(loc[2:].strip())
        times = [_seconds(k[2:].strip()) for k in keys if k.startswith("t.")]
        return any(abs(want - t) <= 120 for t in times) or (bool(times) and min(times) <= want <= max(times) + 120)
    if loc.startswith("#c"):
        return f"#c{loc[2:].strip()}" in keys
    if loc == "#description":
        return "#description" in keys
    if loc.startswith("L"):
        n = int(loc[1:].strip())
        lines = [int(k[1:]) for k in keys if k.startswith("L") and k[1:].isdigit()]
        return bool(lines) and n <= max(lines) + 10
    return False


def check_wiki(report: dict) -> None:
    """Checks for model-written pages (ingest v2): links resolve; citations point to an existing source page and
    an existing place in that source; statements without any citation are counted. Problems are warnings."""
    from kb.knowledge import wiki as wikimod
    w = pages.wiki()
    names = {p.stem for p in w.rglob("*.md")}
    srcs = wikimod.source_pages()
    seg_cache: dict[str, dict | None] = {}
    report.update({"citations": 0, "citations_ok": 0, "uncited_lines": 0, "contradictions": 0, "broken_links": 0})
    for page in sorted(w.rglob("*.md")):
        rel = str(page.relative_to(w)).replace("\\", "/")
        text = page.read_text(encoding="utf-8")
        ptype = (re.search(r"^type:\s*(\w+)", text[:400], re.M) or [None, ""])[1]
        report["contradictions"] += len(re.findall(r"^>\s*\[!contradiction\]", text, re.M))
        for i, line in enumerate(text.splitlines(), 1):
            for m in LINK.finditer(line):
                target = m.group(1).strip().split("/")[-1]
                if target not in names:
                    report["broken_links"] += 1
                    report["problems"].append({"page": rel, "line": i, "issue": f"broken link [[{target}]]"})
            for m in CITE.finditer(line):
                slug = m.group(1).strip().split("/")[-1]
                if slug not in srcs:
                    continue
                report["citations"] += 1
                sid = srcs[slug]
                if sid not in seg_cache:
                    tm = catalog.instance() / "raw" / sid / "text.md"
                    seg_cache[sid] = {l: t for l, t in segments(tm.read_text(encoding="utf-8"))} if tm.exists() else None
                if seg_cache[sid] is None:
                    report["problems"].append({"page": rel, "line": i, "issue": f"cited source {slug} has no text"}); continue
                if _locator_ok(m.group(2), seg_cache[sid]):
                    report["citations_ok"] += 1
                else:
                    report["problems"].append({"page": rel, "line": i, "issue": f"{m.group(2)} not found in {slug}"})
            body = line.strip()
            if (ptype not in NO_CITE_TYPES and rel not in ("index.md", "log.md", "hot.md", "glossary.md") and len(body) > 60
                    and not body.startswith(("#", ">", "|", "---", "[[", "```")) and "[[" not in body and ":" not in body[:20]):
                report["uncited_lines"] += 1


def verify_all() -> dict:
    report = {"pages": 0, "facts": 0, "ok": 0, "problems": []}
    cache: dict[str, dict] = {}
    for page in sorted(pages.wiki().rglob("*.md")):
        rel = str(page.relative_to(pages.wiki()))
        report["pages"] += 1
        lines = page.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            m = FACT.match(line)
            if not m:
                continue
            report["facts"] += 1
            sid, loc = m.group("sid"), m.group("loc").strip()
            if sid not in cache:
                tm = catalog.instance() / "raw" / sid / "text.md"
                cache[sid] = {l: t for l, t in segments(tm.read_text(encoding="utf-8"))} if tm.exists() else None
            segs = cache[sid]
            if segs is None:
                report["problems"].append({"page": rel, "line": i + 1, "issue": "source missing", "source": sid}); continue
            q = QUOTE.match(lines[i + 1]) if i + 1 < len(lines) else None
            locs = [k for k in segs if k and (loc.endswith(k) or k.endswith(loc.split(":")[-1].split("@")[0]) or loc.endswith(k.lstrip("L")))]
            if q:
                where = [k for k, t in segs.items() if llmjson.quote_in(q.group("q"), t)]
                if not where:
                    report["problems"].append({"page": rel, "line": i + 1, "issue": "quote not found in source", "source": sid, "locator": loc})
                    continue
                if locs and not set(locs) & set(where):
                    report["problems"].append({"page": rel, "line": i + 1, "issue": f"quote is at {where[0]}, not {loc}", "source": sid}); continue
            elif not locs:
                report["problems"].append({"page": rel, "line": i + 1, "issue": "locator not found", "source": sid, "locator": loc}); continue
            report["ok"] += 1
    check_wiki(report)
    out = catalog.instance() / "reports" / "verify.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report
