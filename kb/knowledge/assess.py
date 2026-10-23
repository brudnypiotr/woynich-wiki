"""Quality of a source after its ingest: read-only, it decides nothing (yet).

Two halves, kept apart so they can be compared:
  - the model's judgement: it has just read the whole source and the wiki, so it scores relevance, novelty,
    specificity, reliability and text quality (1–5, each with a reason) and gives a verdict; it costs nothing extra,
    it is the end of the ingest reply (prompts/ingest.md, step 9);
  - measured signals: what the ingest actually produced (pages, citations per 10k characters) and what extraction
    noticed (pages without text, empty slides).

Saved as raw/<id>/assessment.json and committed with the ingest. `kb assess` lists them (also as CSV), so a curator
can see how the scores behave before anything is filtered or skipped automatically.

Sources ingested before this existed are assessed afterwards with `kb assess --backfill`: the measured signals for free,
the model's judgement with `--model` (one read-only session per source, prompts/assess.md; novelty then means what
the wiki would lose without the source, since its knowledge is already in). These carry `"mode": "backfill"`.
"""
from __future__ import annotations

import hashlib
import json
import re

from kb.knowledge import catalog, pages

CRITERIA = ("relevance", "novelty", "specificity", "reliability", "text_quality")
VERDICTS = ("core", "useful", "marginal", "noise")
ABBR = {"relevance": "rel", "novelty": "nov", "specificity": "spe", "reliability": "rlb", "text_quality": "txt"}
FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)
BARE = re.compile(r'\{\s*"(?:assessment|verdict|relevance)"')  # an assessment without the ```json fence


def prompt_version(mode: str) -> str:
    """Short fingerprint of the prompt that judges in this mode (ingest.md at ingest, assess.md afterwards), so
    assessments made before a change of criteria can be told apart and run again."""
    from kb.knowledge import agent
    text = agent.template("ingest" if mode == "ingest" else "assess")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def parse(reply: str) -> dict:
    """The model's assessment from the end of its reply; {"missing": True} or {"invalid": reason} when unusable.
    Fenced ```json blocks first; then bare JSON, which a model asked for "the JSON only" often replies with."""
    reply = reply or ""
    blocks = list(reversed(FENCE.findall(reply)))
    dec = json.JSONDecoder()
    for m in reversed(list(BARE.finditer(reply))):
        try:
            blocks.append(dec.raw_decode(reply, m.start())[0])
        except ValueError:
            continue
    for block in blocks:
        try:
            data = json.loads(block) if isinstance(block, str) else block
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


def wiki_texts() -> dict[str, str]:
    """Every wiki page's text by file stem: read once when many sources are measured."""
    return {p.stem: p.read_text(encoding="utf-8") for p in pages.wiki().rglob("*.md")}


def signals(rec: dict, slug: str, chars: int, created: list[str] | None, updated: list[str] | None,
            texts: dict[str, str] | None = None) -> dict:
    """What the ingest produced, measured: no model involved."""
    cite = re.compile(r"\[\[" + re.escape(slug) + r"(?:\]\]|\|)")
    citations, citing = 0, 0
    for stem, text in (texts if texts is not None else wiki_texts()).items():
        n = len(cite.findall(text))
        citations += n
        if n and stem != slug:
            citing += 1
    info = {}
    f = catalog.instance() / "raw" / rec["id"] / "extract.json"
    if f.exists():
        info = json.loads(f.read_text(encoding="utf-8"))
    out = {"chars": chars, "pages_created": None if created is None else len(created),  # unknown afterwards
           "pages_updated": None if updated is None else len(updated), "pages_citing": citing,
           "citations": citations, "citations_per_10k_chars": round(citations * 10_000 / chars, 1) if chars else 0.0}
    for k in ("pages_needing_ocr", "slides_without_text", "hidden_slides", "cut_sheets"):
        if info.get(k):
            out[k] = info[k]
    return out


def record(rec: dict, reply: str, slug: str, chars: int, created: list[str] | None, updated: list[str] | None,
           model: str = "", mode: str = "ingest", texts: dict[str, str] | None = None) -> dict:
    m = parse(reply)
    a = {"source_id": rec["id"], "title": rec["title"], "kind": rec["kind"], "ref": rec["origin"].get("ref"), "mode": mode,
         "assessed": catalog.now(), "model": model, "model_assessment": m,
         "prompt": prompt_version(mode) if reply else None, "signals": signals(rec, slug, chars, created, updated, texts)}
    if (m.get("missing") or m.get("invalid")) and (reply or model):  # the model answered: keep its end, to see why
        a["reply_end"] = reply[-600:] if reply.strip() else "(empty reply)"
    (catalog.instance() / "raw" / rec["id"] / "assessment.json").write_text(json.dumps(a, ensure_ascii=False, indent=1), encoding="utf-8")
    return a


