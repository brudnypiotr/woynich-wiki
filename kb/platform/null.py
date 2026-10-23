"""Null Objects for services this laptop does not have: available() says why, the work raises Unavailable."""
from __future__ import annotations

from pathlib import Path

from kb.core.ports import DocumentConverter, TextRecognizer, Unavailable


class MissingRecognizer(TextRecognizer):
    name = "none"

    def __init__(self, why: str):
        self.why = why

    def available(self) -> tuple[bool, str]:
        return False, self.why

    def recognize(self, image: Path) -> str:
        raise Unavailable(self.why)


class MissingConverter(DocumentConverter):
    def __init__(self, why: str):
        self.why = why

    def available(self) -> tuple[bool, str]:
        return False, self.why

    def convert(self, src: Path, dest: Path) -> Path:
        raise Unavailable(self.why)
