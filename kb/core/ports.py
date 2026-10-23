"""Ports (hexagonal architecture): the core depends only on these interfaces; systems plug in as adapters."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


@dataclass
class FetchedItem:
    """What a connector hands to the core: bytes on disk plus metadata for a SourceRecord."""
    path: Path
    title: str
    kind: str
    ref: str
    url: str | None = None
    version: str | None = None
    mime: str | None = None
    meta: dict = field(default_factory=dict)


class Connector(ABC):
    """Lists and fetches items from one source system (folder, Jira, Git, Graph...)."""
    name: str = "connector"

    def __init__(self, **options):
        self.options = options

    @abstractmethod
    def list(self) -> Iterable[str]:
        """Return refs of available items."""

    @abstractmethod
    def fetch(self, ref: str, dest_dir: Path) -> FetchedItem:
        """Download one item into dest_dir."""


class Extractor(ABC):
    """Turns one original file into text.md with locator markers."""
    extensions: tuple[str, ...] = ()

    @abstractmethod
    def extract(self, path: Path) -> dict:
        """Return {'text': str, 'meta': dict}. Text must contain locator markers."""



class Unavailable(RuntimeError):
    """A platform service this laptop does not have (no Word, no OCR). The message says what is missing, for the user."""


class DocumentConverter(ABC):
    """Turns a file into another format with a program on this laptop (e.g. .doc → .docx with Word)."""

    @abstractmethod
    def available(self) -> tuple[bool, str]:
        """(usable, why): a cheap check, without starting the program."""

    @abstractmethod
    def convert(self, src: Path, dest: Path) -> Path:
        """Write `src` as `dest` (its suffix says the format) and return it; raise Unavailable when it cannot."""


class TextRecognizer(ABC):
    """Reads the text in a picture (OCR)."""
    name: str = "ocr"

    @abstractmethod
    def available(self) -> tuple[bool, str]:
        """(usable, why): a cheap check."""

    @abstractmethod
    def recognize(self, image: Path) -> str:
        """The text in the picture, lines separated by newlines ("" when there is none); raise Unavailable when it cannot."""

@dataclass
class LLMResult:
    text: str
    model: str
    tokens_in: int | None = None
    tokens_out: int | None = None
    raw: object = None


class LLM(ABC):
    """A model adapter. Source text is always data: adapters must run without tool access."""
    name: str = "llm"

    @abstractmethod
    def complete(self, prompt: str, model: str, attachments: list[Path] | None = None) -> LLMResult:
        ...


class SecretStore(ABC):
    @abstractmethod
    def get(self, name: str) -> str | None: ...

    @abstractmethod
    def set(self, name: str, value: str) -> None: ...

    def delete(self, name: str) -> None:
        raise NotImplementedError(f"{type(self).__name__} cannot delete secrets")


class Publisher(ABC):
    @abstractmethod
    def publish(self, instance: Path, out: Path) -> Path: ...
