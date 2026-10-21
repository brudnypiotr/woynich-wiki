"""Knowledge pack: a finished knowledge base in one file; importing it replaces the wiki and sources."""
import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from kb.knowledge import catalog, pack
from kb.publish import settings

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "sources" / "example-air-om-a-ch7.pdf"


def make_instance(path, monkeypatch, title, page):
    monkeypatch.setenv("KB_INSTANCE", str(path))
    catalog.init()
    rec, _ = catalog.add_file(SAMPLE)
    (path / "wiki" / "topics").mkdir(parents=True, exist_ok=True)
    (path / "wiki" / "topics" / "rest.md").write_text(page, encoding="utf-8")
    (path / "store").mkdir(exist_ok=True); (path / "store" / "big.pdf").write_bytes(b"large original")
    (path / "sessions").mkdir(exist_ok=True); (path / "sessions" / "s1.json").write_text("{}", encoding="utf-8")
    settings.save({"profile": {"title": title, "jira_base_url": "https://jira.example.com", "jira_email": f"{title[:3]}@example.com"}})
    return rec


def test_export_then_import_replaces_wiki_and_sources(tmp_path, monkeypatch):
    rec = make_instance(tmp_path / "piotr", monkeypatch, "Orders Rules", "# Rest\nminimum rest 12 h\n")
    r = pack.export(tmp_path / "orders.kbpack.zip")
    assert r["sources"] == 1 and r["title"] == "Orders Rules"
    names = zipfile.ZipFile(r["path"]).namelist()
    assert "instance/wiki/topics/rest.md" in names and "instance/store/big.pdf" in names
    assert f"instance/raw/{rec['id']}/text.md" in names
    data = Path(r["path"]).read_bytes()
    assert not any(n.startswith("instance/sessions") for n in names) and b"orders@example.com" not in data  # nothing personal

    monkeypatch.setenv("KB_INSTANCE", str(tmp_path / "colleague"))
    catalog.init()
    (tmp_path / "colleague" / "wiki" / "mine.md").write_text("# Mine\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path / "colleague"), "add", "wiki"], check=True)
    subprocess.run(["git", "-C", str(tmp_path / "colleague"), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "docs: mine"], check=True)
    (tmp_path / "colleague" / "sessions").mkdir(exist_ok=True); (tmp_path / "colleague" / "sessions" / "own.json").write_text("{}")
    out = pack.import_pack(Path(r["path"]))
    c = tmp_path / "colleague"
    assert out["sources"] == 1 and (c / "wiki" / "topics" / "rest.md").exists() and not (c / "wiki" / "mine.md").exists()
    assert (c / "store" / "big.pdf").read_bytes() == b"large original"
    assert (c / "sessions" / "own.json").exists() and not (c / "sessions" / "s1.json").exists()   # own discussions stay
    st = settings.state()["profile"]
    assert st["title"] == "Orders Rules" and st["jira_base_url"] == "https://jira.example.com" and st["jira_email"] == ""
    log = subprocess.run(["git", "-C", str(c), "log", "--format=%s"], capture_output=True, text=True).stdout
    assert "import knowledge pack" in log and "docs: mine" in log   # the replaced wiki is in the history
    assert subprocess.run(["git", "-C", str(c), "status", "--porcelain", "wiki", "raw"], capture_output=True, text=True).stdout == ""


def test_import_refuses_other_zips_and_skips_unsafe_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("KB_INSTANCE", str(tmp_path / "inst"))
    catalog.init()
    plain = tmp_path / "plain.zip"
    with zipfile.ZipFile(plain, "w") as z:
        z.writestr("readme.txt", "x")
    with pytest.raises(ValueError, match="not a knowledge pack"):
        pack.import_pack(plain)
    make_instance(tmp_path / "src", monkeypatch, "Orders Rules", "# Rest\n")
    good = pack.export(tmp_path / "good.kbpack.zip")["path"]
    evil = tmp_path / "evil.kbpack.zip"
    with zipfile.ZipFile(good) as g, zipfile.ZipFile(evil, "w") as z:
        for i in g.infolist():
            z.writestr(i, g.read(i))
        z.writestr("instance/../../escape.txt", "x"); z.writestr("instance/config/profile.yaml", "x: 1")
    monkeypatch.setenv("KB_INSTANCE", str(tmp_path / "inst"))
    pack.import_pack(evil)
    assert not (tmp_path / "escape.txt").exists() and "x: 1" not in (tmp_path / "inst" / "config" / "profile.yaml").read_text()


def test_packs_are_never_committed_to_the_blueprint():
    root = Path(__file__).resolve().parents[1]
    assert subprocess.run(["git", "-C", str(root), "check-ignore", "-q", "orders-rules.kbpack.zip"]).returncode == 0
