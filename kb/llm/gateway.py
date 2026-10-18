"""LLM gateway: routes a task to a model tier and wraps every call with the cost meter (decorator) and budget."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from kb.core import config, registry
from kb.core.ports import LLM, LLMResult


class BudgetExceeded(RuntimeError):
    pass


class Metered(LLM):
    """Decorator: records every call (task, model, tokens, cost, time) to metering.jsonl and enforces a token budget."""

    def __init__(self, inner: LLM, log_path: Path, prices: dict, max_tokens: int | None = None):
        self.inner, self.log_path, self.prices, self.max_tokens = inner, Path(log_path), prices, max_tokens
        self.name = inner.name
        self.used = 0

    def complete(self, prompt, model, attachments=None, *, task="adhoc", tier=None, stage=None, source_id=None, response_schema=None):
        if self.max_tokens is not None and self.used >= self.max_tokens:
            raise BudgetExceeded(f"token budget of {self.max_tokens} reached")
        t0 = time.perf_counter(); err = None; res: LLMResult | None = None
        try:
            res = (self.inner.complete(prompt, model, attachments, response_schema=response_schema)
                   if response_schema else self.inner.complete(prompt, model, attachments))
            return res
        except Exception as e:
            err = f"{type(e).__name__}: {e}"[:300]
            raise
        finally:
            tin = res.tokens_in if res else None
            tout = res.tokens_out if res else None
            self.used += (tin or 0) + (tout or 0)
            price = self.prices.get(model) or {}
            cost = None
            if tin is not None and tout is not None and (price.get("input") or price.get("output")):
                cost = round(tin / 1e6 * price.get("input", 0) + tout / 1e6 * price.get("output", 0), 6)
            ev = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "task": task, "stage": stage,
                  "source_id": source_id, "adapter": self.inner.name, "model": model, "tier": tier,
                  "tokens_in": tin, "tokens_out": tout, "cost": cost,
                  "duration_s": round(time.perf_counter() - t0, 3), "ok": err is None, "error": err}
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")


class Gateway:
    """One entry point for all model calls: `gateway.run(task, prompt)`."""

    def __init__(self, cfg: dict | None = None, adapter: str | None = None, log_path: Path | None = None):
        self.cfg = cfg if cfg is not None else config.load("models")
        name = adapter or self.cfg.get("default_adapter", "fake")
        spec = dict(self.cfg["adapters"][name])
        inner = registry.resolve(spec.pop("module"))(**spec)
        self.llm = Metered(inner, log_path or config.paths().metering, self.cfg.get("prices", {}),
                           (self.cfg.get("budget") or {}).get("max_tokens_per_run"))

    def model_for(self, task: str) -> tuple[str, str]:
        tier = (self.cfg.get("tasks") or {}).get(task, "standard")
        return tier, self.cfg["tiers"][tier]["model"]

    def run(self, task: str, prompt: str, attachments=None, **meta) -> LLMResult:
        tier, model = self.model_for(task)
        return self.llm.complete(prompt, model, attachments, task=task, tier=tier, **meta)
