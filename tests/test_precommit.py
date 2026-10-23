from kb.core import precommit


def test_detects_tokens():
    assert "GitHub token" in precommit.scan_text("x = 'ghp_" + "a" * 36 + "'")
    assert "Private key" in precommit.scan_text("-----BEGIN RSA " + "PRIVATE KEY-----")
    assert precommit.scan_text("nothing secret here, token: <from keyring>") == []


def test_blocks_invalid_record(tmp_path, monkeypatch):
    d = tmp_path / "instance" / "catalog" / "records"; d.mkdir(parents=True)
    f = d / "bad.json"; f.write_text('{"id": "NOT-VALID"}')
    monkeypatch.chdir(tmp_path)
    assert precommit.main([str(f.relative_to(tmp_path))]) == 1


def test_the_hook_finds_kb_without_pythonpath(tmp_path):
    """The embeddable Python on Windows ignores PYTHONPATH: the hook must put the blueprint on the path itself."""
    import os
    import shutil
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t"), ("core.hooksPath", str(root / ".githooks"))):
        subprocess.run(["git", "-C", str(tmp_path), "config", k, v], check=True)
    (tmp_path / "a.txt").write_text("1")
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    subprocess.run(["git", "-C", str(tmp_path), "add", "a.txt"], check=True, env=env)
    r = subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "x"], capture_output=True, text=True, env=env, cwd=shutil.os.sep)
    assert r.returncode == 0, r.stderr
    (tmp_path / "b.txt").write_text("token = 'ghp_" + "a" * 36 + "'")
    subprocess.run(["git", "-C", str(tmp_path), "add", "b.txt"], check=True, env=env)
    r = subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "y"], capture_output=True, text=True, env=env)
    assert r.returncode == 1 and "GitHub token" in r.stderr     # the guard really ran


def test_the_instance_uses_this_copys_guard(instance):
    """A renamed or moved repository folder (or an instance made by another copy) would run another copy's guard."""
    import subprocess
    from kb.core import config
    from kb.knowledge import catalog
    catalog.init()
    git = lambda *x: subprocess.run(["git", "-C", str(instance), *x], capture_output=True, text=True).stdout.strip()
    subprocess.run(["git", "-C", str(instance), "config", "core.hooksPath", "C:/old-copy/.githooks"], check=True)
    catalog._HOOKED.clear()
    catalog.init()
    assert git("config", "core.hooksPath") == str(config.paths().root / ".githooks")
