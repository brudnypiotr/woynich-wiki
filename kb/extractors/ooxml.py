"""Word (.docx) and Excel (.xlsx, .xlsm), read with the standard library (both are zip files of XML).

Word: the body in document order, paragraphs and tables (a table becomes one Markdown table), headings with their
level (from the style's name or outline level, so localised styles like "Nagłówek 1" work too), list items, tabs and
line breaks; then footnotes, endnotes and reviewers' comments; pictures are saved to figures/. Deleted text of tracked
changes is left out. One ¶ marker per paragraph or table.

Excel: every sheet, every row as one ¶: `Sheet "Rates", row 12: Client = A | Rest = 12 h`, with the column names from
the sheet's first row when it is a header row; dates as dates (Excel stores them as numbers), formulas as their last
computed value. Very large sheets are cut, with a note saying so.
"""
from __future__ import annotations

import posixpath
import re
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

from kb.core.ports import Extractor
from kb.extractors.base import paragraphs_to_md

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")


def _xml(z: zipfile.ZipFile, name: str):
    try:
        return ET.fromstring(z.read(name))
    except KeyError:
        return None


def _kids(el) -> list:
    return list(el) if el is not None else []


# ------------------------------------------------------------------------------------------------------------- Word

class DocxExtractor(Extractor):
    extensions = (".docx",)
    max_images = 60

    def extract(self, path: Path, out_dir: Path | None = None) -> dict:
        self.tables = 0
        with zipfile.ZipFile(path) as z:
            doc = _xml(z, "word/document.xml")
            if doc is None:
                raise ValueError("not a Word document (word/document.xml is missing)")
            self.levels = self._heading_levels(_xml(z, "word/styles.xml"))
            paras: list[str] = []
            body = doc.find(f"{W}body")
            for el in _kids(body):
                self._block(el, paras)
            for part, title in (("word/footnotes.xml", "Footnotes"), ("word/endnotes.xml", "Endnotes")):
                notes = [self._text(n) for n in _kids(_xml(z, part)) if n.get(f"{W}id") not in ("-1", "0")]
                notes = [n for n in notes if n.strip()]
                if notes:
                    paras += [f"## {title}"] + [f"[{i}] {n}" for i, n in enumerate(notes, 1)]
            comments = [(c.get(f"{W}author") or "?", self._text(c)) for c in _kids(_xml(z, "word/comments.xml"))]
            comments = [(a, t) for a, t in comments if t.strip()]
            if comments:
                paras += ["## Reviewers' comments"] + [f"{a}: {t}" for a, t in comments]
            figures = self._images(z, out_dir) if out_dir is not None else []
        # no "title" in meta: the file name stays the title (docProps titles are often "Document1" or a template's)
        return {"text": paragraphs_to_md(paras), "meta": {"figures": figures, "tables": self.tables}}

    def _heading_levels(self, styles) -> dict[str, int]:
        """styleId → heading level (1–6); 0 for the Title style. Word keeps English names ("heading 1") in styles.xml
        even in localised Word, but custom styles may only carry an outline level."""
        out: dict[str, int] = {}
        self.list_styles: set[str] = set()
        for st in _kids(styles):
            sid = st.get(f"{W}styleId") or ""
            name = (st.find(f"{W}name").get(f"{W}val") if st.find(f"{W}name") is not None else "").lower()
            if st.find(f"{W}pPr/{W}numPr") is not None or name.startswith(("list bullet", "list number", "list paragraph")):
                self.list_styles.add(sid)  # Word often numbers through the style, not the paragraph
            lvl = st.find(f"{W}pPr/{W}outlineLvl")
            if m := re.match(r"(heading|nagłówek|überschrift|titre)\s*(\d)", name):
                out[sid] = int(m[2])
            elif name == "title":
                out[sid] = 0
            elif lvl is not None and lvl.get(f"{W}val", "9").isdigit() and int(lvl.get(f"{W}val")) < 6:
                out[sid] = int(lvl.get(f"{W}val")) + 1
        return out

    def _text(self, el) -> str:
        """Visible text of an element: runs, tabs, line breaks; not deleted text of tracked changes."""
        out = []
        for node in el.iter():
            tag = node.tag
            if tag == f"{W}t":
                out.append(node.text or "")
            elif tag == f"{W}tab":
                out.append(" ")
            elif tag in (f"{W}br", f"{W}cr"):
                out.append("\n")
            elif tag == f"{W}p" and out and not out[-1].endswith("\n"):
                out.append("\n")  # several paragraphs inside a cell, a note or a comment
        return re.sub(r"\n{2,}", "\n", "".join(out)).strip()

    def _block(self, el, paras: list[str]) -> None:
        if el.tag == f"{W}p":
            txt = self._text(el)
            if not txt:
                return
            ppr = el.find(f"{W}pPr")
            style = ppr.find(f"{W}pStyle").get(f"{W}val") if ppr is not None and ppr.find(f"{W}pStyle") is not None else ""
            lvl = ppr.find(f"{W}outlineLvl") if ppr is not None else None
            level = self.levels.get(style)
            if level is None and lvl is not None and lvl.get(f"{W}val", "9").isdigit() and int(lvl.get(f"{W}val")) < 6:
                level = int(lvl.get(f"{W}val")) + 1
            if level is not None:
                paras.append("#" * max(1, level) + " " + txt.replace("\n", " "))
            elif style in self.list_styles or (ppr is not None and ppr.find(f"{W}numPr") is not None):
                paras.append("- " + txt)
            else:
                paras.append(txt)
        elif el.tag == f"{W}tbl":
            rows = [[self._text(c).replace("\n", "<br>").replace("|", "\\|") for c in tr.findall(f"{W}tc")]
                    for tr in el.findall(f"{W}tr")]
            rows = [r for r in rows if any(c.strip() for c in r)]
            if not rows:
                return
            self.tables += 1
            width = max(len(r) for r in rows)
            rows = [r + [""] * (width - len(r)) for r in rows]
            md = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width] + ["| " + " | ".join(r) + " |" for r in rows[1:]]
            paras.append("\n".join(md))
        elif el.tag == f"{W}sdt":  # content controls (e.g. a table of contents or a form field): their content
            content = el.find(f"{W}sdtContent")
            for child in _kids(content):
                self._block(child, paras)

    def _images(self, z: zipfile.ZipFile, out_dir: Path) -> list[dict]:
        names = [n for n in z.namelist() if n.startswith("word/media/") and n.lower().endswith(IMAGE_EXT)]
        if not names:
            return []
        figs = Path(out_dir) / "figures"
        figs.mkdir(parents=True, exist_ok=True)
        out = []
        for i, n in enumerate(sorted(names)[: self.max_images], 1):
            dest = figs / f"img-{i:03d}{Path(n).suffix.lower()}"
            dest.write_bytes(z.read(n))
            out.append({"file": f"figures/{dest.name}", "from": n})
        return out



