"""Ingest v2: the model writes the wiki (agent session per source); scripts prepare, check, commit and roll back.

    add (extract text with locators, commit source)  →  agent reads the whole source and the wiki, creates and
    updates pages  →  check (links, citations, contradictions)  →  commit  |  any failure or cancel → rollback
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from kb.core import config, gitops
from kb.knowledge import agent, catalog, pages

SKELETON = {
    "index.md": "---\ntype: index\n---\n# Index\n\nNo pages yet.\n",
    "log.md": "# Log\n\n",
    "hot.md": "# Recent context\n\nThe wiki is empty.\n",
}
FOLDERS = ("sources", "entities", "concepts", "decisions", "answers", "meta")
LARGE_SOURCE_CHARS = 300_000


from kb.knowledge.ingest import Cancelled  # noqa: E402  (one exception type for both ingest modes)


def mode() -> str:
    return ((config.load("profile").get("ingest") or {}).get("mode") or "agent").lower()


def ensure_skeleton() -> Path:
    w = pages.wiki()
    for d in FOLDERS:
        (w / d).mkdir(parents=True, exist_ok=True)
    for name, text in SKELETON.items():
        if not (w / name).exists():
            (w / name).write_text(text, encoding="utf-8")
    return w


def source_slug(rec: dict) -> str:
    """Readable page name for a source; unique across sources."""
    base = re.sub(r"[^a-z0-9]+", "-", rec["title"].lower()).strip("-")[:60] or rec["id"]
    p = pages.wiki() / "sources" / f"{base}.md"
    if p.exists() and f"source_id: {rec['id']}" not in p.read_text(encoding="utf-8")[:400]:
        return f"{base}-{rec['id'][:6]}"
    return base


def source_pages() -> dict[str, str]:
    """slug -> source id, read from the source pages' frontmatter."""
    out = {}
    for p in sorted((pages.wiki() / "sources").glob("*.md")) if (pages.wiki() / "sources").exists() else []:
        m = re.search(r"^source_id:\s*([0-9a-f]{12})", p.read_text(encoding="utf-8")[:600], re.M)
        if m:
            out[p.stem] = m.group(1)
    return out


def _extra(rec: dict, d: Path, chars: int) -> str:
    lines = []
    if rec.get("key"):
        lines.append(f"- Jira key: {rec['key']}")
    if rec.get("version"):
        lines.append(f"- Version / commit: {rec['version']}")
    if rec["origin"].get("url"):
        lines.append(f"- URL: {rec['origin']['url']}")
    figs = sorted((d / "figures").glob("*.png")) if (d / "figures").exists() else []
    if figs:
        lines.append(f"- Figures extracted from the document: `raw/{rec['id']}/figures/` ({len(figs)} images, named by page, "
                     "e.g. p0012-01.png). Look at them where the text refers to a screen or diagram.")
    if chars > LARGE_SOURCE_CHARS:
        lines.append(f"- This source is long. Work through it section by section (e.g. 30–50 pages at a time), updating the "
                     "source page and the knowledge pages as you go, until you reach the end.")
    if rec["kind"] == "transcript":
        lines.append("- This is a recorded conversation. Turn what people explain into knowledge; keep names only for "
                     "decisions, ownership and open doubts. Ignore small talk.")
    return "\n".join(lines)


def ingest_source(sid: str, runner=None, progress=None, cancelled=lambda: False) -> dict:
    step = progress or (lambda *_: None)
    inst = catalog.instance()
    rec = catalog.load(sid)
    d = inst / "raw" / sid
    text = (d / "text.md").read_text(encoding="utf-8") if (d / "text.md").exists() else ""
    if not text.strip():
        rec["status"] = "ingested"; catalog.save(rec)
        return {"id": sid, "created": [], "updated": [], "note": "no text to ingest"}
    catalog.ingest_started(sid)
    try:
        ensure_skeleton()
        slug = source_slug(rec)
        before = {str(p.relative_to(inst)): p.stat().st_mtime for p in pages.wiki().rglob("*.md")}
        task = agent.prompt("ingest", title=rec["title"], kind=rec["kind"], source_id=sid, source_slug=slug,
                            text_path=f"raw/{sid}/text.md", chars=f"{len(text):,}", extra=_extra(rec, d, len(text)),
                            today=pages.today())
        step("writing", f"model reads {len(text):,} characters and writes the wiki")
        runner = runner or agent.AgentRunner()
        res = runner.run(task, agent.model_for("write_page"), inst, write_dirs=("wiki",), progress=step, cancelled=cancelled)
        agent.meter("agent_ingest", res, sid)
        if cancelled():
            raise Cancelled()
        step("checking", "links, citations, contradictions")
        after = {str(p.relative_to(inst)): p.stat().st_mtime for p in pages.wiki().rglob("*.md")}
        created = sorted(set(after) - set(before))
        updated = sorted(k for k in after if k in before and after[k] != before[k])
        src_page = pages.wiki() / "sources" / f"{slug}.md"
        if not src_page.exists():
            raise RuntimeError(f"the model did not write the source page wiki/sources/{slug}.md. Reply: {res.reply[:300]}")
        from kb.knowledge import verify
        report = verify.verify_all()
        rec["status"] = "ingested"
        catalog.save(rec)
        summary = f"{len(created)} pages created, {len(updated)} updated"
        gitops.commit(inst, [d, pages.wiki()], gitops.message(
            "ingest", f"{rec['title']} — {summary}", scope=sid,
            body=f"model: {res.model}\npremium requests: {res.premium}\ntokens in/out: {res.tokens_in}/{res.tokens_out}\n"
                 f"tool calls: {len(res.tools)} (denied: {sum(1 for t in res.tools if not t['ok'])})\n"
                 f"created: {', '.join(created) or '-'}\nupdated: {', '.join(updated) or '-'}"))
        catalog.ingest_finished()
        return {"id": sid, "created": created, "updated": updated, "reply": res.reply, "premium": res.premium,
                "seconds": res.seconds, "warnings": len(report["problems"])}
    except BaseException:
        catalog.rollback()
        raise


