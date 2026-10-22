"""Source quality after ingest: read-only, recorded next to the source, listed by `kb assess`."""
import json
import subprocess
from pathlib import Path

from kb.knowledge import assess, catalog, wiki
from scripted_agent import ScriptedAgent

SAMPLES = Path(__file__).resolve().parents[1] / "samples" / "sources"


def test_parse_takes_the_last_json_block_and_checks_it():
    reply = ('CREATED: a\n```json\n{"not": "this"}\n```\nthen\n```json\n{"assessment": {"relevance": {"score": 5, "why": "core"}, '
             '"novelty": {"score": 4.6, "why": ""}, "specificity": {"score": 2, "why": "vague"}, "reliability": {"score": 3, "why": ""}, '
             '"text_quality": {"score": 5, "why": ""}, "verdict": "Useful", "summary": "s"}}\n```')
    a = assess.parse(reply)
    assert a["verdict"] == "useful" and a["relevance"] == {"score": 5, "why": "core"} and a["novelty"]["score"] == 5
    assert "invalid" not in a
    assert assess.parse("CREATED: a\nUPDATED: b") == {"missing": True}
    assert assess.parse("```json\n{broken\n```") == {"missing": True}
    bad = assess.parse('```json\n{"assessment": {"relevance": {"score": 9}, "verdict": "great"}}\n```')
    assert "relevance" in bad["invalid"] and "verdict" in bad["invalid"] and "relevance" not in bad


def test_ingest_records_the_assessment_and_never_acts_on_it(instance):
    rec, _ = catalog.add_file(SAMPLES / sorted(p.name for p in SAMPLES.iterdir())[0])
    res = wiki.ingest_pending(runner=ScriptedAgent())[0]
    a = res["assessment"]
    assert a["model_assessment"]["verdict"] == "useful" and a["model_assessment"]["specificity"]["score"] == 5
    s = a["signals"]
    assert s["citations"] >= 2 and s["pages_citing"] >= 1 and s["chars"] > 0 and s["citations_per_10k_chars"] > 0
    f = instance / "raw" / rec["id"] / "assessment.json"
    assert json.loads(f.read_text(encoding="utf-8"))["source_id"] == rec["id"]
    git = lambda *x: subprocess.run(["git", "-C", str(instance), *x], capture_output=True, text=True).stdout
    assert not git("status", "--porcelain").strip()                      # committed with the ingest
    assert "assessment: useful (rel=4 nov=3 spe=5 rlb=3 txt=5)" in git("log", "-1", "--format=%b")
    assert catalog.load(rec["id"])["status"] == "ingested"
    rows = [assess.row(x) for x in assess.load_all()]
    assert rows[0]["verdict"] == "useful" and rows[0]["relevance"] == 4 and rows[0]["title"] == rec["title"]


def test_a_reply_without_assessment_still_ingests(instance, monkeypatch):
    catalog.add_file(SAMPLES / sorted(p.name for p in SAMPLES.iterdir())[0])
    agent = ScriptedAgent()
    run = agent.run

    def no_assessment(*a, **k):
        r = run(*a, **k); r.reply = r.reply.split("```")[0]; return r
    agent.run = no_assessment
    res = wiki.ingest_pending(runner=agent)[0]
    assert res["assessment"]["model_assessment"] == {"missing": True} and res["created"]


def test_backfill_for_sources_ingested_before_assessments(instance):
    for f in sorted(SAMPLES.iterdir())[:2]:
        catalog.add_file(f)
    wiki.ingest_pending(runner=ScriptedAgent())
    for f in (instance / "raw").glob("*/assessment.json"):   # as if ingested by an older version
        f.unlink()
    subprocess.run(["git", "-C", str(instance), "commit", "-qam", "catalog: drop"], check=True)
    agent = ScriptedAgent()
    measured = assess.backfill(runner=agent)                    # free: no model session
    assert len(measured) == 2 and not agent.prompts
    a = measured[0]
    assert a["mode"] == "backfill" and a["model_assessment"] == {"missing": True}
    assert a["signals"]["pages_created"] is None and a["signals"]["citations"] >= 2
    assert assess.backfill(runner=agent) == []                  # nothing left to do
    judged = assess.backfill(with_model=True, runner=agent)     # only where the model's judgement is missing
    assert len(judged) == 2 and len(agent.prompts) == 2 and "novelty`: what the wiki would lose" in agent.prompts[0]
    assert judged[0]["model_assessment"]["verdict"] == "core"
    assert assess.backfill(with_model=True, runner=agent) == []
    assert len(assess.backfill(with_model=True, force=True, ids=[a["source_id"]], runner=agent)) == 1
    git = lambda *x: subprocess.run(["git", "-C", str(instance), *x], capture_output=True, text=True).stdout
    assert not git("status", "--porcelain").strip() and git("log", "-1", "--format=%s").startswith("catalog")
    assert assess.row(judged[0])["pages_created"] == ""


def test_backfill_never_replaces_an_assessment_made_at_ingest(instance):
    catalog.add_file(SAMPLES / sorted(p.name for p in SAMPLES.iterdir())[0])
    wiki.ingest_pending(runner=ScriptedAgent())
    agent = ScriptedAgent()
    assert assess.backfill(with_model=True, runner=agent) == [] and not agent.prompts
    again = assess.backfill(force=True, runner=agent)[0]         # measured again; the model's judgement is kept
    assert again["mode"] == "ingest" and again["model_assessment"]["verdict"] == "useful" and not agent.prompts
