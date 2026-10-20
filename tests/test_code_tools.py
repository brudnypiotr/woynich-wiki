"""The registry and the newer read-only tools: kb_search, git_refs/git_grep/git_diff, code_outline/find_symbol."""
import os
import time

import pytest

from kb.knowledge import catalog, chat, tools as agent_tools
from kb.knowledge.tools import code, git as git_group, kb as kb_group
from test_git_tools import _git, repo, run  # noqa: F401  (repo is a fixture)

RULE = """package rules;

public class MaxFdpRule extends Rule {
    private static final int LIMIT = 13;

    public int maxFdp(int sectors) {
        return LIMIT - sectors;
    }
}
"""
USE = "package rules;\n\nclass Checker {\n    Rule r = new MaxFdpRule();\n}\n"


@pytest.fixture
def versions(repo):
    """demo with a release tag on the old rule, a feature branch, and Java code on the checked-out branch."""
    r, _ = repo
    _git(r, "tag", "v1.0", "HEAD~1")
    _git(r, "checkout", "-q", "-b", "feature/rest-14")
    (r / "rules" / "min_rest.txt").write_text("min rest 14\n", encoding="utf-8")
    _git(r, "commit", "-qam", "PROJ-11 rest 14 h")
    _git(r, "checkout", "-q", "-")
    (r / "src").mkdir()
    (r / "src" / "MaxFdpRule.java").write_text(RULE, encoding="utf-8")
    (r / "src" / "Checker.java").write_text(USE, encoding="utf-8")
    _git(r, "add", "-A"); _git(r, "commit", "-qm", "PROJ-12 max FDP rule")
    return r


def tool(group, name):
    return next(t for t in group.tools() if t.name == name)


def test_registry_lists_groups_that_work_here(instance, versions):
    names = {t.name for t in agent_tools.all_tools()}
    assert {"kb_search", "git_refs", "git_grep", "git_diff", "code_outline", "find_symbol"} <= names
    assert not {"jira_get", "jira_search"} & names  # Jira not configured
    lines = agent_tools.context_lines()
    assert any(l.startswith("JIRA: not configured") for l in lines) and any(l.startswith("CODE") for l in lines)
    assert {t.name for t in chat.git_tools()} == {t.name for t in git_group.tools()}


def test_git_refs_grep_diff_see_other_versions(versions):
    refs = run(tool(git_group, "git_refs"), repo="demo")
    assert refs.splitlines()[0] == "checked out: " + _branch(versions)
    assert "v1.0" in refs and "feature/rest-14" in refs
    assert "feature" not in run(tool(git_group, "git_refs"), repo="demo", pattern="v1")

    grep = tool(git_group, "git_grep")
    out = run(grep, repo="demo", text="MIN REST", ref="feature/rest-14")
    head, *hits = out.splitlines()
    assert head.startswith("feature/rest-14 = commit ") and hits == ["rules/min_rest.txt:1:min rest 14"]
    assert "min rest 10" in run(grep, repo="demo", text="min rest", ref="v1.0")
    assert "MaxFdpRule.java" in run(grep, repo="demo", text="maxfdp", path="src")
    assert "no branch, tag or commit" in run(grep, repo="demo", text="x", ref="v9.9")
    assert "not a branch, tag or commit" in run(grep, repo="demo", text="x", ref="main..feature")
    assert "not a branch, tag or commit" in run(grep, repo="demo", text="x", ref="--output=x")
    assert "give a text" in run(grep, repo="demo", text="  ")

    diff = tool(git_group, "git_diff")
    stat = run(diff, repo="demo", old="v1.0", new="feature/rest-14", stat_only=True)
    assert stat.startswith("v1.0 = ") and "rules/min_rest.txt" in stat and "+min rest" not in stat
    patch = run(diff, repo="demo", old="v1.0", new="feature/rest-14", path="rules")
    assert "-min rest 10" in patch and "+min rest 14" in patch
    assert "unknown branch, tag or commit (nope)" in run(diff, repo="demo", old="nope")
    assert "not a path inside" in run(diff, repo="demo", old="v1.0", path="../x")

    assert "rest 14 h" in run(tool(git_group, "git_log"), repo="demo", ref="feature/rest-14")
    assert "rest 14 h" not in run(tool(git_group, "git_log"), repo="demo")


