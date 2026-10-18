"""Render wiki pages from verified claims. Code writes every citation; the model only contributes sentences that
must reference claim numbers. Pages are `status: draft` until a human reviews them (ADR-0005)."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from kb.knowledge import catalog, llmjson

MAX_TOPIC_CLAIMS_FOR_MODEL = 40


def wiki() -> Path:
    return catalog.instance() / "wiki"


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def cite(c: dict, rel: str = "..") -> str:
    """Canonical citation used everywhere (verify.py parses exactly this)."""
    rec = catalog.load(c["source_id"])
    loc = c["locator"]
    if rec["kind"] == "code" and loc.startswith("L"):
        loc = f"{rec['origin']['ref']}:{loc[1:]}" + (f"@{rec['version'][:7]}" if rec.get("version") else "")
    elif rec["kind"] == "ticket" and loc.startswith("#") and rec.get("key"):
        loc = f"{rec['key']}{loc}"
    return f"[{rec['title']}]({rel}/sources/{c['source_id']}.md) · {loc}"


def claim_line(c: dict, rel: str = "..") -> str:
    q = c["quote"].replace('"', "'")
    return f"- {c['text']} — {cite(c, rel)}\n  > \"{q}\""


def frontmatter(**kv) -> str:
    lines = ["---"] + [f"{k}: {json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v}" for k, v in kv.items()] + ["---", ""]
    return "\n".join(lines)


def write_source_page(rec: dict, claims: list[dict], summary: list[dict], topic_map: dict) -> Path:
    by_n = {c["n"]: c for c in claims}
    lines = [frontmatter(type="source", status="draft", source_id=rec["id"], kind=rec["kind"], updated=today()),
             f"# {rec['title']}", "",
             f"Kind: {rec['kind']} · Origin: {rec['origin']['connector']} `{rec['origin']['ref']}` · Collected: {rec['collected_at'][:10]}"
             + (f" · Version: {rec['version']}" if rec.get("version") else ""), "", "## Summary"]
    for s in summary:
        refs = "; ".join(dict.fromkeys(cite(by_n[n]).split(" · ", 1)[1] for n in s["claims"] if n in by_n))
        lines.append(f"- {s['sentence'].strip()} ({refs})")
    if not summary:
        lines.append("_No summary yet._")
    lines += ["", "## Facts (verified quotes)"] + [claim_line(c) for c in claims] or ["_none_"]
    if topic_map:
        lines += ["", "## Topics"] + [f"- [{t['title']}](../topics/{slug}.md)" for slug, t in topic_map.items()]
    p = wiki() / "sources" / f"{rec['id']}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (catalog.instance() / "raw" / rec["id"] / "topics.json").write_text(json.dumps(topic_map, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def topic_index() -> dict[str, str]:
    out = {}
    for f in sorted((wiki() / "topics").glob("*.json")) if (wiki() / "topics").exists() else []:
        out[f.stem] = json.loads(f.read_text(encoding="utf-8")).get("title", f.stem)
    return out


def topic_claims(slug: str) -> list[dict]:
    """All verified claims assigned to a topic, across every source (deterministic order)."""
    out = []
    for tj in sorted((catalog.instance() / "raw").glob("*/topics.json")):
        topics = json.loads(tj.read_text(encoding="utf-8"))
        if slug not in topics:
            continue
        claims = json.loads((tj.parent / "claims.json").read_text(encoding="utf-8"))["verified"]
        wanted = set(topics[slug]["claims"])
        out += [c for c in claims if c["n"] in wanted]
    return out


def update_topic(gw, slug: str, title: str, rec: dict, new_claims: list[dict]) -> Path:
    from kb.knowledge.ingest import CONFLICT_SCHEMA, RULES, SYNOPSIS_SCHEMA
    claims = topic_claims(slug)
    numbered = claims[:MAX_TOPIC_CLAIMS_FOR_MODEL]
    listing = "\n".join(f"[{i}] {c['text']} (source: {catalog.load(c['source_id'])['title']}, {c['locator']})" for i, c in enumerate(numbered, 1))
    synopsis, conflicts = [], []
    if numbered:
        try:
            data = llmjson.ask(gw, "write_page", f"{RULES}\nWrite a synopsis of the topic '{title}' in 2 to 5 sentences using ONLY these numbered facts. "
                               "Each sentence must list the fact numbers it relies on.\n\nFACTS:\n" + listing, SYNOPSIS_SCHEMA, stage="topic")
            synopsis = [s for s in data["sentences"] if s["claims"] and all(1 <= n <= len(numbered) for n in s["claims"])]
        except ValueError:
            pass
        if len({c["source_id"] for c in numbered}) > 1 or len(numbered) > 3:
            try:
                data = llmjson.ask(gw, "verify_support", f"{RULES}\nFind contradictions between these numbered facts. A contradiction is two facts that give a different "
                                   "value, limit, rule or date for the SAME thing, e.g. one source says 12 hours and another says 10 hours for the "
                                   "same rest rule, even if one of them says it was changed. Facts about different things (e.g. home base vs away "
                                   "from home base) are not contradictions. For each contradiction list the fact numbers and explain in one "
                                   "sentence what differs. Return an empty list if there are none.\n\nFACTS:\n" + listing,
                                   CONFLICT_SCHEMA, stage="conflicts")
                conflicts = [c for c in data["conflicts"] if len(c["claims"]) >= 2 and all(1 <= n <= len(numbered) for n in c["claims"])]
            except ValueError:
                pass
    return render_topic(slug, title, claims, numbered, synopsis, conflicts)


def render_topic(slug: str, title: str, claims: list[dict], numbered: list[dict], synopsis: list[dict], conflicts: list[dict]) -> Path:
    """Write topic JSON + Markdown from verified claims (no model call). Synopsis/conflict refs index into `numbered`."""
    data = {"slug": slug, "title": title, "updated": today(), "synopsis": synopsis, "conflicts": conflicts,
            "claims": [f"{c['source_id']}:{c['n']}" for c in numbered]}
    (wiki() / "topics").mkdir(parents=True, exist_ok=True)
    (wiki() / "topics" / f"{slug}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [frontmatter(type="topic", status="draft", slug=slug, updated=today(), sources=sorted({c["source_id"] for c in claims})),
             f"# {title}", "", "## Synopsis"]
    for s in synopsis:
        refs = dict.fromkeys(cite(numbered[n - 1]).split(" · ", 1)[0] + " · " + numbered[n - 1]["locator"] for n in s["claims"])
        lines.append(f"- {s['sentence'].strip()} ({'; '.join(refs)})")
    if not synopsis:
        lines.append("_No synopsis yet._")
    if conflicts:
        lines += ["", "## Discrepancies ⚖️"]
        for c in conflicts:
            lines.append(f"- ⚖️ {c['explanation'].strip()}")
            lines += [f"  - {numbered[n - 1]['text']} — {cite(numbered[n - 1])}" for n in c["claims"]]
    lines += ["", "## Facts"] + [claim_line(c) for c in claims]
    p = wiki() / "topics" / f"{slug}.md"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_discrepancies()
    return p


def drop_source(sid: str) -> list[Path]:
    """Remove one source's facts from topic pages and the glossary without calling the model: synopsis sentences
    and conflicts that cite the removed source are dropped, the rest is re-numbered. Returns touched paths."""
    touched = []
    tdir = wiki() / "topics"
    for f in sorted(tdir.glob("*.json")) if tdir.exists() else []:
        t = json.loads(f.read_text(encoding="utf-8"))
        keys = t.get("claims", [])
        md = tdir / f"{t['slug']}.md"
        if not any(k.startswith(sid + ":") for k in keys) and not (md.exists() and sid in md.read_text(encoding="utf-8")):
            continue
        claims = topic_claims(t["slug"])  # raw/<sid> is already gone
        if not claims:
            f.unlink(); (tdir / f"{t['slug']}.md").unlink(missing_ok=True)
            touched += [f, tdir / f"{t['slug']}.md"]
            continue
        numbered = claims[:MAX_TOPIC_CLAIMS_FOR_MODEL]
        new_index = {f"{c['source_id']}:{c['n']}": i for i, c in enumerate(numbered, 1)}
        remap = lambda refs: [new_index[keys[n - 1]] for n in refs if 0 < n <= len(keys) and keys[n - 1] in new_index]
        keep = lambda refs: all(0 < n <= len(keys) and not keys[n - 1].startswith(sid + ":") for n in refs)
        synopsis = [{**x, "claims": remap(x["claims"])} for x in t.get("synopsis", []) if keep(x["claims"])]
        conflicts = [{**x, "claims": remap(x["claims"])} for x in t.get("conflicts", []) if keep(x["claims"])]
        touched += [f, render_topic(t["slug"], t["title"], claims, numbered, [x for x in synopsis if x["claims"]],
                                    [x for x in conflicts if len(x["claims"]) >= 2])]
    gpath = wiki() / "glossary.json"
    if gpath.exists():
        gloss = json.loads(gpath.read_text(encoding="utf-8"))
        for k in list(gloss):
            gloss[k]["cites"] = [c for c in gloss[k]["cites"] if c["source_id"] != sid]
            if not gloss[k]["cites"]:
                del gloss[k]
        gpath.write_text(json.dumps(gloss, ensure_ascii=False, indent=1), encoding="utf-8")
        touched += update_glossary({"id": sid}, [])
    touched.append(write_discrepancies())
    return touched


def write_discrepancies() -> Path:
    lines = [frontmatter(type="discrepancies", status="draft", updated=today()), "# Discrepancies ⚖️", "",
             "Conflicts between sources found during ingest. Experts decide which source wins (authority hierarchy, validity dates).", ""]
    n = 0
    for f in sorted((wiki() / "topics").glob("*.json")):
        t = json.loads(f.read_text(encoding="utf-8"))
        for c in t.get("conflicts", []):
            n += 1
            lines.append(f"- **[{t['title']}](topics/{t['slug']}.md):** {c['explanation'].strip()}")
    if not n:
        lines.append("_None found yet._")
    p = wiki() / "discrepancies.md"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


ACR_LONG_FIRST = re.compile(r"\b([A-Z][a-zA-Z]+(?:[ \-](?:of|and|for|the|[A-Z][a-zA-Z]+)){1,7})\s*\(([A-Z][A-Z0-9]{1,9}s?)\)")
ACR_SHORT_FIRST = re.compile(r"\b([A-Z][A-Z0-9]{1,9})\s*\(([A-Z][a-zA-Z]+(?:[ \-](?:of|and|for|the|[A-Za-z][a-zA-Z]+)){1,7})\)")


def _initials_match(abbr: str, words: str) -> bool:
    parts = [w for w in re.split(r"[ \-]", words) if w]
    a = abbr.rstrip("s").upper()
    for letters in ("".join(w[0] for w in parts if w.lower() not in ("of", "and", "for", "the")).upper(),
                    "".join(w[0] for w in parts).upper()):
        if a in (letters, letters[-len(a):]):
            return True
    return False


def update_glossary(rec: dict, segs) -> list[Path]:
    gpath = wiki() / "glossary.json"
    gloss = json.loads(gpath.read_text(encoding="utf-8")) if gpath.exists() else {}
    for loc, txt in segs:
        for m in ACR_LONG_FIRST.finditer(txt):
            long, abbr = m.group(1), m.group(2)
            if _initials_match(abbr, long):
                _add_term(gloss, abbr, long, rec["id"], loc)
        for m in ACR_SHORT_FIRST.finditer(txt):
            abbr, long = m.group(1), m.group(2)
            if _initials_match(abbr, long):
                _add_term(gloss, abbr, long, rec["id"], loc)
    gpath.write_text(json.dumps(dict(sorted(gloss.items())), ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [frontmatter(type="glossary", status="draft", updated=today()), "# Glossary", "",
             "Terms and acronyms found in the sources (by rules, not by the model).", "", "| Term | Meaning | Where defined |", "|---|---|---|"]
    for abbr, e in sorted(gloss.items()):
        where = "; ".join(cite({"source_id": c["source_id"], "locator": c["locator"]}, ".") for c in e["cites"][:3])
        lines.append(f"| **{abbr}** | {e['expansion']} | {where} |")
    p = wiki() / "glossary.md"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return [gpath, p]


def _add_term(gloss, abbr, long, sid, loc):
    e = gloss.setdefault(abbr, {"expansion": long.strip(), "cites": []})
    if not any(c["source_id"] == sid and c["locator"] == loc for c in e["cites"]):
        e["cites"].append({"source_id": sid, "locator": loc})


def update_index_log_hot(event: str) -> list[Path]:
    w = wiki(); w.mkdir(parents=True, exist_ok=True)
    srcs = catalog.all_sources()
    topics = topic_index()
    idx = [frontmatter(type="index", updated=today()), "# Index", "",
           f"{len(srcs)} sources · {len(topics)} topics · see also [Glossary](glossary.md), [Discrepancies](discrepancies.md)", "",
           "## Topics"] + [f"- [{t}](topics/{s}.md)" for s, t in sorted(topics.items(), key=lambda x: x[1].lower())] + \
          ["", "## Sources"] + [f"- [{r['title']}](sources/{r['id']}.md) · {r['kind']} · {r['status']}" for r in srcs]
    (w / "index.md").write_text("\n".join(idx) + "\n", encoding="utf-8")
    log = w / "log.md"
    old = log.read_text(encoding="utf-8").split("\n", 2)[2] if log.exists() and log.read_text(encoding="utf-8").startswith("# Log") else ""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    log.write_text(f"# Log\n\n- {stamp} {event}\n{old}", encoding="utf-8")
    recent = [l for l in log.read_text(encoding="utf-8").splitlines() if l.startswith("- ")][:10]
    (w / "hot.md").write_text("# Recent activity\n\n" + "\n".join(recent) + "\n", encoding="utf-8")
    return [w / "index.md", log, w / "hot.md"]
