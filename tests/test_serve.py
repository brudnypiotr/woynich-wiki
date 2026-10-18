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
CFG = {"default_adapter": "s", "adapters": {"s": {"module": "scripted_llm:Scripted"}},
       "tiers": {"standard": {"model": "m"}, "basic": {"model": "m"}}, "tasks": {}}


@pytest.fixture
def app(instance):
    from scripted_agent import ScriptedAgent
    httpd = serve.make_server(0, gw=Gateway(cfg=CFG, log_path=instance / "catalog" / "metering.jsonl"))
    serve.Handler.runner = ScriptedAgent()
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", serve.Handler.token
    httpd.shutdown()


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
    for _ in range(100):
        job = call(base, token, f"/api/jobs/{job['id']}")
        if job["state"] != "running":
            break
        time.sleep(0.1)
    assert job["state"] == "done", job
    assert [s for s in serve.STEPS_AGENT if s in {l["step"] for l in job["log"]}] == serve.STEPS_AGENT
    s = call(base, token, "/api/sessions", json.dumps({"topic": "Minimum rest"}).encode())
    t = call(base, token, f"/api/sessions/{s['id']}/ask", json.dumps({"question": "minimum rest home base"}).encode())
    assert not t["not_found"] and "[[" in t["markdown"]
    assert call(base, token, f"/api/sessions/{s['id']}/save", b"")["saved"].startswith("wiki/answers/discussion-")
