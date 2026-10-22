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
