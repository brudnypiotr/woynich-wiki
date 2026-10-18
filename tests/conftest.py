import pytest


@pytest.fixture
def instance(tmp_path, monkeypatch):
    monkeypatch.setenv("KB_INSTANCE", str(tmp_path / "instance"))
    return tmp_path / "instance"
