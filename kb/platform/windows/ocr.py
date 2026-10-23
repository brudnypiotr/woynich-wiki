"""The Windows text recognition (Windows.Media.Ocr) through ocr.ps1: offline, in the user's Windows languages."""
from __future__ import annotations

import platform
import tempfile
from pathlib import Path

from kb.core.ports import TextRecognizer
from kb.platform.windows import powershell

MAX_SIDE = 2500  # below OcrEngine.MaxImageDimension on every Windows 10/11


class WindowsOcr(TextRecognizer):
    name = "windows"

    def available(self) -> tuple[bool, str]:
        if platform.release() not in ("10", "11"):
            return False, f"text recognition needs Windows 10 or 11 (this is Windows {platform.release()})"
        return True, "Windows text recognition (languages are checked on first use)"

    def recognize(self, image: Path) -> str:
        from PIL import Image
        with Image.open(image) as im:
            if max(im.size) <= MAX_SIDE:
                return powershell.run("ocr.ps1", str(image))["text"]
            with tempfile.TemporaryDirectory() as tmp:
                small = Path(tmp) / "ocr.png"
                im.thumbnail((MAX_SIDE, MAX_SIDE))
                im.save(small)
                return powershell.run("ocr.ps1", str(small))["text"]
