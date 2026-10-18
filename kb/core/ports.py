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


class Publisher(ABC):
    @abstractmethod
    def publish(self, instance: Path, out: Path) -> Path: ...
