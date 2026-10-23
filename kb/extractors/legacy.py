"""Office 97–2003 formats.

Excel (.xls): a file named .xls is one of four things, and Excel opens all of them, so the reader looks at the content,
not the name (one small reader per kind, chosen by the first bytes):
  - a real Excel 97–2003 workbook (BIFF in an OLE2 container), read with xlrd (pure Python, no Office needed);
  - "XML Spreadsheet 2003" (SpreadsheetML), what many systems export as .xls;
  - an HTML table saved as .xls (another common export);
  - an .xlsx renamed to .xls.
Each reader only reads cells; sheets.SheetText writes the text exactly like .xlsx: every sheet, one ¶ per row with the
column names, dates as dates, formulas as their last computed value.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

from kb.core.ports import Extractor
from kb.extractors import sheets
from kb.extractors.sheets import Row, SheetText

OLE2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
SS = "{urn:schemas-microsoft-com:office:spreadsheet}"
Sheet = tuple[str, list[Row], bool]   # (name, rows, hidden)


class XlsExtractor(Extractor):
    extensions = (".xls",)
    max_rows = 5000       # per sheet, as for .xlsx
    max_cells = 200_000   # per workbook

    def extract(self, path: Path) -> dict:
        with open(path, "rb") as f:
            head = f.read(4096)
        if head.startswith(b"PK"):                       # an .xlsx with the wrong name
            from kb.extractors.ooxml import XlsxExtractor
            x = XlsxExtractor(); x.max_rows, x.max_cells = self.max_rows, self.max_cells
            return _with(x.extract(path), "xlsx")
        if head.startswith(OLE2):
            found, kind = _biff(path), "biff"
        else:
            text = _decode(head).lstrip("﻿ \t\r\n").lower()
            if "urn:schemas-microsoft-com:office:spreadsheet" in text or text.startswith("<?xml"):
                found, kind = _spreadsheetml(path), "spreadsheetml"
            elif "<table" in text or "<html" in text or "<!doctype html" in text:
                found, kind = _html(path), "html"
            else:
                raise ValueError("not an Excel file: neither an Excel 97-2003 workbook, nor XML Spreadsheet 2003, nor an HTML table")
        out = SheetText(self.max_rows, self.max_cells)
        for name, rows, hidden in found:
            out.add(name, rows, hidden=hidden)
        return _with(out.result(), kind)


def _with(result: dict, kind: str) -> dict:
    result["meta"]["format"] = kind   # what the .xls really was, for diagnostics
    return result


def _decode(data: bytes) -> str:
    """Text of an export: UTF-16 when it says so (BOM), else UTF-8, else Windows' own code page."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _cell(v: str | None) -> str | None:
    v = re.sub(r"\s+", " ", v or "").strip()
    return v or None


# ------------------------------------------------------------------ Excel 97–2003 (BIFF), with xlrd

def _biff(path: Path) -> list[Sheet]:
    import xlrd  # only when such a file is read
    book = xlrd.open_workbook(str(path), on_demand=True)
    try:
        out = []
        for i in range(book.nsheets):
            sh = book.sheet_by_index(i)
            out.append((sh.name, _biff_rows(sh, book.datemode == 1), sh.visibility != 0))
            book.unload_sheet(i)
        return out
    finally:
        book.release_resources()


def _biff_value(cell, date1904: bool) -> str | None:
    import xlrd
    t, v = cell.ctype, cell.value
    if t in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
        return None
    if t == xlrd.XL_CELL_TEXT:
        return v
    if t == xlrd.XL_CELL_BOOLEAN:
        return "TRUE" if v else "FALSE"
    if t == xlrd.XL_CELL_ERROR:
        return xlrd.error_text_from_code.get(v, "#ERROR")
    if t == xlrd.XL_CELL_DATE:
        return sheets.date(v, date1904) or sheets.number(v)
    return sheets.number(v)


def _biff_rows(sh, date1904: bool) -> list[Row]:
    out = []
    for r in range(sh.nrows):
        vals = {c: v for c, cell in enumerate(sh.row(r)) if (v := _cell(_biff_value(cell, date1904)))}
        if vals:
            out.append((r + 1, vals))
    return out


# ------------------------------------------------------------------ XML Spreadsheet 2003 (SpreadsheetML)

def _spreadsheetml(path: Path) -> list[Sheet]:
    root = ET.parse(path).getroot()
    if root.tag != f"{SS}Workbook":
        raise ValueError("an XML file, but not an Excel XML Spreadsheet 2003 (no ss:Workbook)")
    out = []
    for ws in root.iter(f"{SS}Worksheet"):
        opts = ws.find("{urn:schemas-microsoft-com:office:excel}WorksheetOptions")
        vis = opts.findtext("{urn:schemas-microsoft-com:office:excel}Visible") if opts is not None else None
        rows, r = [], 0
        for row in ws.iter(f"{SS}Row"):
            r = int(row.get(f"{SS}Index") or r + 1)       # ss:Index skips empty rows and cells
            vals, c = {}, -1
            for cell in row.findall(f"{SS}Cell"):
                c = int(cell.get(f"{SS}Index")) - 1 if cell.get(f"{SS}Index") else c + 1
                data = cell.find(f"{SS}Data")
                if data is not None and (v := _cell(_ss_value(data))):
                    vals[c] = v
            if vals:
                rows.append((r, vals))
        out.append((ws.get(f"{SS}Name") or f"Sheet{len(out) + 1}", rows, vis in ("SheetHidden", "SheetVeryHidden")))
    return out


def _ss_value(data) -> str:
    t, text = data.get(f"{SS}Type"), "".join(data.itertext())
    if t == "Number":
        try:
            return sheets.number(float(text))
        except ValueError:
            return text
    if t == "Boolean":
        return "TRUE" if text.strip() == "1" else "FALSE"
    if t == "DateTime":                                   # 2024-01-01T00:00:00.000
        day, _, time = text.partition("T")
        return day if time[:5] in ("", "00:00") else f"{day} {time[:5]}"
    return text


# ------------------------------------------------------------------ an HTML table saved as .xls

class _Tables(HTMLParser):
    """Every <table> as rows of cell texts; colspan keeps the columns of the following cells in place."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self.row, self.cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.tables.append([])
        elif tag == "tr" and self.tables:
            self.row = []; self.tables[-1].append(self.row)
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []; self.row.append((self.cell, int(dict(attrs).get("colspan") or 1)))
        elif tag == "br" and self.cell is not None:
            self.cell.append(" ")

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            self.cell = None
        elif tag == "tr":
            self.row = self.cell = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)


def _html(path: Path) -> list[Sheet]:
    p = _Tables()
    p.feed(_decode(path.read_bytes()))
    out = []
    for n, table in enumerate(p.tables, 1):
        rows = []
        for r, cells in enumerate(table, 1):
            vals, c = {}, 0
            for parts, span in cells:
                if v := _cell("".join(parts)):
                    vals[c] = v
                c += max(span, 1)
            if vals:
                rows.append((r, vals))
        if rows:
            out.append((f"Table {n}" if len(p.tables) > 1 else "Sheet1", rows, False))
    if not out:
        raise ValueError("an HTML file without a table with data")
    return out
