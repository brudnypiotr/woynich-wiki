import json

import pytest

from kb.llm.gateway import BudgetExceeded, Gateway

CFG = {"default_adapter": "fake", "adapters": {"fake": {"module": "kb.llm.adapters:FakeAdapter", "reply": '{"ok": 1}'}},
       "tiers": {"basic": {"model": "m-basic"}, "standard": {"model": "m-std"}},
       "tasks": {"classify": "basic"}, "prices": {"m-basic": {"input": 1.0, "output": 2.0}}, "budget": {"max_tokens_per_run": 50}}


def test_routing_and_metering(tmp_path):
    log = tmp_path / "metering.jsonl"
    gw = Gateway(cfg=CFG, log_path=log)
    r = gw.run("classify", "x" * 40, source_id="abc")
    assert r.model == "m-basic"
    ev = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert ev["task"] == "classify" and ev["tier"] == "basic" and ev["ok"] and ev["tokens_in"] == 10 and ev["cost"] is not None
    assert gw.run("summarize", "y").model == "m-std"  # unknown task -> standard tier


def test_budget(tmp_path):
    gw = Gateway(cfg=CFG, log_path=tmp_path / "m.jsonl")
    with pytest.raises(BudgetExceeded):
        for _ in range(100):
            gw.run("classify", "z" * 200)


def test_model_override(tmp_path, monkeypatch):
    gw = Gateway(cfg={**CFG, "model_override": "one-model", "budget": {}}, log_path=tmp_path / "m.jsonl")
    assert gw.run("classify", "x").model == "one-model" and gw.run("summarize", "y").model == "one-model"
    monkeypatch.setenv("KB_MODEL", "env-model")
    assert gw.run("classify", "x").model == "env-model"
