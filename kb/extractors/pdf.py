"""PDF extractor (permissive licences, ADR-0009): pypdfium2 for text and images, pdfplumber for tables.

Every page gets a `<!-- p. N -->` marker. Tables are appended per page as Markdown. Embedded images (screenshots,
figures) are saved as files with their page number, so answers can show "where to click" with a citation.
Per-page quality metrics flag pages without a text layer (scans need OCR, not part of the MVP).
"""
from __future__ import annotations

from pathlib import Path

from kb.core.ports import Extractor
from kb.extractors.base import marker

MIN_CHARS_PER_PAGE = 40


class PdfExtractor(Extractor):
    extensions = (".pdf",)

    def __init__(self, tables: bool = True, images: bool = True, max_images: int = 200, **_):
        self.tables, self.images, self.max_images = tables, images, max_images

    def extract(self, path: Path, out_dir: Path | None = None) -> dict:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(str(path))
        pages, quality, figures = [], [], []
        tables_by_page = self._tables(path) if self.tables else {}
        for i in range(len(pdf)):
            page = pdf[i]
            text = page.get_textpage().get_text_range().replace("\r\n", "\n").replace("\r", "\n").strip()
            n = i + 1
            parts = [marker("p.", n), text]
            for t in tables_by_page.get(n, []):
                parts += ["", t]
            pages.append("\n".join(parts))
            quality.append({"page": n, "chars": len(text), "tables": len(tables_by_page.get(n, [])),
                            "needs_ocr": len(text) < MIN_CHARS_PER_PAGE})
            if self.images and out_dir is not None and len(figures) < self.max_images:
                figures += self._images(page, n, out_dir, self.max_images - len(figures))
        meta = {"pages": len(pdf), "quality": quality, "figures": figures,
                "pages_needing_ocr": [q["page"] for q in quality if q["needs_ocr"]]}
        return {"text": "\n\n".join(pages) + "\n", "meta": meta}

    @staticmethod
    def _tables(path: Path) -> dict[int, list[str]]:
        try:
            import pdfplumber
        except ImportError:
            return {}
        out: dict[int, list[str]] = {}
        try:
            with pdfplumber.open(str(path)) as doc:
                for n, page in enumerate(doc.pages, 1):
                    for table in page.extract_tables() or []:
                        rows = [[(c or "").replace("\n", " ").strip() for c in row] for row in table if row]
                        if len(rows) < 2 or not any(any(c for c in r) for r in rows):
                            continue
                        width = max(len(r) for r in rows)
                        rows = [r + [""] * (width - len(r)) for r in rows]
                        md = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width] + ["| " + " | ".join(r) + " |" for r in rows[1:]]
                        out.setdefault(n, []).append("\n".join(md))
        except Exception:
            return out
        return out

    @staticmethod
    def _images(page, n: int, out_dir: Path, limit: int) -> list[dict]:
        import pypdfium2.raw as pdfium_c
        figs = []
        try:
            objs = list(page.get_objects(filter=(pdfium_c.FPDF_PAGEOBJ_IMAGE,), max_depth=2))
        except Exception:
            return figs
        fig_dir = out_dir / "figures"
        for k, obj in enumerate(objs[:limit], 1):
            try:
                img = obj.get_bitmap(render=False).to_pil()
                if img.width < 80 or img.height < 80:
                    continue  # icons, bullets
                fig_dir.mkdir(parents=True, exist_ok=True)
                name = f"p{n:04d}-{k:02d}.png"
                img.save(fig_dir / name)
                figs.append({"file": f"figures/{name}", "page": n, "width": img.width, "height": img.height})
            except Exception:
                continue
        return figs
