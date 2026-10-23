"""Ingest v2: the model writes the wiki (agent session per source); scripts prepare, check, commit and roll back.

    add (extract text with locators, commit source)  →  agent reads the whole source and the wiki, creates and
    updates pages  →  check (links, citations, contradictions)  →  commit  |  any failure or cancel → rollback
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from kb.core import gitops
from kb.knowledge import agent, catalog, pages

SKELETON = {
    "index.md": "---\ntype: index\n---\n# Index\n\nNo pages yet.\n",
    "log.md": "# Log\n\n",
    "hot.md": "# Recent context\n\nThe wiki is empty.\n",
}
FOLDERS = ("sources", "entities", "concepts", "decisions", "answers", "meta")
LARGE_SOURCE_CHARS = 300_000




class Cancelled(Exception):
    """Raised to stop an ingest; everything not yet committed is rolled back."""


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
    ref = str(rec["origin"].get("ref") or "")
    if rec["origin"].get("connector") == "upload" and "/" in ref:  # part of a dropped folder
        lines.append(f"- Found in the folder: `{ref.rsplit('/', 1)[0]}/` (as the user organised the files; folder names often "
                     "say the client, the area, the version or the date: use them as context, but cite the text)")
    figs = sorted(f for f in (d / "figures").iterdir() if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp")) \
        if (d / "figures").exists() else []
    if figs:
        lines.append(f"- Figures extracted from the document: `raw/{rec['id']}/figures/` ({len(figs)} images, "
                     + ("the issue's attached screenshots" if rec["kind"] == "ticket"
                        else "in the order they appear in the document, img-001.png first" if figs[0].name.startswith("img-")
                        else "named by slide, e.g. p0012-01.png is on slide 12" if _is_deck(rec)
                        else "named by page, e.g. p0012-01.png")
                     + "). Look at them where the text refers to a screen or diagram.")
    hint = _extracted(d).get("hint")  # what the extractor knows about its format (a deck, a picture)
    if hint:
        lines.append(f"- {hint}")
    if chars > LARGE_SOURCE_CHARS:
        lines.append(f"- This source is long. Work through it section by section (e.g. 30–50 pages at a time), updating the "
                     "source page and the knowledge pages as you go, until you reach the end.")
    if rec["kind"] == "transcript":
        lines.append("- This is a recorded conversation. Turn what people explain into knowledge; keep names only for "
                     "decisions, ownership and open doubts. Ignore small talk.")
    return "\n".join(lines)


def _extracted(d: Path) -> dict:
    f = d / "extract.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except ValueError:
        return {}


def _is_deck(rec: dict) -> bool:
    return str(rec["origin"].get("ref") or "").lower().endswith(".pptx")


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
        before = {p.relative_to(inst).as_posix(): p.stat().st_mtime for p in pages.wiki().rglob("*.md")}
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
        after = {p.relative_to(inst).as_posix(): p.stat().st_mtime for p in pages.wiki().rglob("*.md")}
        created = sorted(set(after) - set(before))
        updated = sorted(k for k in after if k in before and after[k] != before[k])
        src_page = pages.wiki() / "sources" / f"{slug}.md"
        if not src_page.exists():
            raise RuntimeError(f"the model did not write the source page wiki/sources/{slug}.md. Reply: {res.reply[:300]}")
        from kb.knowledge import assess, verify
        report = verify.verify_all()
        try:  # read-only: a broken assessment never stops an ingest
            quality = assess.record(rec, res.reply, slug, len(text), created, updated, model=res.model)
        except Exception as e:
            quality = {"error": f"{type(e).__name__}: {e}"[:200]}
        step("checking", "assessment: " + (assess.short(quality) if "error" not in quality else quality["error"]))
        rec["status"] = "ingested"
        catalog.save(rec)
        summary = f"{len(created)} pages created, {len(updated)} updated"
        gitops.commit(inst, [d, pages.wiki()], gitops.message(
            "ingest", f"{rec['title']} — {summary}", scope=sid,
            body=f"model: {res.model}\nAI credits: {res.credits}\ntokens in/out: {res.tokens_in}/{res.tokens_out}\n"
                 f"tool calls: {len(res.tools)} (denied: {sum(1 for t in res.tools if not t['ok'])})\n"
                 f"created: {', '.join(created) or '-'}\nupdated: {', '.join(updated) or '-'}\n"
                 f"assessment: {assess.short(quality) if 'error' not in quality else quality['error']}"))
        catalog.ingest_finished()
        return {"id": sid, "created": created, "updated": updated, "reply": res.reply, "premium": res.premium, "credits": res.credits,
                "seconds": res.seconds, "warnings": len(report["problems"]), "assessment": quality}
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
