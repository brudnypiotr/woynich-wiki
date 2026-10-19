"""Local web app: token required, upload runs the ingest steps, discussion sessions answer with citations."""
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from kb.llm.gateway import Gateway
from kb.publish import serve

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "sources" / "example-air-om-a-ch7.pdf"
CFG = {"default_adapter": "fake", "adapters": {"fake": {"module": "kb.llm.adapters:FakeAdapter"}},
       "tiers": {"standard": {"model": "m"}, "basic": {"model": "m"}}, "tasks": {}}


@pytest.fixture
def app(instance):
    from scripted_agent import ScriptedAgent
    httpd = serve.make_server(0, gw=Gateway(cfg=CFG, log_path=instance / "catalog" / "metering.jsonl"))
    serve.Handler.runner = ScriptedAgent()
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", serve.Handler.token
    httpd.shutdown()
    serve.close_live()


def call(base, token, path, data=None, headers=None):
    req = urllib.request.Request(base + path, data=data, headers={"X-KB-Token": token, **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def test_token_required(app):
    base, _ = app
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(base + "/api/status")
    assert e.value.code == 403


def test_upload_steps_then_discussion(app):
    base, token = app
    job = call(base, token, "/api/upload", SAMPLE.read_bytes(), {"X-Filename": SAMPLE.name})
    for _ in range(1200):  # up to 2 min: Windows with antivirus is slow
        job = call(base, token, f"/api/jobs/{job['id']}")
        if job["state"] != "running":
            break
        time.sleep(0.1)
    assert job["state"] == "done", job
    assert [s for s in serve.STEPS if s in {l["step"] for l in job["log"]}] == serve.STEPS
    s = call(base, token, "/api/sessions", json.dumps({"topic": "Minimum rest"}).encode())
    t = call(base, token, f"/api/sessions/{s['id']}/ask", json.dumps({"question": "minimum rest home base"}).encode())
    assert not t["not_found"] and "[[" in t["markdown"] and t["session"] == "new"
    assert t["check"]["ok"] >= 1 and not t["check"]["broken"]                    # citations checked on the server
    assert [e["kind"] for e in t["trace"]][:2] == ["thinking", "read"]             # what the model did
    pr = call(base, token, f"/api/sessions/{s['id']}/progress")
    assert pr["running"] is False and pr["total"] == len(t["trace"])
    t = call(base, token, f"/api/sessions/{s['id']}/ask", json.dumps({"question": "minimum rest again"}).encode())
    runner = serve.Handler.runner
    assert t["session"] == "continued" and runner.opened == ["live-1"]  # one long session (ADR-0019)
    assert call(base, token, f"/api/sessions/{s['id']}")["agent_session"] == "live-1"
    other = next(p for p in sorted(SAMPLE.parent.iterdir()) if p != SAMPLE)
    job = call(base, token, "/api/upload", other.read_bytes(), {"X-Filename": other.name})
    for _ in range(1200):  # up to 2 min: Windows with antivirus is slow
        if call(base, token, f"/api/jobs/{job['id']}")["state"] != "running":
            break
        time.sleep(0.1)
    call(base, token, f"/api/sessions/{s['id']}/ask", json.dumps({"question": "minimum rest now?"}).encode())
    assert "WIKI UPDATED" in runner.prompts[-1] and "wiki/sources/" in runner.prompts[-1]
    assert serve.close_live() == 1 and runner.closed == ["live-1"]
    t = call(base, token, f"/api/sessions/{s['id']}/ask", json.dumps({"question": "minimum rest after restart"}).encode())
    assert t["session"] == "resumed"
    call(base, token, "/api/settings", json.dumps({"profile": {"title": "Orders"}}).encode())  # e.g. Jira URL set later
    assert "agent_session" not in call(base, token, f"/api/sessions/{s['id']}")
    t = call(base, token, f"/api/sessions/{s['id']}/ask", json.dumps({"question": "minimum rest with new settings"}).encode())
    assert t["session"] == "new" and "EARLIER IN THIS CONVERSATION" in runner.prompts[-1]  # fresh tools, history kept
    assert call(base, token, f"/api/sessions/{s['id']}/save", b"")["saved"].startswith("wiki/answers/discussion-")
    assert call(base, token, f"/api/sessions/{s['id']}/delete", b"") == {"deleted": s["id"]}
    assert s["id"] not in [x["id"] for x in call(base, token, "/api/sessions")] and runner.closed[-1] == runner.opened[-1]
    with pytest.raises(urllib.error.HTTPError) as e:
        call(base, token, f"/api/sessions/{s['id']}/delete", b"")
    assert e.value.code == 404


def test_settings_models_profile_and_secrets(app, instance, monkeypatch):
    from kb.core.ports import SecretStore
    from kb.publish import settings

    class Mem(SecretStore):
        data: dict = {}
        def get(self, name): return self.data.get(name)
        def set(self, name, value): self.data[name] = value
        def delete(self, name): self.data.pop(name, None)
    monkeypatch.setattr(settings, "store", Mem)
    monkeypatch.delenv("KB_MODEL", raising=False)
    monkeypatch.delenv("COPILOT_GITHUB_TOKEN", raising=False)
    base, token = app
    s = call(base, token, "/api/settings", json.dumps({"model": {"override": "gpt-6-luna", "tiers": {"basic": "small-1"}, "timeout_s": 600},
                                                       "profile": {"title": "Orders rules", "jira_base_url": "https://jira.example.com/"}}).encode())
    assert s["model"] == {**s["model"], "effective": "gpt-6-luna", "source": "override", "timeout_s": 600}
    assert s["model"]["tiers"]["basic"] == "small-1" and s["profile"]["jira_base_url"] == "https://jira.example.com"
    assert call(base, token, "/api/status")["model"] == "gpt-6-luna"
    s = call(base, token, "/api/settings", json.dumps({"model": {"override": ""}}).encode())
    assert s["model"]["source"] == "tiers"
    with pytest.raises(urllib.error.HTTPError) as e:
        call(base, token, "/api/settings", json.dumps({"model": {"override": "x; rm -rf /"}}).encode())
    assert e.value.code == 400
    st = call(base, token, "/api/secrets/copilot-github-token", json.dumps({"value": "ghp_secret"}).encode())
    assert {"name": "copilot-github-token", "set": True}.items() <= st["items"][0].items()
    assert "ghp_secret" not in json.dumps(call(base, token, "/api/settings"))  # never sent back
    import os
    assert os.environ["COPILOT_GITHUB_TOKEN"] == "ghp_secret"
    st = call(base, token, "/api/secrets/confluence-token", json.dumps({"value": "c"}).encode())
    assert any(x["name"] == "confluence-token" and x["set"] for x in st["items"])
    st = call(base, token, "/api/secrets/copilot-github-token/delete", b"")
    assert not st["items"][0]["set"] and "COPILOT_GITHUB_TOKEN" not in os.environ


def test_second_server_gets_its_own_port(instance):
    import socket
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    gw = Gateway(cfg=CFG, log_path=instance / "catalog" / "metering.jsonl")
    a = serve.make_server(port, gw=gw)
    b = serve.make_server(port, gw=gw)
    try:
        assert a.server_address[1] == port and b.server_address[1] != port  # never two servers on one port
    finally:
        a.server_close(); b.server_close()


def test_settings_code_repos_roles_and_architecture(app, instance, tmp_path):
    from kb.knowledge import chat
    base, token = app
    server = tmp_path / "inv-server"; server.mkdir()
    body = {"repos": {"list": [{"name": "inv-server", "role": "backend server", "path": str(server), "description": "Java rules engine"},
                               {"name": "inv-web", "role": "frontend (UI)", "path": str(tmp_path / "missing"), "description": ""},
                               {"name": "", "path": ""}],
                      "architecture": "Angular frontend (inv-web) → REST → Java server (inv-server) → Oracle."}}
    s = call(base, token, "/api/settings", json.dumps(body).encode())
    repos = s["profile"]["code_repos"]
    assert [(r["name"], r["role"], r["exists"]) for r in repos] == [("inv-server", "backend server", True), ("inv-web", "frontend (UI)", False)]
    assert s["profile"]["architecture"].startswith("Angular frontend")
    ctx = chat._context(None, None, [], "wiki")
    assert "SYSTEM ARCHITECTURE" in ctx and "- inv-server (backend server):" in ctx and "Java rules engine" in ctx
    for bad in ([{"name": "cm server", "path": "x"}], [{"name": "a", "path": "x"}, {"name": "A", "path": "y"}], [{"name": "a", "path": ""}]):
        with pytest.raises(urllib.error.HTTPError) as e:
            call(base, token, "/api/settings", json.dumps({"repos": {"list": bad}}).encode())
        assert e.value.code == 400
