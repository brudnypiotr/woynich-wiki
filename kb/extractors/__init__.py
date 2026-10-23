"""Extractor selection by file name (Strategy). Extend via config/plugins.yaml `extractors:`."""
from __future__ import annotations

from pathlib import Path

from kb.core import config, registry
from kb.extractors.base import PlainText
from kb.extractors.legacy import XlsExtractor
from kb.extractors.office import CodeExtractor, EmailExtractor, HtmlExtractor, JiraJsonExtractor, JiraXmlExtractor, TranscriptExtractor
from kb.extractors.ooxml import DocxExtractor, PptxExtractor, XlsxExtractor
from kb.extractors.xmlfile import XmlExtractor
from kb.extractors.pdf import PdfExtractor

BUILTIN = [JiraXmlExtractor, JiraJsonExtractor, PdfExtractor, DocxExtractor, XlsxExtractor, XlsExtractor, PptxExtractor, HtmlExtractor, EmailExtractor, TranscriptExtractor, PlainText, XmlExtractor, CodeExtractor]


def supported() -> list[str]:
    """Every file ending that has an extractor (built in or a plugin), e.g. ".pdf", ".jira.json"."""
    extra = [registry.resolve(s) for s in (config.load("plugins").get("extractors") or {}).values()]
    return sorted({ext for cls in extra + BUILTIN for ext in cls.extensions})


def for_path(path: Path):
    name = path.name.lower()
    extra = [registry.resolve(s) for s in (config.load("plugins").get("extractors") or {}).values()]
    for cls in extra + BUILTIN:
        if any(name.endswith(ext) for ext in cls.extensions):
            return cls()
    return None
