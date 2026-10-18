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
