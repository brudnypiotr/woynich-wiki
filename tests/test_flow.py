"""End-to-end mini-flow on the fictional samples: add → ingest → verify → ask → code-ask → site (scripted model)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from kb.knowledge import ask, catalog, code, ingest, search, verify
from kb.llm.gateway import Gateway
from kb.publish import site

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples" / "sources"
CFG = {"default_adapter": "s", "adapters": {"s": {"module": "scripted_llm:Scripted"}},
       "tiers": {"standard": {"model": "m"}, "basic": {"model": "m"}}, "tasks": {}}


@pytest.fixture
def kb(instance):
    gw = Gateway(cfg=CFG, log_path=instance / "catalog" / "metering.jsonl")
    for f in sorted(SAMPLES.iterdir()):
        catalog.add_file(f)
    return gw


def git_log(inst):
    return subprocess.run(["git", "-C", str(inst), "log", "--format=%s"], capture_output=True, text=True).stdout.splitlines()


def test_add_extracts_with_locators_and_commits(kb, instance):
    recs = {r["kind"]: r for r in catalog.all_sources()}
    assert set(recs) == {"document", "transcript", "ticket", "email"}
    assert all(r["status"] == "extracted" for r in recs.values())
    assert recs["ticket"]["title"].startswith("EXA-142: ")
    pdf_text = (instance / "raw" / recs["document"]["id"] / "text.md").read_text(encoding="utf-8")
    assert "<!-- p. 3 -->" in pdf_text and "12 hours" in pdf_text
    assert sum(m.startswith("source(") for m in git_log(instance)) == 4
    again, created = catalog.add_file(SAMPLES / "EXA-142.jira.json")
    assert not created  # idempotent: same content is never added twice


def test_search_finds_segment(kb):
    search.rebuild()
    hits = search.search("minimum rest home base")
    assert hits and any(h["locator"] == "p. 3" for h in hits)


def test_ingest_verifies_quotes_flags_discrepancy(kb, instance):
    res = ingest.ingest_pending(kb)
    assert len(res) == 4 and all(r["rejected"] >= 1 for r in res)  # invented quote rejected every time
    w = instance / "wiki"
    topic = (w / "topics" / "minimum-rest.md").read_text(encoding="utf-8")
    assert "Invented fact" not in topic and "Bad ref." not in topic
    assert "⚖️" in (w / "discrepancies.md").read_text(encoding="utf-8")
    assert "FDP" in (w / "glossary.md").read_text(encoding="utf-8") and "WOCL" in (w / "glossary.md").read_text(encoding="utf-8")
    v = verify.verify_all()
    assert v["facts"] > 0 and not v["problems"]
    assert sum(m.startswith("ingest(") for m in git_log(instance)) == 4


def test_verify_catches_tampered_quote(kb, instance):
    ingest.ingest_pending(kb)
    p = instance / "wiki" / "topics" / "minimum-rest.md"
    lines = p.read_text(encoding="utf-8").splitlines()
    i = next(i for i, l in enumerate(lines) if l.startswith('  > "'))
    lines[i] = '  > "a quote that nobody ever wrote anywhere"'
    p.write_text("\n".join(lines), encoding="utf-8")
    v = verify.verify_all()
    assert any(pr["issue"] == "quote not found in source" for pr in v["problems"])


def test_ask_cites_and_logs(kb, instance):
    ingest.ingest_pending(kb)
    res = ask.answer("minimum rest at home base", kb, save=True)
    assert not res["not_found"] and "sources/" in ask.render(res)
    assert Path(res["saved"]).exists()
    assert json.loads((instance / "catalog" / "queries.jsonl").read_text(encoding="utf-8").splitlines()[-1])["sentences"] == 1
    assert ask.answer("zzzz qqqq", kb)["not_found"]


def test_code_ask_cites_path_line_commit(kb, instance, tmp_path):
    repo = tmp_path / "rules-repo"
    shutil.copytree(ROOT / "samples" / "code-repo", repo)
    for cmd in (["init", "-q"], ["add", "."], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"]):
        subprocess.run(["git", "-C", str(repo), *cmd], check=True)
    (instance / "config").mkdir(exist_ok=True)
    (instance / "config" / "profile.yaml").write_text(f"code_repos:\n  - {{name: rules, path: '{repo.as_posix()}'}}\n")
    res = code.code_ask("How is minimum rest computed for EXA-142?", kb)
    out = code.render(res)
    assert not res["not_found"] and "rules/rules/" in out and "@" in out
    s = res["snippets"][0]
    assert "MIN_REST_HOME_BASE_HOURS" in s["lines"][s["hit_line"] - s["start"]]


def test_site_builds(kb, instance):
    ingest.ingest_pending(kb)
    html = site.build().read_text(encoding="utf-8")
    assert "const D=" in html and "minimum-rest" in html and "</script>" in html
