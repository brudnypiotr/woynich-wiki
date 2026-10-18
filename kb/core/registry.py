"""Plugin registry: config/plugins.yaml maps kind -> name -> 'module:Class'. Adding a plugin needs no core change."""
from __future__ import annotations

import importlib

from kb.core import config


def resolve(spec: str):
    module, _, attr = spec.partition(":")
    if not attr:
        raise ValueError(f"plugin spec must be 'module:Class', got {spec!r}")
    return getattr(importlib.import_module(module), attr)


def available(kind: str, plugins: dict | None = None) -> dict[str, str]:
    plugins = plugins if plugins is not None else config.load("plugins")
    return dict(plugins.get(kind) or {})


def create(kind: str, name: str, plugins: dict | None = None, **options):
    specs = available(kind, plugins)
    if name not in specs:
        raise KeyError(f"no {kind[:-1]} named {name!r}; known: {sorted(specs)}")
    return resolve(specs[name])(**options)
