"""Scripted model for end-to-end tests: answers each prompt type deterministically from the prompt itself."""
from __future__ import annotations

import json
import re

from kb.core.ports import LLM, LLMResult


class Scripted(LLM):
    name = "scripted"

    def __init__(self, **_):
        pass

    def complete(self, prompt, model, attachments=None, response_schema=None):
        return LLMResult(text=json.dumps(self.reply(prompt)), model="scripted", tokens_in=len(prompt) // 4, tokens_out=20)

    def reply(self, p: str) -> dict:
        if "Extract up to" in p:
            body = p.split("SOURCE:\n", 1)[1]
            claims = []
            for loc, txt in re.findall(r"^\[([^\]]+)\]\n(.+?)(?=\n\n\[|\Z)", body, flags=re.S | re.M):
                words = " ".join(txt.split()).split(" ")
                if len(words) >= 6:
                    claims.append({"text": " ".join(words[:12]), "locator": loc, "quote": " ".join(words[:10])})
            claims.append({"text": "Invented fact", "locator": "p. 1", "quote": "this sentence is not in the source at all"})
            return {"claims": claims}
        if "numbered facts from the document" in p:
            n = [int(x) for x in re.findall(r"^\[(\d+)\]", p, flags=re.M)]
            return {"summary": [{"sentence": "Summary sentence.", "claims": n[:1]}],
                    "topics": [{"slug": "minimum-rest", "title": "Minimum rest", "claims": n}]}
        if "Write a synopsis" in p:
            return {"sentences": [{"sentence": "Synopsis sentence.", "claims": [1]}, {"sentence": "Bad ref.", "claims": [999]}]}
        if "Find contradictions" in p:
            a = [int(n) for n, t in re.findall(r"^\[(\d+)\] (.*)$", p, flags=re.M) if "12 hours" in t]
            b = [int(n) for n, t in re.findall(r"^\[(\d+)\] (.*)$", p, flags=re.M) if "10 hours" in t]
            return {"conflicts": [{"claims": [a[0], b[0]], "explanation": "12 hours vs 10 hours"}] if a and b else []}
        if "Answer the QUESTION" in p:
            return {"answer": [{"sentence": "Answer sentence.", "evidence": [1]}], "not_found": False}
        if "List 3 to 8 search terms" in p:
            return {"terms": ["MIN_REST_HOME_BASE_HOURS", "xx"]}
        if "Explain how the code" in p:
            return {"answer": [{"sentence": "Code sentence.", "snippets": [1]}], "not_found": False}
        return {}
