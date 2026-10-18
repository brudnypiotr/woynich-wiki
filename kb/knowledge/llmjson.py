"""Ask the model for JSON that matches a strict schema; parse and validate defensively (weak model)."""
from __future__ import annotations

import json
import re
import unicodedata

import jsonschema


def strict(schema: dict) -> dict:
    """Make a schema 'strict' for structured output: additionalProperties=false and all properties required."""
    if schema.get("type") == "object":
        props = schema.get("properties", {})
        schema = {**schema, "additionalProperties": False, "required": list(props),
                  "properties": {k: strict(v) for k, v in props.items()}}
    elif schema.get("type") == "array" and "items" in schema:
        schema = {**schema, "items": strict(schema["items"])}
    return schema


def parse(text: str):
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.strip("`").split("\n", 1)[-1].rsplit("```", 1)[0]
    s, e = t.find("{"), t.rfind("}")
    if s < 0 or e < 0:
        raise ValueError("no JSON object in model output")
    return json.loads(t[s:e + 1])


def ask(gateway, task: str, prompt: str, schema: dict, retries: int = 1, **meta):
    """Call the model with a strict schema; on invalid output retry once with the error appended."""
    sch = strict(schema)
    last = None
    for attempt in range(retries + 1):
        p = prompt if attempt == 0 else prompt + f"\n\nYour previous answer was invalid ({last}). Return only valid JSON matching the schema."
        res = gateway.run(task, p, response_schema=sch, **meta)
        try:
            data = parse(res.text)
            jsonschema.validate(data, sch)
            return data
        except Exception as e:
            last = f"{type(e).__name__}: {str(e)[:200]}"
    raise ValueError(f"model did not return valid JSON for {task}: {last}")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-").replace("­", "")
    s = re.sub(r"-\s*\n\s*", "", s)  # hyphenation across lines
    return re.sub(r"\s+", " ", s).strip().lower()


def quote_in(quote: str, text: str) -> bool:
    q = norm(quote)
    return len(q) >= 8 and q in norm(text)
