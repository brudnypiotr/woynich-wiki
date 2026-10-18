"""Ingest v2: sandbox policy, model-written pages with checks and commits, cancel, remove, ask, lint."""
import json
import subprocess
from pathlib import Path

import pytest

from kb.knowledge import agent, catalog, verify, wiki
from scripted_agent import ScriptedAgent

SAMPLES = Path(__file__).resolve().parents[1] / "samples" / "sources"


def git(inst, *a):
    return subprocess.run(["git", "-C", str(inst), *a], capture_output=True, text=True).stdout


def test_sandbox_policy(tmp_path):
    box = agent.Sandbox(tmp_path, ("wiki",))
    assert box.decide("view", {"path": str(tmp_path / "raw/abc/text.md")})[0]
    assert box.decide("glob", {"pattern": "**/*.md", "paths": "wiki"})[0]
    assert not box.decide("view", {"path": "/etc/passwd"})[0]
    assert not box.decide("view", {"path": str(tmp_path / ".." / "secret.txt")})[0]
    assert box.decide("create", {"path": "wiki/concepts/x.md"})[0]
    assert not box.decide("create", {"path": "raw/abc/text.md"})[0]
    assert not box.decide("edit", {"path": str(tmp_path / "config/models.yaml")})[0]
    patch = "*** Begin Patch\n*** Add File: wiki/a.md\n+x\n*** Update File: raw/x/text.md\n*** End Patch"
    assert not box.decide("apply_patch", {"input": patch})[0]
    assert box.decide("apply_patch", {"input": "*** Begin Patch\n*** Add File: wiki/a.md\n+x\n*** End Patch"})[0]
    for tool in ("bash", "powershell", "web_fetch", "rg_unknown"):
        assert not box.decide(tool, {})[0]
    assert not agent.Sandbox(tmp_path, ()).decide("create", {"path": "wiki/a.md"})[0]  # read-only task


def test_ingest_v2_writes_checks_commits(instance):
    for f in sorted(SAMPLES.iterdir()):
        catalog.add_file(f)
    res = wiki.ingest_pending(runner=ScriptedAgent())
    assert len(res) == 4 and all(r["created"] for r in res)
    w = instance / "wiki"
    assert len(list((w / "sources").glob("*.md"))) == 4 and (w / "concepts" / "minimum-rest.md").exists()
    v = verify.verify_all()
    assert v["citations"] >= 8 and v["citations_ok"] == v["citations"] and v["broken_links"] == 0
    assert v["contradictions"] >= 1
    assert not git(instance, "status", "--porcelain").strip()
    assert sum(l.startswith("ingest(") for l in git(instance, "log", "--format=%s").splitlines()) == 4
    assert all(r["status"] == "ingested" for r in catalog.all_sources())


def test_ingest_v2_cancel_rolls_back(instance):
    rec, _ = catalog.add_file(SAMPLES / "rules-review-meeting.vtt")
    with pytest.raises(wiki.Cancelled):
        wiki.ingest_pending(runner=ScriptedAgent(stop_after_reading=True), cancelled=lambda: True)
    assert not (instance / "wiki" / "concepts" / "half-written.md").exists()
    assert not git(instance, "status", "--porcelain").strip()
    assert catalog.load(rec["id"])["status"] == "extracted"


def test_ingest_v2_fails_without_source_page(instance):
    class Lazy(ScriptedAgent):
        def run(self, *a, **k):
            return agent.AgentResult("I did nothing", 0.1, "m", 1, 1, 1.0, [])
    catalog.add_file(SAMPLES / "summer-roster-rules.eml")
    with pytest.raises(RuntimeError, match="did not write the source page"):
        wiki.ingest_pending(runner=Lazy())
    assert not git(instance, "status", "--porcelain").strip()


def test_remove_v2_cleans_pages(instance):
    for f in sorted(SAMPLES.iterdir()):
        catalog.add_file(f)
    sa = ScriptedAgent()
    wiki.ingest_pending(runner=sa)
    om = next(r for r in catalog.all_sources() if r["kind"] == "document")
    slug = {v: k for k, v in wiki.source_pages().items()}[om["id"]]
    r = catalog.remove(om["id"], runner=sa)
    assert r["cleanup"]["pages_citing"] >= 1
    text = "".join(p.read_text(encoding="utf-8") for p in (instance / "wiki").rglob("*.md") if p.name not in ("log.md",))
    assert f"[[{slug}]]" not in text and not git(instance, "status", "--porcelain").strip()


def test_ask_v2_and_not_found(instance):
    for f in sorted(SAMPLES.iterdir()):
        catalog.add_file(f)
    sa = ScriptedAgent()
    wiki.ingest_pending(runner=sa)
    a = wiki.ask("minimum rest before duty", runner=sa, save=True)
    assert not a["not_found"] and "[[" in a["answer_text"] and Path(a["saved"]).exists()
    assert wiki.ask("catering policy zzzz", runner=sa)["not_found"]
    assert "QUESTION: minimum rest before duty" in sa.prompts[-2]


def test_lint_commits(instance):
    catalog.init()
    wiki.lint(runner=ScriptedAgent())
    assert "lint: wiki health check" in git(instance, "log", "-1", "--format=%s")
