import json
from pathlib import Path

import pytest

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



def test_xls_reads_like_xlsx_with_dates_booleans_and_hidden_sheets():
    """Excel 97-2003: the same text as .xlsx (one formatter), so the model and the citations see no difference."""
    from kb.extractors import for_path
    from kb.extractors.legacy import XlsExtractor
    assert isinstance(for_path(FIX / "sample.xls"), XlsExtractor) and not isinstance(for_path(FIX / "sample.xlsx"), XlsExtractor)
    r = XlsExtractor().extract(FIX / "sample.xls")
    t = r["text"]
    assert 'Sheet "Rates", row 2: Client = Example Air | Rest (h) = 12 | Valid from = 2024-01-01 | Note = base' in t
    assert 'row 3: Client = Sample Jet | Rest (h) = 10.5 | Valid from = 2025-03-01' in t   # dd.mm.yyyy is still a date
    assert 'row 4: Client = Check | Rest (h) = TRUE | Valid from = 2025-03-01 14:30' in t
    assert '## Sheet "Notes" (hidden)' in t and 'Sheet "Notes", row 2: B = Only one note' in t
    assert '## Sheet "Empty" (empty)' in t and r["meta"]["sheets"] == ["Rates", "Notes", "Empty"]
    x = XlsExtractor(); x.max_rows = 1
    assert x.extract(FIX / "sample.xls")["meta"]["cut_sheets"] == ["Rates"]



def test_xls_exports_that_are_really_xml_html_or_xlsx(tmp_path):
    """Systems export reports as .xls that are XML Spreadsheet 2003 or an HTML table; Excel opens them, so do we."""
    import shutil
    from kb.extractors.legacy import XlsExtractor
    r = XlsExtractor().extract(FIX / "sample-xml2003.xls")
    t = r["text"]
    assert r["meta"]["format"] == "spreadsheetml" and "Columns: Crew | Rule | Date | Hours" in t
    assert 'row 2: Crew = A. Pilot | Rule = Minimum rest | Date = 2026-03-01 | Hours = 9.5' in t
    assert 'row 4: Crew = B. Cabin | Date = 2026-03-02 14:30 | Hours = 12' in t           # ss:Index skips rows and cells
    assert '## Sheet "Parameters" (hidden)' in t and 'row 1: A = TRUE' in t
    r = XlsExtractor().extract(FIX / "sample-html.xls")
    assert r["meta"]["format"] == "html" and 'row 2: Crew = A. Pilot | Rule = Minimum rest after night | Hours = 9.5' in r["text"]
    assert 'row 3: Crew = Total | Hours = 9.5' in r["text"]                               # colspan keeps the columns
    shutil.copy(FIX / "sample.xlsx", tmp_path / "renamed.xls")
    r = XlsExtractor().extract(tmp_path / "renamed.xls")
    assert r["meta"]["format"] == "xlsx" and "Client = Example Air" in r["text"]
    assert XlsExtractor().extract(FIX / "sample.xls")["meta"]["format"] == "biff"
    (tmp_path / "junk.xls").write_bytes(b"hello")
    with pytest.raises(ValueError, match="not an Excel file"):
        XlsExtractor().extract(tmp_path / "junk.xls")


def test_a_file_that_failed_to_read_is_read_again_when_added_again(instance, monkeypatch, tmp_path):
    """After an Update fixes a reader, dropping the same file again reads it, instead of "already there"."""
    import shutil
    import subprocess
    from kb.extractors.legacy import XlsExtractor
    from kb.knowledge import catalog
    f = shutil.copy(FIX / "sample-xml2003.xls", tmp_path / "report.xls")
    good = XlsExtractor.extract
    monkeypatch.setattr(XlsExtractor, "extract", lambda self, p: (_ for _ in ()).throw(ValueError("old reader")))
    rec, created = catalog.add_file(Path(f))
    info = json.loads((instance / "raw" / rec["id"] / "extract.json").read_text(encoding="utf-8"))
    assert created and rec["status"] == "error" and info["extractor"] == "XlsExtractor" and "old reader" in info["error"]
    monkeypatch.setattr(XlsExtractor, "extract", good)
    rec, created = catalog.add_file(Path(f))
    assert not created and rec["status"] == "extracted" and catalog.load(rec["id"])["status"] == "extracted"
    assert "Crew = A. Pilot" in (instance / "raw" / rec["id"] / "text.md").read_text(encoding="utf-8")
    git = lambda *x: subprocess.run(["git", "-C", str(instance), *x], capture_output=True, text=True).stdout
    assert not git("status", "--porcelain").strip() and "read again: extracted" in git("log", "-1", "--format=%b")

def test_sheet_values_like_excel():
    from kb.extractors import sheets
    assert sheets.number(12.0) == "12" and sheets.number(22.5) == "22.5" and sheets.letters(0) == "A" and sheets.letters(26) == "AA"
    assert sheets.date(45292) == "2024-01-01" and sheets.date(0.5) == "12:00" and sheets.date(0, date1904=True) == "1904-01-01"
    assert sheets.date(-1) is None

