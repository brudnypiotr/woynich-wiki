from kb.core import schemas

GOOD = {"id": "abc123def456", "kind": "document", "title": "Ops Manual", "origin": {"connector": "folder_inbox", "ref": "om.pdf"},
        "sha256": "0" * 64, "collected_at": "2026-10-18T10:00:00Z", "found_via": ["inbox"]}


def test_source_record_valid():
    assert schemas.errors("source_record", GOOD) == []


def test_source_record_rejects_long_id_and_unknown_field():
    bad = dict(GOOD, id="Very Long Human Readable Key 2026", extra=1)
    errs = schemas.errors("source_record", bad)
    assert any("id" in e for e in errs) and any("extra" in e for e in errs)