def backfill(with_model: bool = False, ids: list[str] | None = None, force: bool = False, runner=None,
             progress=None, cancelled=lambda: False) -> list[dict]:
    """Assess sources ingested before assessments existed (or again with force). Without the model: measured signals
    only, no AI credits. With it: one read-only session per source that has no model assessment yet. One commit."""
    from kb.core import gitops
    from kb.knowledge import agent, wiki
    say = progress or (lambda *_: None)
    inst = catalog.instance()
    slugs = {sid: slug for slug, sid in wiki.source_pages().items()}
    todo, olds = [], {}
    for rec in catalog.all_sources():
        sid = rec["id"]
        if (ids and sid not in ids) or rec["status"] != "ingested" or sid not in slugs:
            continue
        f = inst / "raw" / sid / "assessment.json"
        old = json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
        has_model = bool(old) and not (old.get("model_assessment") or {}).get("missing")
        if force or not old or (with_model and not has_model):
            todo.append(rec); olds[sid] = old
    out = []
    runner = runner or (agent.AgentRunner() if with_model and todo else None)
    texts = wiki_texts() if todo else {}  # an assessment never writes pages, so one read serves the whole run
    for i, rec in enumerate(todo, 1):
        if cancelled():  # stop between sources; what is done so far is kept and committed
            say("cancelled", f"stopped after {len(out)} of {len(todo)}")
            break
        sid, slug = rec["id"], slugs[rec["id"]]
        text = inst / "raw" / sid / "text.md"
        chars = len(text.read_text(encoding="utf-8")) if text.exists() else 0
        reply, model = "", ""
        if with_model:
            say("assessing", f"{i}/{len(todo)} {rec['title']}")
            ref = str(rec["origin"].get("ref") or "")
            extra = f"- Found in the folder: `{ref.rsplit('/', 1)[0]}/`" if "/" in ref else ""
            res = runner.run(agent.prompt("assess", title=rec["title"], kind=rec["kind"], source_id=sid, source_slug=slug,
                                          text_path=f"raw/{sid}/text.md", chars=f"{chars:,}", extra=extra),
                             agent.model_for("classify"), inst, write_dirs=())
            agent.meter("agent_assess", res, sid)
            reply, model = res.reply, res.model
        old = olds[sid]
        if not with_model and old and not (old.get("model_assessment") or {}).get("missing"):
            a = {**old, "signals": signals(rec, slug, chars, None, None, texts), "signals_updated": catalog.now()}  # keep the judgement
            (inst / "raw" / sid / "assessment.json").write_text(json.dumps(a, ensure_ascii=False, indent=1), encoding="utf-8")
        else:
            a = record(rec, reply, slug, chars, None, None, model=model, mode="backfill", texts=texts)
        say("assessed", f"{rec['title']}: {short(a)}")
        out.append(a)
    if out:
        gitops.commit(inst, [inst / "raw" / a["source_id"] / "assessment.json" for a in out], gitops.message(
            "catalog", f"assess {len(out)} source(s) afterwards" + (" with the model" if with_model else " (measured only)"),
            body="\n".join(f"{a['source_id']} {a['title']}: {short(a)}" for a in out)[:4000]))
    return out


def overview() -> dict:
    """Every ingested source with its assessment (or none), for the Sources view, and the current prompt versions."""
    from kb.knowledge import wiki
    inst = catalog.instance()
    slugs = {sid: slug for slug, sid in wiki.source_pages().items()}
    rows = []
    for rec in catalog.all_sources():
        if rec["status"] != "ingested" or rec["id"] not in slugs:
            continue
        f = inst / "raw" / rec["id"] / "assessment.json"
        try:
            a = json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
        except ValueError:
            a = None
        rows.append({"id": rec["id"], "title": rec["title"], "kind": rec["kind"], "ref": rec["origin"].get("ref") or "",
                     "slug": slugs[rec["id"]], "assessment": a})
    return {"sources": rows, "prompts": {"ingest": prompt_version("ingest"), "backfill": prompt_version("backfill")},
            "criteria": list(CRITERIA)}


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
    r.update({k: "" if s.get(k) is None else s[k] for k in ("chars", "pages_created", "pages_updated", "pages_citing", "citations", "citations_per_10k_chars")})
    r["summary"] = m.get("summary") or ("(no assessment in the reply)" if m.get("missing") else m.get("invalid", ""))
    return r


def short(a: dict) -> str:
    """One line for the commit message and the log."""
    m = a.get("model_assessment") or {}
    if m.get("missing"):
        why = "the model's reply was empty" if a.get("reply_end") == "(empty reply)" else \
            "no assessment in the model's reply" if a.get("reply_end") else "no model assessment"
        return f"{why}; {a['signals']['citations_per_10k_chars']} citations per 10k characters"
    scores = " ".join(f"{ABBR[c]}={(m.get(c) or {}).get('score', '?')}" for c in CRITERIA)
    return f"{m.get('verdict', '?')} ({scores}); {a['signals']['citations_per_10k_chars']} citations per 10k characters"

