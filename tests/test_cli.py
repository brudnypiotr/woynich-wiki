from kb import cli


def test_init_creates_instance(instance):
    assert cli.main(["init"]) == 0
    assert all((instance / d).is_dir() for d in cli.INSTANCE_DIRS) and (instance / ".git").is_dir()


def test_completion_script_follows_the_commands():
    from kb import completion
    t = completion.tree()
    assert t["jira"]["values"] == ["get", "search", "add"] and "--links" in t["jira"]["opts"]
    assert "--jql" in t["collect"]["opts"] and t["completion"]["values"] == ["install", "show"]
    s = completion.script()
    assert "Register-ArgumentCompleter -Native -CommandName kb, kb.cmd" in s
    assert "'jira' = @{ h = 'Jira, read-only" in s and "'--no-attachments'" in s
    assert all(line.count("'") % 2 == 0 for line in s.splitlines() if line.startswith("  '"))  # quotes balanced