def ingest_pending(only: list[str] | None = None, runner=None, progress=None, cancelled=lambda: False) -> list[dict]:
    out = []
    for rec in catalog.all_sources():
        if only and rec["id"] not in only:
            continue
        if not only and rec["status"] != "extracted":
            continue
        out.append(ingest_source(rec["id"], runner, progress, cancelled))
    return out


def ask(question: str, runner=None, history: list[dict] | None = None, topic: str | None = None, save: bool = False) -> dict:
    """Karpathy query: the model reads the index, the relevant pages and, if needed, the sources. Read-only."""
    import time
    inst = catalog.instance()
    ensure_skeleton()
    ctx = ""
    if topic:
        ctx += f"DISCUSSION TOPIC: {topic}\n"
    if history:
        ctx += "EARLIER IN THIS DISCUSSION:\n" + "\n".join(f"Q: {h['question']}\nA: {h.get('answer_text', '')[:800]}" for h in history[-4:]) + "\n"
    t0 = time.perf_counter()
    runner = runner or agent.AgentRunner()
    res = runner.run(agent.prompt("query", question=question, context=ctx), agent.model_for("query"), inst, write_dirs=())
    agent.meter("agent_query", res)
    reply = res.reply.strip()
    not_found = reply.upper().startswith("NOT FOUND")
    out = {"question": question, "answer_text": reply, "not_found": not_found, "seconds": round(time.perf_counter() - t0, 1),
           "premium": res.premium, "pages_read": sorted({p for t in res.tools for p in t.get("paths", []) if t["ok"] and p.endswith(".md")
                                  and (catalog.instance() / p).exists()})}
    log = inst / "catalog" / "queries.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": catalog.now(), "question": question, "sentences": reply.count(". ") + 1,
                            "not_found": not_found, "seconds": out["seconds"], "mode": "agent"}, ensure_ascii=False) + "\n")
    if save and not not_found:
        out["saved"] = str(save_answer(question, reply))
    return out


def save_answer(question: str, answer_md: str, kind: str = "answer") -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", question.lower()).strip("-")[:60] or "answer"
    p = pages.wiki() / "answers" / f"{slug}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(pages.frontmatter(type=kind, status="draft", updated=pages.today()) + f"# {question}\n\n{answer_md}\n", encoding="utf-8")
    _log_line(f"{kind} saved: [[{p.stem}]]")
    gitops.commit(catalog.instance(), [pages.wiki()], gitops.message("ingest", f"{kind}: {question[:80]}", scope="answer"))
    return p


def _log_line(text: str) -> None:
    log = pages.wiki() / "log.md"
    old = log.read_text(encoding="utf-8") if log.exists() else "# Log\n\n"
    head, _, rest = old.partition("\n\n")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    log.write_text(f"{head}\n\n## [{stamp}] {text}\n\n{rest}", encoding="utf-8")


def cleanup_after_remove(rec: dict, slug: str, runner=None) -> dict | None:
    """After a source is removed: let the model remove knowledge that only that source supported."""
    citing = [p for p in pages.wiki().rglob("*.md") if f"[[{slug}]]" in p.read_text(encoding="utf-8")]
    if not citing:
        return None
    runner = runner or agent.AgentRunner()
    res = runner.run(agent.prompt("remove", source_slug=slug, source_id=rec["id"], title=rec["title"]),
                     agent.model_for("write_page"), catalog.instance(), write_dirs=("wiki",))
    agent.meter("agent_remove", res, rec["id"])
    return {"pages_citing": len(citing), "reply": res.reply}


def lint(runner=None) -> dict:
    inst = catalog.instance()
    ensure_skeleton()
    catalog.ingest_started("lint")
    try:
        runner = runner or agent.AgentRunner()
        res = runner.run(agent.prompt("lint", today=pages.today()), agent.model_for("write_page"), inst, write_dirs=("wiki",))
        agent.meter("agent_lint", res)
        gitops.commit(inst, [pages.wiki()], gitops.message("lint", "wiki health check", body=res.reply[:1500]))
        catalog.ingest_finished()
        return {"reply": res.reply, "premium": res.premium}
    except BaseException:
        catalog.rollback()
        raise
