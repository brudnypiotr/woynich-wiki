import subprocess

import pytest

from kb.core import gitops


def test_message_convention():
    m = gitops.message("source", "add Ops Manual rev 7", scope="abc123def456", body="sha256 ...")
    assert m.startswith("source(abc123def456): add Ops Manual rev 7") and gitops.TRAILER in m
    with pytest.raises(ValueError):
        gitops.message("auto", "update")


def test_commit_only_given_paths_and_idempotent(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(tmp_path), "config", k, v], check=True)
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text("1"); b.write_text("2")
    h = gitops.commit(tmp_path, [a], gitops.message("source", "add a"))
    assert h
    files = subprocess.run(["git", "-C", str(tmp_path), "show", "--name-only", "--format=", h], capture_output=True, text=True).stdout.split()
    assert files == ["a.txt"]
    assert gitops.commit(tmp_path, [a], gitops.message("source", "add a")) is None  # nothing changed


def test_windows_scripts_are_ascii():
    """Windows PowerShell 5.1 reads a .ps1 without BOM as cp1252: a "→" turns into a quote and breaks setup."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    bad = [f"{p.relative_to(root)}:{n}" for p in [*root.glob("*.cmd"), *(root / "setup").glob("*.ps1")]
           for n, line in enumerate(p.read_bytes().splitlines(), 1) if any(b > 127 for b in line)]
    assert not bad, f"non-ASCII characters in Windows scripts: {bad}"