# ------------------------------------------------------------------------------------------------------------ Excel

BUILTIN_DATE_FORMATS = set(range(14, 23)) | {45, 46, 47}
EPOCH = datetime(1899, 12, 30)  # Excel's day 0 (with the 1900 leap-year bug folded in)


def _col(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


class XlsxExtractor(Extractor):
    extensions = (".xlsx", ".xlsm")
    max_rows = 5000       # per sheet; more rows are cut, with a note
    max_cells = 200_000   # per workbook

    def extract(self, path: Path) -> dict:
        with zipfile.ZipFile(path) as z:
            shared = self._shared(z)
            dates = self._date_styles(z)
            book = _xml(z, "xl/workbook.xml")
            if book is None:
                raise ValueError("not an Excel workbook (xl/workbook.xml is missing)")
            rels = {r.get("Id"): r.get("Target") for r in _kids(_xml(z, "xl/_rels/workbook.xml.rels"))}
            paras, cells, sheets, cut = [], 0, [], []
            for sh in book.iter(f"{S}sheet"):
                name, state = sh.get("name") or "Sheet", sh.get("state") or "visible"
                target = rels.get(sh.get(f"{R}id"), "")
                part = posixpath.normpath(target.lstrip("/") if target.startswith("/") else "xl/" + target)
                rows = self._rows(z, part, shared, dates)
                sheets.append(name)
                paras.append(f"## Sheet \"{name}\"" + (" (hidden)" if state != "visible" else "")
                             + ("" if rows else " (empty)"))
                if not rows:
                    continue
                header = rows[0][1] if len(rows) > 1 and all(isinstance(v, str) and v.strip() for v in rows[0][1].values()) \
                    and len(rows[0][1]) >= 2 else None
                if header:
                    paras.append(f"Columns: {' | '.join(header[c] for c in sorted(header))}")
                body = rows[1:] if header else rows
                for i, (rnum, vals) in enumerate(body):
                    if i >= self.max_rows or cells >= self.max_cells:
                        cut.append(name)
                        paras.append(f"(The sheet has {len(body)} rows; only the first {i} are included here.)")
                        break
                    cells += len(vals)
                    parts = [f"{header.get(c, _letters(c)) if header else _letters(c)} = {v}" for c, v in sorted(vals.items())]
                    paras.append(f"Sheet \"{name}\", row {rnum}: " + " | ".join(parts))
        return {"text": paragraphs_to_md(paras), "meta": {"sheets": sheets, "cut_sheets": cut, "cells": cells}}

    @staticmethod
    def _shared(z) -> list[str]:
        sst = _xml(z, "xl/sharedStrings.xml")
        return ["".join(t.text or "" for t in si.iter(f"{S}t")) for si in _kids(sst)]

    @staticmethod
    def _date_styles(z) -> set[int]:
        """Indexes of cell styles (the `s` attribute) whose number format is a date or time."""
        st = _xml(z, "xl/styles.xml")
        if st is None:
            return set()
        custom = {int(f.get("numFmtId")): f.get("formatCode", "") for f in st.iter(f"{S}numFmt")}
        is_date = lambda fid: fid in BUILTIN_DATE_FORMATS or (  # noqa: E731
            fid in custom and re.search(r"[dmyhs]", re.sub(r'"[^"]*"|\[[^\]]*\]|\\.', "", custom[fid]).lower()) is not None)
        xfs = st.find(f"{S}cellXfs")
        return {i for i, xf in enumerate(_kids(xfs)) if is_date(int(xf.get("numFmtId", "0")))}

    @staticmethod
    def _value(c, shared, dates):
        t, v = c.get("t"), c.find(f"{S}v")
        if t == "inlineStr":
            return "".join(x.text or "" for x in c.iter(f"{S}t"))
        if v is None or v.text is None:
            return None
        raw = v.text
        if t == "s":
            return shared[int(raw)] if raw.isdigit() and int(raw) < len(shared) else raw
        if t == "b":
            return "TRUE" if raw == "1" else "FALSE"
        if t in ("str", "e"):
            return raw
        try:
            num = float(raw)
        except ValueError:
            return raw
        if int(c.get("s", "0")) in dates and 0 <= num < 2958466:
            d = EPOCH + timedelta(days=num)
            return d.strftime("%Y-%m-%d") if num == int(num) else d.strftime("%Y-%m-%d %H:%M") if num >= 1 else d.strftime("%H:%M")
        return str(int(num)) if num == int(num) and abs(num) < 1e15 else f"{num:.10g}"

    def _rows(self, z, part, shared, dates) -> list[tuple[int, dict[int, str]]]:
        sheet = _xml(z, part)
        if sheet is None:
            return []
        out = []
        for row in sheet.iter(f"{S}row"):
            vals = {}
            for i, c in enumerate(row.findall(f"{S}c")):
                val = self._value(c, shared, dates)
                if val is None or not str(val).strip():
                    continue
                vals[_col(c.get("r")) if c.get("r") else i] = str(val).replace("\n", " ").strip()
            if vals:
                out.append((int(row.get("r") or len(out) + 1), vals))
        return out


def _letters(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s
