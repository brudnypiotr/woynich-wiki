"""setup/check_install.py (doctor's view of an installed copy): what has broken before is reported at once."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(cwd, env=None) -> dict:
    out = subprocess.run([sys.executable, "-I", str(ROOT / "setup" / "check_install.py")], capture_output=True, text=True,
                         cwd=cwd, env=env, check=True).stdout
    return {c["name"]: c for c in json.loads(out)}


def test_from_any_folder_and_any_python_it_finds_this_copys_code(tmp_path):
    """-I ignores the current folder and PYTHONPATH, like the embeddable Python on the laptops."""
    c = run(tmp_path)
    assert c["App code"]["status"] == "OK" and str(ROOT) in c["App code"]["detail"]
    assert {"App Python", "Packages (requirements.txt)", "Setup for this version"} <= set(c)
    assert all(x["status"] in ("OK", "WARN", "FAIL", "INFO") for x in c.values())


def test_it_names_missing_packages_and_a_guard_from_another_copy(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("check_install", ROOT / "setup" / "check_install.py")
    ci = importlib.util.module_from_spec(spec); spec.loader.exec_module(ci)
    req = tmp_path / "requirements.txt"
    req.write_text("pyyaml>=6\nno-such-package-xyz>=1   # a comment\n\n")
    monkeypatch.setattr(ci, "REPO", tmp_path)
    assert ci.missing_packages() == ["no-such-package-xyz"]
    inst = tmp_path / "instance"
    subprocess.run(["git", "init", "-q", str(inst)], check=True)
    subprocess.run(["git", "-C", str(inst), "config", "core.hooksPath", "C:/old-copy/.githooks"], check=True)
    monkeypatch.setenv("KB_INSTANCE", str(inst))
    (tmp_path / "setup").mkdir(); (tmp_path / "setup" / "version.txt").write_text("3")
    (tmp_path / "local").mkdir(); (tmp_path / "local" / "setup-version.txt").write_text("2")
    (tmp_path / "local" / "update-deps").write_text("abc")
    c = {x["name"]: x for x in ci.checks()}
    assert c["Packages (requirements.txt)"]["status"] == "FAIL" and "no-such-package-xyz" in c["Packages (requirements.txt)"]["detail"]
    assert c["Pre-commit guard (instance)"]["status"] == "WARN" and "old-copy" in c["Pre-commit guard (instance)"]["detail"]
    assert c["Setup for this version"]["status"] == "WARN" and c["Packages after the last update"]["status"] == "WARN"
    assert c["App code"]["status"] == "FAIL"          # kb comes from the real repository, not this fake copy
