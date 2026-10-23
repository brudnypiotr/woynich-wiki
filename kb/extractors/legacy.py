"""Office 97–2003 binary formats.

Excel (.xls) is read directly with xlrd (pure Python, no Office needed) and written as text exactly like .xlsx (see
sheets.py): every sheet, one ¶ per row with the column names, dates as dates, formulas as their last computed value.
"""
from __future__ import annotations

from pathlib import Path

from kb.core.ports import Extractor
from kb.extractors import sheets
from kb.extractors.sheets import Row, SheetText


class XlsExtractor(Extractor):
    extensions = (".xls",)
    max_rows = 5000       # per sheet, as for .xlsx
    max_cells = 200_000   # per workbook

    def extract(self, path: Path) -> dict:
        import xlrd  # only when an .xls is read
        book = xlrd.open_workbook(str(path), on_demand=True)
        try:
            out = SheetText(self.max_rows, self.max_cells)
            for i in range(book.nsheets):
                sh = book.sheet_by_index(i)
                out.add(sh.name, self._rows(sh, book.datemode == 1), hidden=sh.visibility != 0)
                book.unload_sheet(i)
            return out.result()
        finally:
            book.release_resources()

    @staticmethod
    def _value(cell, date1904: bool) -> str | None:
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

    def _rows(self, sh, date1904: bool) -> list[Row]:
        out = []
        for r in range(sh.nrows):
            vals = {}
            for c, cell in enumerate(sh.row(r)):
                val = self._value(cell, date1904)
                if val is not None and str(val).strip():
                    vals[c] = str(val).replace("\n", " ").strip()
            if vals:
                out.append((r + 1, vals))
        return out
