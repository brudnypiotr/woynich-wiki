"""Pictures as sources: screenshots, photos of whiteboards, scanned pages, diagrams.

A picture is a one-page source: it is kept in figures/ for the model to look at (BMP and TIFF converted to PNG, very
large pictures scaled down, photos turned upright), and text.md holds `<!-- p. 1 -->` with the text the laptop's OCR
recognised, so the text can be searched and cited as `p. 1`. Without OCR (or when the picture has no text) a note says
so, and the model reads the picture itself.
"""
from __future__ import annotations

from pathlib import Path

from kb.core.ports import Extractor, TextRecognizer, Unavailable
from kb.extractors.base import marker

VIEWABLE = (".png", ".jpg", ".jpeg", ".gif", ".webp")   # what the model can look at as it is
HINT = ("This source is a picture (a screenshot, photo or diagram): look at it in figures/; the text under p. 1 is what "
        "OCR recognised, which may miss or misread words. Describe what it shows and cite it as p. 1.")


class ImageExtractor(Extractor):
    extensions = VIEWABLE + (".bmp", ".tif", ".tiff")
    max_side = 4000   # pixels; larger pictures are scaled down for the model

    def __init__(self, ocr: TextRecognizer | None = None):
        self._ocr = ocr

    @property
    def ocr(self) -> TextRecognizer:
        if self._ocr is None:
            from kb import platform
            self._ocr = platform.recognizer()
        return self._ocr

    def extract(self, path: Path, out_dir: Path | None = None) -> dict:
        from PIL import Image
        with Image.open(path) as im:
            frames, size = getattr(im, "n_frames", 1), im.size
            figure = self._figure(im, path, Path(out_dir)) if out_dir is not None else None
        text, ocr, problem = self._recognize(figure or path)
        body = text.strip() or f"(No text was recognised in this picture{': ' + problem if problem else ''}. Look at the picture itself.)"
        if frames > 1:
            body += f"\n\n(The file has {frames} frames or pages; only the first is shown.)"
        meta = {"width": size[0], "height": size[1], "ocr": ocr, "hint": HINT,
                "figures": [{"file": f"figures/{figure.name}", "page": 1}] if figure else []}
        if problem:
            meta["ocr_problem"] = problem
        if frames > 1:
            meta["frames"] = frames
        return {"text": f"{marker('p.', 1)}\n{body}\n", "meta": meta}

    def _figure(self, im, path: Path, out_dir: Path) -> Path:
        """Save the picture the model will look at: the file itself when it can, else upright, scaled down, as PNG
        (JPEG stays JPEG)."""
        from PIL import ImageOps
        figs = out_dir / "figures"
        figs.mkdir(parents=True, exist_ok=True)
        suffix = path.suffix.lower()
        upright = im.getexif().get(0x0112, 1) == 1          # EXIF orientation: photos from phones are often turned
        if suffix in VIEWABLE and upright and max(im.size) <= self.max_side:
            dest = figs / f"p0001-01{suffix}"
            dest.write_bytes(path.read_bytes())
            return dest
        im = ImageOps.exif_transpose(im)
        im.thumbnail((self.max_side, self.max_side))
        if suffix in (".jpg", ".jpeg"):
            dest = figs / f"p0001-01{suffix}"
            im.convert("RGB").save(dest, quality=90)
        else:
            dest = figs / "p0001-01.png"
            (im if im.mode in ("1", "L", "LA", "P", "RGB", "RGBA", "I;16") else im.convert("RGBA")).save(dest)
        return dest

    def _recognize(self, image: Path) -> tuple[str, str, str | None]:
        """(text, which OCR, problem): the recognised text, or "" with why there is none."""
        ok, why = self.ocr.available()
        if not ok:
            return "", "none", why
        try:
            return self.ocr.recognize(image), self.ocr.name, None
        except Unavailable as e:
            return "", self.ocr.name, str(e)
