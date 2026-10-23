"""Spreadsheets as text, the same for every file format (.xlsx, .xlsm, .xls).

Each reader only reads cells (as strings, by row number and column index); SheetText turns them into text.md: a
heading per sheet, the column names when the first row is a header, then one ¶ per row:
`Sheet "Rates", row 12: Client = A | Rest = 12 h`. Very large sheets are cut, with a note saying so.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from kb.extractors.base import paragraphs_to_md

Row = tuple[int, dict[int, str]]   # (row number as shown in Excel, {column index from 0: value})
EPOCH_1900 = datetime(1899, 12, 30)  # Excel's day 0 (with the 1900 leap-year bug folded in)
EPOCH_1904 = datetime(1904, 1, 1)    # workbooks made on old Macs


def number(num: float) -> str:
    """A cell's number as Excel shows it without formatting: 12, not 12.0."""
    return str(int(num)) if num == int(num) and abs(num) < 1e15 else f"{num:.10g}"


def date(serial: float, date1904: bool = False) -> str | None:
    """A date cell (Excel stores days since its epoch): a date, a date with time, or a time; None if out of range."""
    if not 0 <= serial < 2958466:
        return None
    d = (EPOCH_1904 if date1904 else EPOCH_1900) + timedelta(days=serial)
    return d.strftime("%Y-%m-%d") if serial == int(serial) else d.strftime("%Y-%m-%d %H:%M") if serial >= 1 else d.strftime("%H:%M")


def letters(i: int) -> str:
    """Column index from 0 → Excel's letters: 0 → A, 26 → AA."""
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


class SheetText:
    """Builder: add() the sheets in workbook order, then result() gives {"text", "meta"} for an extractor."""

    def __init__(self, max_rows: int = 5000, max_cells: int = 200_000):
        self.max_rows, self.max_cells = max_rows, max_cells
        self.paras: list[str] = []
        self.sheets: list[str] = []
        self.cut: list[str] = []
        self.cells = 0

    def add(self, name: str, rows: list[Row], hidden: bool = False) -> None:
        self.sheets.append(name)
        self.paras.append(f"## Sheet \"{name}\"" + (" (hidden)" if hidden else "") + ("" if rows else " (empty)"))
        if not rows:
            return
        header = rows[0][1] if len(rows) > 1 and len(rows[0][1]) >= 2 and all(v.strip() for v in rows[0][1].values()) else None
        if header:
            self.paras.append(f"Columns: {' | '.join(header[c] for c in sorted(header))}")
        body = rows[1:] if header else rows
        for i, (rnum, vals) in enumerate(body):
            if i >= self.max_rows or self.cells >= self.max_cells:
                self.cut.append(name)
                self.paras.append(f"(The sheet has {len(body)} rows; only the first {i} are included here.)")
                break
            self.cells += len(vals)
            parts = [f"{header.get(c, letters(c)) if header else letters(c)} = {v}" for c, v in sorted(vals.items())]
            self.paras.append(f"Sheet \"{name}\", row {rnum}: " + " | ".join(parts))

    def result(self) -> dict:
        return {"text": paragraphs_to_md(self.paras), "meta": {"sheets": self.sheets, "cut_sheets": self.cut, "cells": self.cells}}
