"""The inbox: a shared OneDrive folder (from the branding) where feedback files and usage records land by themselves."""
import json
import zipfile

import pytest

from kb.publish import appgit, branding, inbox


@pytest.fixture
def onedrive(tmp_path, monkeypatch):
    """A fake OneDrive for Business with the author's shared folder added, and this copy's local/ in tmp."""
    od = tmp_path / "OneDrive - Example"
    monkeypatch.delenv("KB_NO_USAGE", raising=False)
    monkeypatch.setenv("OneDriveCommercial", str(od))
    monkeypatch.delenv("OneDrive", raising=False)
    monkeypatch.setattr(branding, "settings", lambda: {"inbox": {"folder": "Wiki Inbox", "contact": "author@example.com",
                                                                 "share_url": "https://example.sharepoint.com/x"}})
    local = tmp_path / "local"; local.mkdir()
    monkeypatch.setattr(appgit, "local", lambda: local)
    inbox.user.cache_clear()
    monkeypatch.setattr(inbox, "user", lambda: "me@example.com")
    return od / "Wiki Inbox"


def test_not_connected_until_the_folder_is_in_onedrive(onedrive):
    st = inbox.status()
    assert st["configured"] and not st["connected"] and st["share_usage"] and st["contact"] == "author@example.com"
    onedrive.mkdir(parents=True)
    assert inbox.status()["connected"] and inbox.folder() == onedrive


def test_usage_waits_offline_then_goes_out_with_the_next_record(onedrive):
    inbox.record("start")
    assert (appgit.local() / "usage-pending.jsonl").exists()
    onedrive.mkdir(parents=True)
    inbox.record("question", question="What is the minimum rest?", not_found=False)
    files = list((onedrive / "usage" / "me@example.com").glob("*.jsonl"))
    rows = [json.loads(x) for x in files[0].read_text(encoding="utf-8").splitlines()]
    assert [r["kind"] for r in rows] == ["start", "question"] and rows[1]["question"] == "What is the minimum rest?"
    assert not (appgit.local() / "usage-pending.jsonl").exists()


def test_usage_off_writes_nothing(onedrive):
    onedrive.mkdir(parents=True)
    assert inbox.set_prefs(share_usage=False)["share_usage"] is False
    inbox.record("question", question="secret")
    assert not (onedrive / "usage").exists()


def test_report_sums_per_user(onedrive):
    onedrive.mkdir(parents=True)
    inbox.record("start")
    inbox.record("question", question="Q1", not_found=True)
    inbox.record("session", task="agent_query", tokens_in=100, tokens_out=20, credits=0.5, ok=True)
    inbox.record("session", task="ingest", tokens_in=10, tokens_out=0, credits=0.25, ok=False, error="boom")
    r = inbox.report()
    u = r["users"][0]
    assert (u["user"], u["starts"], u["questions"], u["sessions"], u["tokens"], u["credits"], u["errors"], u["days"]) == \
        ("me@example.com", 1, 1, 2, 130, 0.75, 1, 1)
    assert r["recent_questions"][0]["question"] == "Q1"


def test_feedback_file_goes_to_the_inbox(onedrive, tmp_path):
    onedrive.mkdir(parents=True)
    z = tmp_path / "wiki-feedback-1.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("feedback.md", "# x")
    dest = inbox.deliver_feedback(z)
    assert dest == onedrive / "feedback" / "me@example.com" / z.name and dest.exists()


def test_no_inbox_in_the_branding(monkeypatch, tmp_path):
    monkeypatch.setattr(branding, "settings", lambda: {})
    monkeypatch.setattr(appgit, "local", lambda: tmp_path)
    assert not inbox.status()["configured"] and inbox.folder() is None
    inbox.record("start")  # nothing to do, no error
    assert not (tmp_path / "usage-pending.jsonl").exists()
