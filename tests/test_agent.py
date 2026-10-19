"""Ingest v2: sandbox policy, model-written pages with checks and commits, cancel, remove, ask, lint."""
import json
import re
import subprocess
from pathlib import Path

import pytest

from kb.knowledge import agent, catalog, chat, verify, wiki
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
    a = chat.ask("minimum rest before duty", runner=sa, save=True)
    assert not a["not_found"] and "[[" in a["answer_text"] and Path(a["saved"]).exists()
    assert sa.last["write_dirs"] == () and sa.last["tools"] == []  # read-only; no Jira configured
    assert chat.ask("catering policy zzzz", runner=sa)["not_found"]
    assert "QUESTION: minimum rest before duty" in sa.prompts[-2]


def test_code_ask_reads_configured_repos(instance, tmp_path):
    import shutil
    repo = tmp_path / "rules-repo"
    shutil.copytree(Path(__file__).resolve().parents[1] / "samples" / "code-repo", repo)
    for cmd in (["init", "-q"], ["add", "."], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"]):
        subprocess.run(["git", "-C", str(repo), *cmd], check=True)
    catalog.init()
    (instance / "config").mkdir(exist_ok=True)
    (instance / "config" / "profile.yaml").write_text(
        f"code_repos:\n  - name: rules\n    path: '{repo.as_posix()}'\n    description: Fictional rules engine; rule classes and parameters.\n")
    rs = chat.repos()
    assert rs[0]["name"] == "rules" and rs[0]["commit"] and not rs[0]["dirty"]
    sa = ScriptedAgent()
    shot = tmp_path / "screen.png"; shot.write_bytes(b"\x89PNG")
    a = chat.ask("How is minimum rest computed?", runner=sa, focus="code", attachments=[shot])
    assert re.search(r"rules/rules/\w+\.py:\d+@", a["answer_text"])
    assert sa.last["read_roots"] == [repo] and sa.last["attachments"] == [shot]
    assert "Fictional rules engine" in sa.prompts[-1] and "ATTACHED: 1 image" in sa.prompts[-1]


def test_sandbox_allows_reading_repos_only(tmp_path):
    repo = tmp_path / "repo"; repo.mkdir()
    box = agent.Sandbox(tmp_path / "inst", (), read_roots=(repo,), custom=("jira_get",))
    assert box.decide("view", {"path": str(repo / "src/x.py")})[0]
    assert not box.decide("view", {"path": str(tmp_path / "other/x.py")})[0]
    assert not box.decide("create", {"path": str(repo / "src/x.py")})[0]
    assert box.decide("jira_get", {"key": "PROJ-1"})[0] and not box.decide("jira_delete", {})[0]


def test_lint_commits(instance):
    catalog.init()
    wiki.lint(runner=ScriptedAgent())
    assert "lint: wiki health check" in git(instance, "log", "-1", "--format=%s")


def test_conversation_keeps_one_session_and_hears_about_changes(instance):
    for f in sorted(SAMPLES.iterdir()):
        catalog.add_file(f)
    sa = ScriptedAgent()
    wiki.ingest_pending(runner=sa)
    conv = chat.Conversation(topic="Rest", runner=sa)
    a1 = conv.ask("minimum rest before duty")
    a2 = conv.ask("and at home base minimum rest?")
    assert sa.opened == ["live-1"] and (a1["session"], a2["session"]) == ("new", "continued")
    assert a1["check"]["ok"] and not a1["check"]["broken"]
    assert "# How to work" in sa.prompts[-2] and "DISCUSSION TOPIC: Rest" in sa.prompts[-2] and "wiki/hot.md" in sa.prompts[-2]
    assert "# How to work" not in sa.prompts[-1] and "QUESTION: and at home base" in sa.prompts[-1]
    conv.wiki_changed(["wiki/concepts/minimum-rest.md"])
    conv.ask("minimum rest again")
    assert "WIKI UPDATED" in sa.prompts[-1] and "wiki/concepts/minimum-rest.md" in sa.prompts[-1]
    conv.ask("minimum rest once more")
    assert "WIKI UPDATED" not in sa.prompts[-1]
    conv.close()
    assert sa.closed == ["live-1"] and conv.session_id == "live-1"
    again = chat.Conversation(runner=sa, history=conv.history, resume="live-1")  # resumed: no full prompt
    assert again.ask("minimum rest?")["session"] == "resumed" and "# How to work" not in sa.prompts[-1]
    lost = chat.Conversation(runner=sa, history=conv.history, resume="gone")      # cannot resume: history summary
    assert lost.ask("minimum rest?")["session"] == "new" and "EARLIER IN THIS CONVERSATION" in sa.prompts[-1]


def test_check_answer(instance, tmp_path):
    import shutil
    for f in sorted(SAMPLES.iterdir()):
        catalog.add_file(f)
    wiki.ingest_pending(runner=ScriptedAgent())
    page = next((instance / "wiki" / "sources").glob("*.md"))
    text = page.read_text(encoding="utf-8")
    slug, loc = re.search(r"\(\[\[([^\]]+)\]\] ((?:p\.|L|t\.|¶|#)[^)]*)\)", text).groups()
    repo = tmp_path / "rules-repo"
    shutil.copytree(Path(__file__).resolve().parents[1] / "samples" / "code-repo", repo)
    for cmd in (["init", "-q"], ["add", "."], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"]):
        subprocess.run(["git", "-C", str(repo), *cmd], check=True)
    (instance / "config").mkdir(exist_ok=True)
    (instance / "config" / "profile.yaml").write_text(f"code_repos:\n  - name: rules\n    path: '{repo.as_posix()}'\n")
    commit = git(repo, "rev-parse", "--short", "HEAD").strip()
    code = next(p for p in repo.rglob("*.py")).relative_to(repo).as_posix()
    good = f"Rest is 12 hours ([[{slug}]] {loc}; see [[minimum-rest]]). Computed in rules/{code}:1@{commit} (PROJ-1#c2)."
    r = verify.check_answer(good)
    assert not r["broken"] and len(r["ok"]) == 3 and r["unchecked"] == ["PROJ-1#c2"]
    bad = f"Rest ([[{slug}]] p. 999), see [[no-such-page]], rules/{code}:99999@{commit}, other/x.py:1@{commit}."
    r = verify.check_answer(bad)
    assert len(r["broken"]) == 4 and not r["ok"]
