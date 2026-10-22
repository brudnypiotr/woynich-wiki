"""Quality of a source after its ingest: read-only, it decides nothing (yet).

Two halves, kept apart so they can be compared:
  - the model's judgement: it has just read the whole source and the wiki, so it scores relevance, novelty,
    specificity, reliability and text quality (1–5, each with a reason) and gives a verdict; it costs nothing extra,
    it is the end of the ingest reply (prompts/ingest.md, step 9);
  - measured signals: what the ingest actually produced (pages, citations per 10k characters) and what extraction
    noticed (pages without text, empty slides).

Saved as raw/<id>/assessment.json and committed with the ingest. `kb assess` lists them (also as CSV), so a curator
can see how the scores behave before anything is filtered or skipped automatically.
"""
from __future__ import annotations

import json
import re

from kb.knowledge import catalog, pages

CRITERIA = ("relevance", "novelty", "specificity", "reliability", "text_quality")
VERDICTS = ("core", "useful", "marginal", "noise")
ABBR = {"relevance": "rel", "novelty": "nov", "specificity": "spe", "reliability": "rlb", "text_quality": "txt"}
FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)


def parse(reply: str) -> dict:
    """The model's assessment from the end of its reply; {"missing": True} or {"invalid": reason} when unusable."""
    for block in reversed(FENCE.findall(reply or "")):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        a = data.get("assessment", data) if isinstance(data, dict) else None
        if isinstance(a, dict) and ("verdict" in a or any(c in a for c in CRITERIA)):
            return _clean(a)
    return {"missing": True}


def _clean(a: dict) -> dict:
    out, problems = {}, []
    for c in CRITERIA:
        v = a.get(c)
        score = v.get("score") if isinstance(v, dict) else v
        why = str(v.get("why") or "")[:300] if isinstance(v, dict) else ""
        if isinstance(score, (int, float)) and 1 <= score <= 5:
            out[c] = {"score": int(round(score)), "why": why}
        else:
            problems.append(c)
    verdict = str(a.get("verdict") or "").strip().lower()
    if verdict in VERDICTS:
        out["verdict"] = verdict
    else:
        problems.append("verdict")
    out["summary"] = str(a.get("summary") or "")[:400]
    if problems:
        out["invalid"] = "missing or out of range: " + ", ".join(problems)
    return out


def signals(rec: dict, slug: str, chars: int, created: list[str], updated: list[str]) -> dict:
    """What the ingest produced, measured: no model involved."""
    cite = re.compile(r"\[\[" + re.escape(slug) + r"(?:\]\]|\|)")
    citations, citing = 0, 0
    for p in pages.wiki().rglob("*.md"):
        n = len(cite.findall(p.read_text(encoding="utf-8")))
        citations += n
        if n and p.stem != slug:
            citing += 1
    info = {}
    f = catalog.instance() / "raw" / rec["id"] / "extract.json"
    if f.exists():
        info = json.loads(f.read_text(encoding="utf-8"))
    out = {"chars": chars, "pages_created": len(created), "pages_updated": len(updated), "pages_citing": citing,
           "citations": citations, "citations_per_10k_chars": round(citations * 10_000 / chars, 1) if chars else 0.0}
    for k in ("pages_needing_ocr", "slides_without_text", "hidden_slides", "cut_sheets"):
        if info.get(k):
            out[k] = info[k]
    return out


def record(rec: dict, reply: str, slug: str, chars: int, created: list[str], updated: list[str], model: str = "") -> dict:
    a = {"source_id": rec["id"], "title": rec["title"], "kind": rec["kind"], "ref": rec["origin"].get("ref"),
         "assessed": catalog.now(), "model": model, "model_assessment": parse(reply),
         "signals": signals(rec, slug, chars, created, updated)}
    (catalog.instance() / "raw" / rec["id"] / "assessment.json").write_text(json.dumps(a, ensure_ascii=False, indent=1), encoding="utf-8")
    return a


def load_all() -> list[dict]:
    out = []
    for f in sorted((catalog.instance() / "raw").glob("*/assessment.json")):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except ValueError:
            continue
    return sorted(out, key=lambda a: a.get("assessed") or "", reverse=True)


def row(a: dict) -> dict:
    """One flat row for a table or CSV."""
    m, s = a.get("model_assessment") or {}, a.get("signals") or {}
    r = {"source_id": a["source_id"], "title": a["title"], "ref": a.get("ref") or "", "verdict": m.get("verdict", "?")}
    for c in CRITERIA:
        r[c] = (m.get(c) or {}).get("score", "")
    r.update({k: s.get(k, "") for k in ("chars", "pages_created", "pages_updated", "pages_citing", "citations", "citations_per_10k_chars")})
    r["summary"] = m.get("summary") or ("(no assessment in the reply)" if m.get("missing") else m.get("invalid", ""))
    return r


def short(a: dict) -> str:
    """One line for the commit message and the log."""
    m = a.get("model_assessment") or {}
    if m.get("missing"):
        return "no assessment in the reply"
    scores = " ".join(f"{ABBR[c]}={(m.get(c) or {}).get('score', '?')}" for c in CRITERIA)
    return f"{m.get('verdict', '?')} ({scores}); {a['signals']['citations_per_10k_chars']} citations per 10k characters"

