"""Pictures as sources (ADR-0022): kept for the model to look at, their text read by the laptop's OCR when it has one."""
import json
import os
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from kb.core.ports import TextRecognizer, Unavailable
from kb.extractors import for_path
from kb.extractors.base import segments
from kb.extractors.image import ImageExtractor


class FakeOcr(TextRecognizer):
    name = "fake"

    def __init__(self, text="", fail=None, off=None):
        self.text, self.fail, self.off, self.seen = text, fail, off, []

    def available(self):
        return (False, self.off) if self.off else (True, "fake")

    def recognize(self, image):
        self.seen.append(Path(image))
        if self.fail:
            raise Unavailable(self.fail)
        return self.text


def picture(path: Path, size=(400, 120), text="Crew rest 10 hours", **save) -> Path:
    im = Image.new("RGB", size, "white")
    ImageDraw.Draw(im).text((10, 40), text, fill="black")
    im.save(path, **save)
    return path


def test_a_picture_is_a_one_page_source_with_the_ocr_text(tmp_path):
    src = picture(tmp_path / "screen.png")
    ocr = FakeOcr("Crew rest 10 hours\nMinimum")
    r = ImageExtractor(ocr).extract(src, out_dir=tmp_path / "raw")
    assert dict(segments(r["text"])) == {"p. 1": "Crew rest 10 hours\nMinimum"}          # cited as p. 1
    fig = tmp_path / "raw" / "figures" / "p0001-01.png"
    assert fig.read_bytes() == src.read_bytes() and ocr.seen == [fig]                       # kept as it is, OCR on the figure
    assert r["meta"]["figures"] == [{"file": "figures/p0001-01.png", "page": 1}]
    assert r["meta"]["ocr"] == "fake" and "look at it in figures/" in r["meta"]["hint"]
    assert (r["meta"]["width"], r["meta"]["height"]) == (400, 120)


def test_without_ocr_or_text_a_note_says_why(tmp_path):
    src = picture(tmp_path / "board.jpg")
    r = ImageExtractor(FakeOcr(off="text recognition (OCR) needs Windows 10 or 11")).extract(src, out_dir=tmp_path)
    assert "No text was recognised in this picture: text recognition (OCR) needs Windows 10 or 11" in r["text"]
    assert r["meta"]["ocr"] == "none" and r["meta"]["ocr_problem"]
    r = ImageExtractor(FakeOcr(fail="the picture is larger than 2600 pixels")).extract(src, out_dir=tmp_path)
    assert "larger than 2600 pixels" in r["text"] and r["meta"]["ocr"] == "fake"
    r = ImageExtractor(FakeOcr("")).extract(src, out_dir=tmp_path)            # OCR ran, the picture has no text
    assert "(No text was recognised in this picture. Look at the picture itself.)" in r["text"] and "ocr_problem" not in r["meta"]


def test_bmp_and_tiff_become_png_and_large_pictures_are_scaled(tmp_path):
    for name in ("scan.bmp", "scan.tiff"):
        out = tmp_path / name
        r = ImageExtractor(FakeOcr("x")).extract(picture(tmp_path / ("src-" + name)), out_dir=out)
        assert r["meta"]["figures"][0]["file"] == "figures/p0001-01.png"
        with Image.open(out / "figures" / "p0001-01.png") as im:
            assert im.format == "PNG"
    x = ImageExtractor(FakeOcr("x")); x.max_side = 100
    x.extract(picture(tmp_path / "big.jpg", size=(1000, 300)), out_dir=tmp_path / "big")
    with Image.open(tmp_path / "big" / "figures" / "p0001-01.jpg") as im:
        assert max(im.size) == 100 and im.format == "JPEG"


def test_a_photo_taken_sideways_is_turned_upright(tmp_path):
    exif = Image.Exif(); exif[0x0112] = 6                     # "rotate 90° clockwise to view"
    src = picture(tmp_path / "phone.jpg", size=(400, 120), exif=exif)
    ImageExtractor(FakeOcr("x")).extract(src, out_dir=tmp_path / "o")
    with Image.open(tmp_path / "o" / "figures" / "p0001-01.jpg") as im:
        assert im.size == (120, 400)


def test_every_picture_type_has_the_image_reader():
    for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"):
        assert isinstance(for_path(Path("a" + ext.upper())), ImageExtractor), ext


def test_the_platform_says_why_there_is_no_ocr(monkeypatch):
    from kb import platform
    platform.recognizer.cache_clear()
    monkeypatch.setattr(os, "name", "posix")
    try:
        ok, why = platform.recognizer().available()
        assert not ok and "Windows" in why
        with pytest.raises(Unavailable):
            platform.recognizer().recognize(Path("x.png"))
        assert platform.status()["ocr"] == {"ok": False, "detail": why}
    finally:
        platform.recognizer.cache_clear()


def test_the_ingest_prompt_carries_the_extractors_hint(instance, tmp_path, monkeypatch):
    """The format is explained by its extractor, not guessed by the ingest from the file name."""
    from kb.extractors import image
    from kb.knowledge import catalog, wiki
    from scripted_agent import ScriptedAgent
    monkeypatch.setattr(image.ImageExtractor, "ocr", property(lambda self: FakeOcr("Rest 10 h")))
    rec, _ = catalog.add_file(picture(tmp_path / "whiteboard.png"))
    info = json.loads((instance / "raw" / rec["id"] / "extract.json").read_text(encoding="utf-8"))
    assert info["extractor"] == "ImageExtractor" and rec["kind"] == "image" and rec["status"] == "extracted"
    agent = ScriptedAgent()
    wiki.ingest_pending([rec["id"]], runner=agent)
    assert "This source is a picture" in agent.prompts[0] and "figures/" in agent.prompts[0]


@pytest.mark.skipif(os.name != "nt", reason="the Windows text recognition")
def test_windows_ocr_reads_a_picture(tmp_path):
    """On a real Windows: the OCR script works from Python (skipped where Windows has no OCR language)."""
    from PIL import ImageFont
    from kb.platform.windows.ocr import WindowsOcr
    im = Image.new("RGB", (900, 200), "white")
    try:
        font = ImageFont.truetype("arial.ttf", 48)
    except OSError:
        pytest.skip("no Arial font")
    ImageDraw.Draw(im).text((20, 50), "Crew rest 10 hours", fill="black", font=font)
    im.save(tmp_path / "ocr.png")
    try:
        text = WindowsOcr().recognize(tmp_path / "ocr.png")
    except Unavailable as e:
        pytest.skip(f"no Windows OCR here: {e}")
    assert "rest" in text.lower()
