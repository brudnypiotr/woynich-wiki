from kb.extractors.base import paragraphs_to_md, segments
from kb.extractors.office import CodeExtractor, HtmlExtractor, TranscriptExtractor


def test_segments_roundtrip():
    segs = segments(paragraphs_to_md(["First para.", "", "Second para."]))
    assert segs == [("¶ 1", "First para."), ("¶ 2", "Second para.")]


def test_html_and_code(tmp_path):
    h = tmp_path / "a.html"
    h.write_text("<html><head><title>T</title></head><body><p>One &amp; two</p><script>x()</script><p>Three</p></body></html>")
    out = HtmlExtractor().extract(h)
    assert out["meta"]["title"] == "T" and "One & two" in out["text"] and "x()" not in out["text"]
    c = tmp_path / "x.py"
    c.write_text("\n".join(f"line{i}" for i in range(1, 25)))
    segs = dict(segments(CodeExtractor().extract(c)["text"]))
    assert segs["L11"].startswith("line11") and set(segs) == {"L1", "L11", "L21"}


def test_transcript_minutes(tmp_path):
    v = tmp_path / "m.vtt"
    v.write_text("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n<v A>Hello\n\n00:02:05.000 --> 00:02:06.000\n<v B>Later\n")
    segs = segments(TranscriptExtractor().extract(v)["text"])
    assert [l for l, _ in segs] == ["t. 00:00:01", "t. 00:02:05"] and "A: Hello" in segs[0][1]


FIX = __import__("pathlib").Path(__file__).parent / "fixtures"


def test_docx_reads_structure_tables_notes_and_pictures(tmp_path):
    from kb.extractors.ooxml import DocxExtractor
    r = DocxExtractor().extract(FIX / "sample.docx", out_dir=tmp_path)
    t = r["text"]
    assert "# Rest rules" in t and "## Exceptions" in t
    assert "### Wyjątki lokalne" in t                          # a localised heading style, by its outline level
    assert "Minimum rest is 12 hours. After a night duty:\n14 hours." in t   # tab and line break kept
    assert "- Early start" in t and "- Standby" in t           # list items numbered through their style
    assert "| Client | Rest | Since |\n|---|---|---|\n| Example Air | 12 h | 2024-01-01 |" in t
    assert "10 h \\| short" in t                               # a pipe inside a cell does not break the table
    assert "Rest after travel ten hours." in t and "eight" not in t   # tracked changes: the new text, not the deleted
    assert "[1] Agreed in the March workshop." in t and "Ana: Check with the client." in t
    assert r["meta"]["tables"] == 1 and (tmp_path / "figures" / "img-001.png").exists()
    assert "title" not in r["meta"]                            # "Document1" from docProps never replaces the file name
    assert [loc for loc, _ in segments(t)][:3] == ["¶ 1", "¶ 2", "¶ 3"]


def test_xlsx_rows_with_column_names_dates_and_formulas():
    from kb.extractors.ooxml import XlsxExtractor
    r = XlsxExtractor().extract(FIX / "sample.xlsx")
    t = r["text"]
    assert 'Sheet "Rates", row 2: Client = Example Air | Rest (h) = 12 | Valid from = 2024-01-01 | Note = base' in t
    assert 'Valid from = 2025-03-01' in t                      # a custom date format (dd.mm.yyyy) is still a date
    assert 'row 5: Client = Total | Rest (h) = 22.5' in t      # a formula: its last computed value
    assert '## Sheet "Notes" (hidden)' in t and 'Sheet "Notes", row 2: B = Only one note' in t
    assert '## Sheet "Empty" (empty)' in t and "row 4" not in t
    assert r["meta"]["sheets"] == ["Rates", "Notes", "Empty"]


def test_xlsx_large_sheet_is_cut_with_a_note(monkeypatch):
    from kb.extractors.ooxml import XlsxExtractor
    x = XlsxExtractor(); x.max_rows = 1
    r = x.extract(FIX / "sample.xlsx")
    assert "(The sheet has 3 rows; only the first 1 are included here.)" in r["text"] and r["meta"]["cut_sheets"] == ["Rates"]


def test_catalog_reads_word_and_excel(instance):
    from kb.knowledge import catalog
    catalog.init()
    for name, kind in (("sample.docx", "document"), ("sample.xlsx", "spreadsheet")):
        rec, _ = catalog.add_file(FIX / name)
        assert rec["status"] == "extracted" and rec["kind"] == kind and rec["title"] == "sample"
    assert (instance / "raw" / catalog.add_file(FIX / "sample.docx")[0]["id"] / "figures" / "img-001.png").exists()