def test_pptx_slides_in_order_with_bullets_tables_groups_notes_and_pictures(tmp_path):
    from kb.extractors.ooxml import PptxExtractor
    r = PptxExtractor().extract(FIX / "sample.pptx", out_dir=tmp_path)
    t = r["text"]
    segs = dict(segments(t))
    assert [loc for loc in segs] == ["p. 1", "p. 2", "p. 3", "p. 4", "p. 5"]      # one marker per slide, cited as p. N
    assert segs["p. 1"] == "## Slide 1: Onboarding a new client\n\nImplementation kick-off"   # a subtitle is not a bullet
    assert "- Minimum rest is 12 hours\n  - After a night duty: 14 hours\n- Standby counts as duty" in segs["p. 2"]
    assert "Speaker notes: Ask the client about split duty." in segs["p. 2"]
    assert "| Client | Rest |\n|---|---|\n| Example Air | 12 h |" in segs["p. 3"] and "10 h \\| short" in segs["p. 3"]
    assert "Inside a group" in segs["p. 3"]                     # text inside a grouped shape
    assert segs["p. 4"].startswith("## Slide 4: Draft ideas (hidden)")
    assert "(no text on this slide)" in segs["p. 5"]
    assert r["meta"]["slides"] == 5 and r["meta"]["hidden_slides"] == [4] and r["meta"]["slides_without_text"] == [5]
    assert r["meta"]["tables"] == 1 and (tmp_path / "figures" / "p0003-01.png").exists()   # named by slide, like PDF pages


def test_catalog_reads_word_excel_and_powerpoint(instance):
    from kb.knowledge import catalog
    catalog.init()
    for name, kind in (("sample.docx", "document"), ("sample.xlsx", "spreadsheet"), ("sample.pptx", "document")):
        rec, _ = catalog.add_file(FIX / name)
        assert rec["status"] == "extracted" and rec["kind"] == kind and rec["title"] == "sample"
    assert (instance / "raw" / catalog.add_file(FIX / "sample.docx")[0]["id"] / "figures" / "img-001.png").exists()


def test_xsd_outline_with_lines_docs_and_values():
    from kb.extractors.xmlfile import XmlExtractor
    t = XmlExtractor().extract(FIX / "rules.xsd")["text"]
    assert '- element Rules (L 3): "All rules of one client."' in t
    assert "  - element Rule: RuleType [0..unbounded] (L 7)" in t
    assert '- complexType RuleType (L 11): "One rule: a name, a severity and parameters."' in t
    assert "  - attribute id: ID (required) (L 17)" in t
    assert "- simpleType Severity (L 20); allowed values: ERROR, WARNING, INFO" in t
    segs = dict(segments(t))
    assert '<xs:element name="Rules">' in segs["L1"] and "enumeration" in segs["L21"]   # cited by line, as code
    assert "top" in segs and "Schema outline" in segs["top"]   # the outline is a map, not a citable segment


def test_xml_in_utf16_with_polish_text_and_its_shape():
    from kb.extractors.xmlfile import XmlExtractor
    r = XmlExtractor().extract(FIX / "rules-utf16.xml")
    assert "żółw" in r["text"] and "Odpoczynek minimalny 11 h" in r["text"] and "\x00" not in r["text"]
    assert "root <Rules>, 37 elements; most common: <Param> ×24, <Rule> ×12" in r["text"]
    assert r["meta"]["lines"] == 15


def test_xml_encoding_from_the_declaration_and_broken_xml(tmp_path):
    from kb.extractors.xmlfile import XmlExtractor
    f = tmp_path / "cfg.xml"
    f.write_bytes('<?xml version="1.0" encoding="windows-1250"?>\n<a>Łódź</a>\n'.encode("cp1250"))
    assert "Łódź" in XmlExtractor().extract(f)["text"]
    f.write_text("<a><b></a>\n", encoding="utf-8")
    r = XmlExtractor().extract(f)
    assert "Not well-formed XML" in r["text"] and "<a><b></a>" in r["text"] and r["meta"]["xml_error"]


def test_xml_and_xsd_go_to_the_xml_reader_jira_xml_stays():
    from pathlib import Path
    from kb import extractors
    assert type(extractors.for_path(Path("a.xsd"))).__name__ == "XmlExtractor"
    assert type(extractors.for_path(Path("a.xml"))).__name__ == "XmlExtractor"
    assert type(extractors.for_path(Path("PROJ-1.jira.xml"))).__name__ == "JiraXmlExtractor"
    assert type(extractors.for_path(Path("Deck.PPTX"))).__name__ == "PptxExtractor" and ".pptx" in extractors.supported()


def test_adding_again_commits_an_add_whose_commit_failed(instance, tmp_path):
    import subprocess
    from kb.knowledge import catalog
    f = tmp_path / "note.md"
    f.write_text("# Note\n\nSome text.\n", encoding="utf-8")
    rec, created = catalog.add_file(f, commit=False)              # as if the commit had failed (a broken hook)
    git = lambda *x: subprocess.run(["git", "-C", str(instance), *x], capture_output=True, text=True).stdout
    assert created and f"raw/{rec['id']}" in git("status", "--porcelain", "-uall")
    again, created = catalog.add_file(f)
    assert not created and again["id"] == rec["id"]
    assert f"raw/{rec['id']}" not in git("status", "--porcelain", "-uall") and "committed on a later add" in git("log", "-1", "--format=%b")
