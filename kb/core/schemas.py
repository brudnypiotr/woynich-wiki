"""Schema-first data contracts: every record crossing a stage boundary is validated."""
from __future__ import annotations

import json
from functools import lru_cache

import jsonschema

from kb.core import config


@lru_cache(maxsize=None)
def schema(name: str) -> dict:
    return json.loads((config.paths().schemas / f"{name}.json").read_text(encoding="utf-8"))


def validate(name: str, data: dict) -> None:
    jsonschema.validate(data, schema(name))


def errors(name: str, data: dict) -> list[str]:
    v = jsonschema.Draft202012Validator(schema(name))
    return [f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in v.iter_errors(data)]
