"""Read-only Git history tools for the assistant (git_log, git_show, git_blame) and `repo@commit` citations."""
import asyncio
import subprocess
from types import SimpleNamespace

import pytest
import yaml

from kb.knowledge import chat, verify


def _git(repo, *args, who=("Ann Lee", "ann@example.com")):
    subprocess.run(["git", "-C", str(repo), "-c", f"user.name={who[0]}", "-c", f"user.email={who[1]}", *args],
                   check=True, capture_output=True)


@pytest.fixture
def repo(instance, tmp_path):
    r = tmp_path / "demo"
    (r / "rules").mkdir(parents=True)
    _git(r.parent, "init", "-q", str(r))
    (r / "rules" / "min_rest.txt").write_text("min rest 10\n", encoding="utf-8")
    _git(r, "add", "-A"); _git(r, "commit", "-q", "-m", "PROJ-7 first rule")
    (r / "rules" / "min_rest.txt").write_text("min rest 12\n", encoding="utf-8")
    _git(r, "commit", "-qam", "PROJ-9 minimum rest is 12 h", who=("Bob Ray", "bob@example.com"))
    cfg = instance / "config" / "profile.yaml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(yaml.safe_dump({"code_repos": [{"name": "demo", "path": str(r)}]}), encoding="utf-8")
    chat._GIT.clear()
    head = subprocess.run(["git", "-C", str(r), "rev-parse", "--short=8", "HEAD"], capture_output=True, text=True).stdout.strip()
    return r, head


def run(tool, **args):
    res = asyncio.run(tool.handler(SimpleNamespace(arguments=args, session_id="s", tool_call_id="t", tool_name=tool.name)))
    return res.text_result_for_llm


def test_git_history_tools(repo):
    _, head = repo
    tools = {t.name: t for t in chat.git_tools()}
    assert set(tools) == {"git_log", "git_show", "git_blame", "git_refs", "git_grep", "git_diff"}
    log = run(tools["git_log"], repo="demo", grep="proj-9")
    assert "Bob Ray <bob@example.com>" in log and "minimum rest is 12 h" in log and "first rule" not in log
    assert "first rule" in run(tools["git_log"], repo="demo", author="ann", path="rules")
    show = run(tools["git_show"], repo="demo", commit=head)
    assert "Author: Bob Ray" in show and "-min rest 10" in show and "+min rest 12" in show
    assert "Bob Ray" in run(tools["git_blame"], repo="demo", path="rules/min_rest.txt", start=1, end=1)


def test_git_tools_refuse_what_is_not_history(repo):
    tools = {t.name: t for t in chat.git_tools()}
    assert "not a path inside the repository" in run(tools["git_log"], repo="demo", path="../secret")
    assert "not a path inside the repository" in run(tools["git_blame"], repo="demo", path="--output=x", start=1, end=2)
    assert "must be a hash" in run(tools["git_show"], repo="demo", commit="HEAD; rm -rf /")
    assert "unknown repository" in run(tools["git_log"], repo="other")
    assert "YYYY-MM-DD" in run(tools["git_log"], repo="demo", since="yesterday")
    assert "at most 200 lines" in run(tools["git_blame"], repo="demo", path="rules/min_rest.txt", start=1, end=500)


def test_commit_citations_are_checked(repo):
    _, head = repo
    c = verify.check_answer(f"Changed to 12 h by Bob ({'demo@' + head}). Wrong one (demo@deadbee1). Mail ann@abcdef1234.")
    assert f"demo@{head}" in c["ok"]
    assert any(b.startswith("demo@deadbee1") for b in c["broken"])
    assert not any("abcdef1234" in x for x in c["ok"] + c["broken"])  # an e-mail is not a citation
