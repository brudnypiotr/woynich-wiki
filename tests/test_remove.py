"""Interrupting an ingest rolls back; removing a source deletes it from raw, pages, topics and glossary."""
import json
import subprocess
from pathlib import Path

import pytest

from kb.knowledge import catalog, ingest, verify
from kb.llm.gateway import Gateway

SAMPLES = Path(__file__).resolve().parents[1] / "samples" / "sources"
CFG = {"default_adapter": "s", "adapters": {"s": {"module": "scripted_llm:Scripted"}},
       "tiers": {"standard": {"model": "m"}, "basic": {"model": "m"}}, "tasks": {}}


@pytest.fixture
def gw(instance):
    return Gateway(cfg=CFG, log_path=instance / "catalog" / "metering.jsonl")


def dirty(inst):
    return subprocess.run(["git", "-C", str(inst), "status", "--porcelain", "--", "raw", "wiki"], capture_output=True, text=True).stdout.strip()


def test_interrupted_ingest_rolls_back(gw, instance):
    rec, _ = catalog.add_file(SAMPLES / "example-air-om-a-ch7.pdf")
    calls = []

    def stop_at_topics(step, detail):
        calls.append(step)
        if step == "topics":
            raise ingest.Cancelled()
    with pytest.raises(ingest.Cancelled):
        ingest.ingest_pending(gw, progress=stop_at_topics)
    assert "facts" in calls and not dirty(instance)
    assert catalog.load(rec["id"])["status"] == "extracted"  # can be ingested again
    assert ingest.ingest_pending(gw)[0]["claims"] > 0


def test_remove_ingested_source(gw, instance):
    for f in sorted(SAMPLES.iterdir()):
        catalog.add_file(f)
    ingest.ingest_pending(gw)
    om = next(r for r in catalog.all_sources() if r["kind"] == "document")
    assert "⚖️" in (instance / "wiki" / "discrepancies.md").read_text(encoding="utf-8")
    catalog.remove(om["id"])
    assert not (instance / "raw" / om["id"]).exists() and not (instance / "wiki" / "sources" / f"{om['id']}.md").exists()
    wiki_text = "".join(p.read_text(encoding="utf-8") for p in (instance / "wiki").rglob("*.md") if p.name not in ("log.md", "hot.md"))
    assert om["id"] not in wiki_text
    assert "FDP" not in json.loads((instance / "wiki" / "glossary.json").read_text(encoding="utf-8"))
    assert "⚖️ " not in (instance / "wiki" / "discrepancies.md").read_text(encoding="utf-8").split("\n", 8)[-1]
    assert not dirty(instance) and not verify.verify_all()["problems"]
    log = subprocess.run(["git", "-C", str(instance), "log", "-1", "--format=%s"], capture_output=True, text=True).stdout
    assert log.startswith(f"fix({om['id']}): remove source")


def test_remove_never_ingested(instance):
    rec, _ = catalog.add_file(SAMPLES / "summer-roster-rules.eml")
    catalog.remove(rec["id"])
    assert catalog.all_sources() == [] and not dirty(instance)
