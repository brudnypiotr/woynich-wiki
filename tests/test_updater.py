"""Updates from the Git remote (check, apply, rollback, attach a ZIP copy) and the changelog from Git history."""
import json
import subprocess

import pytest

from kb.publish import updater


def git(cwd, *a):
    return subprocess.run(["git", "-C", str(cwd), *a], check=True, capture_output=True, text=True).stdout.strip()


def commit(repo, msg, files):
    for name, text in files.items():
        p = repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", msg)


@pytest.fixture
def repos(tmp_path, monkeypatch):
    """dev: where new versions are made; origin: the official remote (bare); app: the user's copy."""
    origin, dev, app = tmp_path / "origin.git", tmp_path / "dev", tmp_path / "app"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(dev)], check=True)
    sources = json.dumps({"update": {"remote": str(origin), "branch": "main"}})
    commit(dev, "feat(core): first", {"pyproject.toml": 'version = "0.1.0"\n', "setup/sources.json": sources,
                                      "requirements.txt": "a\n", ".gitignore": "instance/\nlocal/\n"})
    git(dev, "remote", "add", "origin", str(origin)); git(dev, "push", "-q", "origin", "main")
    subprocess.run(["git", "clone", "-q", str(origin), str(app)], check=True)
    monkeypatch.setenv("KB_ROOT", str(app))
    monkeypatch.setattr(updater, "_LAST", None)
    return dev, app


def publish(dev, msg, files):
    commit(dev, msg, files)
    git(dev, "push", "-q", "origin", "main")


def test_check_and_apply(repos):
    dev, app = repos
    assert updater.check()["available"] is False
    publish(dev, "fix(serve): the bug the user hit", {"a.py": "x = 1\n"})
    publish(dev, "feat(serve): something new; 0.2.0", {"pyproject.toml": 'version = "0.2.0"\n'})
    c = updater.check()
    assert c["available"] and c["behind"] == 2 and c["latest_version"] == "0.2.0"
    assert [e["kind"] for e in c["incoming"]] == ["Features", "Fixes"]
    r = updater.apply()
    assert r["updated"] and r["version"] == "0.2.0" and not r["packages"] and r["restart"]
    assert (app / "a.py").exists() and updater.check()["available"] is False
    assert updater.apply()["updated"] is False


def test_local_edits_and_commits_do_not_block(repos):
    dev, app = repos
    (app / "instance").mkdir(); (app / "instance" / "page.md").write_text("mine", encoding="utf-8")
    commit(app, "local experiment", {"b.py": "y = 2\n"})                 # a local commit
    (app / "requirements.txt").write_text("edited\n", encoding="utf-8")  # and a local edit of a tracked file
    publish(dev, "fix(setup): new package", {"requirements.txt": "a\nb\n"})
    r = updater.apply()
    assert r["packages"] and any("stash" in n for n in r["notes"]) and any("backup/" in n for n in r["notes"])
    assert (app / "requirements.txt").read_text() == "a\nb\n"
    assert (app / "instance" / "page.md").read_text() == "mine"          # ignored files untouched
    assert (app / "local" / "update-deps").exists()


def test_rollback(repos):
    dev, app = repos
    before = git(app, "rev-parse", "HEAD")
    publish(dev, "feat(serve): breaks something", {"a.py": "boom\n"})
    updater.apply()
    r = updater.rollback()
    assert r["rolled_back"] and git(app, "rev-parse", "HEAD") == before
    with pytest.raises(updater.UpdateError):
        updater.rollback()


def test_attach_zip_copy(repos, tmp_path, monkeypatch):
    dev, app = repos
    publish(dev, "feat(serve): newer than the zip", {"c.py": "z = 3\n"})
    zipcopy = tmp_path / "zip"
    subprocess.run(["git", "clone", "-q", str(app), str(zipcopy)], check=True)
    subprocess.run(["rm", "-rf", str(zipcopy / ".git")], check=True)
    (zipcopy / "instance").mkdir(); (zipcopy / "instance" / "x.md").write_text("keep", encoding="utf-8")
    monkeypatch.setenv("KB_ROOT", str(zipcopy))
    assert updater.check()["clone"] is False
    r = updater.attach()
    assert r["attached"] and (zipcopy / "c.py").exists() and (zipcopy / "instance" / "x.md").read_text() == "keep"
    assert updater.check()["available"] is False
    assert updater.attach()["attached"] is False  # an existing origin is never changed


def test_changelog_groups_by_version(repos):
    dev, app = repos
    publish(dev, "fix(chat): one", {"a.py": "1\n"})
    publish(dev, "feat(serve): two; 0.2.0", {"pyproject.toml": 'version = "0.2.0"\n'})
    publish(dev, "docs: three", {"README.md": "x\n"})
    updater.apply()
    g = updater.changelog()
    assert [x["version"] for x in g] == ["0.2.0", "0.1.0"]
    assert [e["text"] for e in g[0]["entries"]] == ["three", "two; 0.2.0"]
    assert [e["text"] for e in g[1]["entries"]] == ["one", "first"]
    assert g[1]["entries"][0]["scope"] == "chat" and g[1]["entries"][0]["kind"] == "Fixes"
    md = updater.changelog_markdown(g)
    assert "## 0.2.0" in md and "three" not in md and "three" in updater.changelog_markdown(g, all_types=True)


def test_parse():
    assert updater.parse("abc", "2026-10-21", "fix(setup)!: x: y")["text"] == "x: y"
    assert updater.parse("abc", "2026-10-21", 'Revert "feat: x"')["kind"] == "Other"