def _branch(r):
    import subprocess
    return subprocess.run(["git", "-C", str(r), "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True).stdout.strip()


def test_outline_recognises_the_kinds_of_files():
    assert code.outline(RULE) == [(3, "class", "MaxFdpRule"), (6, "method", "maxFdp")]
    py = "class A:\n    async def run(self):\n        if x:\n            pass\n"
    assert code.outline(py) == [(1, "class", "A"), (2, "def", "run")]
    ts = "export class Svc {\n  load(id: string): Promise<X> {\n    if (id) {\n  }\n}\nexport async function main() {\n"
    assert code.outline(ts) == [(1, "class", "Svc"), (2, "method", "load"), (6, "function", "main")]
    sql = "CREATE OR REPLACE PROCEDURE dbo.calc_rest AS\ncreate table [crew_rest] (\n"
    assert code.outline(sql) == [(1, "sql", "dbo.calc_rest"), (2, "sql", "[crew_rest]")]
    assert code.outline("!1 Minimum rest\ntext\n!3 Cases\n") == [(1, "section", "Minimum rest"), (3, "section", "Cases")]
    assert code.outline('<rules>\n  <rule name="MaxFdp" value="13"/>\n') == [(2, "element", "rule MaxFdp")]
    assert code.outline("    } else if (a) {\n    while (x) {\n") == []


def test_code_outline_tool(versions):
    t = tool(code, "code_outline")
    out = run(t, repo="demo", path="src/MaxFdpRule.java")
    assert out.splitlines()[0] == "src/MaxFdpRule.java: 9 lines"
    assert "MaxFdpRule" in out and "maxFdp" in out and "     6  method" in out
    assert "no outline" in run(t, repo="demo", path="rules/min_rest.txt")
    assert "no such file" in run(t, repo="demo", path="src/Nope.java")
    assert "not a path inside" in run(t, repo="demo", path="../demo/src/MaxFdpRule.java")
    assert "unknown repository" in run(t, repo="other", path="x")


def test_find_symbol_tool(versions):
    t = tool(code, "find_symbol")
    out = run(t, repo="demo", name="MaxFdpRule")
    defined = out.split("DEFINED", 1)[1].split("USED", 1)[0]
    used = out.split("USED", 1)[1]
    assert out.startswith("checked-out commit ")
    assert "src/MaxFdpRule.java:3:" in defined and "Checker.java" not in defined
    assert "src/Checker.java:4:" in used
    assert "src/MaxFdpRule.java:6:" in run(t, repo="demo", name="Rule.maxFdp").split("USED")[0]  # last part of a dotted name
    assert "Checker.java" not in run(t, repo="demo", name="MaxFdpRule", path="src/MaxFdpRule.java")
    assert "not found in demo" in run(t, repo="demo", name="NoSuchThing")
    assert "give one identifier" in run(t, repo="demo", name="a b; rm")
    assert "not a path inside" in run(t, repo="demo", name="MaxFdpRule", path="../x")


def test_kb_search_finds_pages_and_sources(instance, tmp_path):
    src = tmp_path / "rest-rules.txt"
    src.write_text("Crew rest rules\n\nThe minimum rest after a duty is twelve hours.\n", encoding="utf-8")
    rec, _ = catalog.add_file(src, commit=False)
    wiki = instance / "wiki"
    (wiki / "sources").mkdir(parents=True, exist_ok=True)
    (wiki / "sources" / "rest-rules.md").write_text(f"---\ntype: source\nsource_id: {rec['id']}\n---\n# Rest rules\n", encoding="utf-8")
    t = tool(kb_group, "kb_search")

    out = run(t, query="minimum rest", scope="sources")
    assert "source rest-rules [[rest-rules]]" in out and f"raw/{rec['id']}/text.md" in out and "twelve hours" in out
    assert "no matches" in run(t, query="sectors", scope="all")

    (wiki / "concepts").mkdir(exist_ok=True)
    page = wiki / "concepts" / "sectors.md"
    page.write_text("---\ntype: concept\n---\n# Sectors\nMax FDP drops with the number of sectors.\n", encoding="utf-8")
    later = time.time() + 5
    os.utime(page, (later, later))  # newer than the index, whatever the file system's time resolution
    out = run(t, query="sectors", scope="pages")
    assert out.startswith("wiki/concepts/sectors.md") and "raw/" not in out
