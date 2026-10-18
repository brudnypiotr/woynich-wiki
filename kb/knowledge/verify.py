"""Citation verifier: every fact line on a wiki page must cite an existing source at an existing locator, and its
verbatim quote must appear there. Runs after each ingest and on demand (`kb verify`)."""
from __future__ import annotations

import json
import re

from kb.extractors.base import segments
from kb.knowledge import catalog, llmjson, pages

FACT = re.compile(r"^- (?P<text>.+?) — \[(?P<title>[^\]]+)\]\((?:\.\.?/)?sources/(?P<sid>[0-9a-f]{12})\.md\) · (?P<loc>.+)$")
QUOTE = re.compile(r'^\s+> "(?P<q>.*)"$')


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
    out = catalog.instance() / "reports" / "verify.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report
