import pytest


@pytest.fixture(autouse=True)
def no_usage_to_the_real_inbox(monkeypatch):
    """A developer's own branding may name a real inbox: tests never write usage there (test_inbox turns it back on)."""
    monkeypatch.setenv("KB_NO_USAGE", "1")


@pytest.fixture
def instance(tmp_path, monkeypatch):
    monkeypatch.setenv("KB_INSTANCE", str(tmp_path / "instance"))
    return tmp_path / "instance"
