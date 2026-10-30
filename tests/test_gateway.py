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


def test_cli_npm_shim_runs_node(tmp_path, monkeypatch):
    from kb.llm import adapters
    shim = tmp_path / "copilot.CMD"
    shim.write_text('@ECHO off\r\nIF EXIST "%dp0%\\node.exe" (\r\n  SET "_prog=%dp0%\\node.exe"\r\n)\r\n'
                    'endLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & "%_prog%"  '
                    '"%dp0%\\node_modules\\@github\\copilot\\npm-loader.js" %*\r\n', encoding="utf-8")
    (tmp_path / "node.exe").write_text("")
    monkeypatch.setattr(adapters.shutil, "which", lambda c: str(shim) if c == "copilot" else None)
    argv = adapters.CopilotCLIAdapter().argv()
    assert argv[0].endswith("node.exe") and argv[1].replace("\\", "/").endswith("node_modules/@github/copilot/npm-loader.js")


def test_cli_parsing_final_message_and_tokens():
    from kb.llm.adapters import _final_text, _sum_tokens
    events = [{"type": "assistant.reasoning", "data": {"content": "**thinking**"}},
              {"type": "assistant.message", "data": {"content": '{"claims": []}'}},
              {"type": "assistant.reasoning_delta", "data": {"content": "x"}}]
    assert _final_text(events) == '{"claims": []}'
    u = {"modelMetrics": {"m": {"usage": {"inputTokens": 100, "outputTokens": 7}}},
         "agentMetrics": {"main": {"modelMetrics": {"m": {"usage": {"inputTokens": 100, "outputTokens": 7}}}}},
         "providerModelMetrics": [{"metrics": {"usage": {"inputTokens": 100, "outputTokens": 7}}}]}
    assert _sum_tokens(u) == (100, 7)


def test_find_copilot_cli_off_path(tmp_path, monkeypatch):
    """Installed but not on this process's PATH (winget after the app started, npm, VS Code's Copilot Chat): still found."""
    from kb.llm import adapters
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setattr(adapters, "_registry_path", lambda: str(tmp_path / "empty"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    assert adapters.find_copilot_cli(windows=True) is None
    vscode = tmp_path / "roaming" / "Code" / "User" / "globalStorage" / "github.copilot-chat" / "copilotCli" / "copilot.bat"
    vscode.parent.mkdir(parents=True)
    vscode.write_text("@echo off")
    assert adapters.find_copilot_cli(windows=True) == str(vscode)
    winget = tmp_path / "local" / "Microsoft" / "WinGet" / "Links" / "copilot.exe"
    winget.parent.mkdir(parents=True)
    winget.write_text("")
    assert adapters.find_copilot_cli(windows=True) == str(winget)          # winget first
    assert adapters.find_copilot_cli(windows=False) is None                # elsewhere: PATH only
