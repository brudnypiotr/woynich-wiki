"""Services of the laptop the app runs on (ADR-0022): Office to convert old formats, the Windows text recognition.

Extractors ask this factory; on Windows they get the Windows adapters, elsewhere (or when a service is missing) a Null
Object that says why, so an extraction fails or degrades with a clear message instead of a crash. Tests replace
`recognizer`/`converter` with fakes.
"""
from __future__ import annotations

import os
from functools import lru_cache

from kb.core.ports import DocumentConverter, TextRecognizer
from kb.platform.null import MissingRecognizer


@lru_cache(maxsize=None)
def recognizer() -> TextRecognizer:
    if os.name != "nt":
        return MissingRecognizer("text recognition (OCR) needs Windows 10 or 11")
    from kb.platform.windows.ocr import WindowsOcr
    return WindowsOcr()


def status() -> dict:
    """What this laptop offers, for diagnostics: cheap checks only, no program is started."""
    out = {}
    for name, svc in (("ocr", recognizer()),):
        ok, why = svc.available()
        out[name] = {"ok": ok, "detail": why}
    return out


__all__ = ["recognizer", "status", "DocumentConverter", "TextRecognizer"]
