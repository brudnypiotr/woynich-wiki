"""Configuration (12-factor): YAML files under config/, overridable per instance and by KB_* environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

BLUEPRINT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Paths:
    root: Path          # blueprint checkout
    instance: Path      # instance data (raw/, catalog/, wiki/, queue/, ...)

    @property
    def config(self) -> Path:
        return self.root / "config"

    @property
    def schemas(self) -> Path:
        return self.root / "schemas"

    @property
    def catalog(self) -> Path:
        return self.instance / "catalog"

    @property
    def metering(self) -> Path:
        return self.catalog / "metering.jsonl"

    @property
    def reports(self) -> Path:
        return self.instance / "reports"


def paths() -> Paths:
    root = Path(os.environ.get("KB_ROOT", BLUEPRINT_ROOT))
    instance = Path(os.environ.get("KB_INSTANCE", root / "instance"))
    return Paths(root=root, instance=instance)


def load(name: str, p: Paths | None = None) -> dict:
    """Load config/<name>.yaml; an instance copy (instance/config/<name>.yaml) overrides key by key."""
    p = p or paths()
    data: dict = {}
    for f in (p.config / f"{name}.yaml", p.instance / "config" / f"{name}.yaml"):
        if f.exists():
            data = _merge(data, yaml.safe_load(f.read_text(encoding="utf-8")) or {})
    return data


def _merge(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out
