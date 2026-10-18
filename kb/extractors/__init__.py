"""Extractor selection by file name (Strategy). Extend via config/plugins.yaml `extractors:`."""
from __future__ import annotations

from pathlib import Path

from kb.core import config, registry
from kb.extractors.base import PlainText
from kb.extractors.office import (CodeExtractor, DocxExtractor, EmailExtractor, HtmlExtractor, JiraJsonExtractor,
                                  TranscriptExtractor)
from kb.extractors.pdf import PdfExtractor

BUILTIN = [JiraJsonExtractor, PdfExtractor, DocxExtractor, HtmlExtractor, EmailExtractor, TranscriptExtractor, PlainText, CodeExtractor]


def for_path(path: Path):
    name = path.name.lower()
    extra = [registry.resolve(s) for s in (config.load("plugins").get("extractors") or {}).values()]
    for cls in extra + BUILTIN:
        if any(name.endswith(ext) for ext in cls.extensions):
            return cls()
    return None
