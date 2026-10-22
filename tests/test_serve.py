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


@pytest.mark.smoke
def test_static_app_files(app):
    base, token = app
    with urllib.request.urlopen(base + "/static/js/main.js") as r:  # the app's code needs no token
        assert r.headers["Content-Type"].startswith("text/javascript") and r.headers["Cache-Control"] == "no-store"
    for bad in ("/static/../serve.py", "/static/%2e%2e/serve.py", "/static/nope.js", "/static/index.html"):
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(base + bad)
        assert e.value.code == 404, bad
    with urllib.request.urlopen(f"{base}/?t={token}") as r:
        page = r.read().decode("utf-8")
    assert f'"access": "{token}"' in page and "__CONFIG__" not in page and "__TITLE__" not in page
    for path, hdr, code in (("/api/nope", {"X-KB-Token": token}, 404), ("/api/nope", {}, 403), ("/", {}, 403)):
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(urllib.request.Request(base + path, headers=hdr))
        assert e.value.code == code, path


def test_first_run_setup_flag(app):
    base, token = app
    assert call(base, token, "/api/setup")["done"] is False                      # fresh instance: the app opens the setup
    assert call(base, token, "/api/setup/done", b"{}")["done"] is True
    assert call(base, token, "/api/setup")["done"] is True                       # kept in instance/config/profile.yaml
    assert call(base, token, "/api/setup/reset", b"{}")["done"] is False
    assert call(base, token, "/api/settings")["model"]["recommended"] == "gpt-6-luna"


@pytest.mark.smoke
def test_about_and_diagnostics(app):
    base, token = app
    v = call(base, token, "/api/about")
    from kb import __version__
    assert v["version"] == __version__ and "commit" in v
    d = call(base, token, "/api/diagnostics")
    assert d["app"]["version"] == v["version"] and set(d["checks"]) == {"copilot", "jira"}
    keys = {k: v for k, v in d["secrets"].items() if k != "error"}  # "error": no secret store (Linux CI has no keyring)
    assert all(isinstance(x, bool) or x is None for x in keys.values())  # whether a key is set, never its value
    assert d["knowledge_base"]["sources"] == 0 and d["recent_errors"] == []


def test_update_state_and_changelog(app, monkeypatch):
    from kb.publish import updater
    monkeypatch.setattr(updater, "_LAST", None)
    monkeypatch.setattr(updater, "check", lambda fetch=True: {"available": True, "behind": 1, "incoming": [], "error": None})
    base, token = app
    assert call(base, token, "/api/update")["behind"] == 1
    log = call(base, token, "/api/changelog")
    assert log and all({"version", "date", "entries"} <= set(g) for g in log)


def test_update_waits_for_ingest(app, monkeypatch):
    from kb.publish import updater
    from kb.publish.server import ingest_api
    monkeypatch.setattr(updater, "apply", lambda: pytest.fail("must not update during an ingest"))
    monkeypatch.setattr(ingest_api, "QUEUE", ["job1", "job2"])
    base, token = app
    with pytest.raises(urllib.error.HTTPError) as e:
        call(base, token, "/api/update/apply", b"{}")
    assert e.value.code == 400 and "2 in the queue" in json.loads(e.value.read())["error"]


@pytest.mark.smoke
def test_upload_steps_then_discussion(app):
    base, token = app
    job = call(base, token, "/api/upload", SAMPLE.read_bytes(), {"X-Filename": SAMPLE.name})
    for _ in range(1200):  # up to 2 min: Windows with antivirus is slow
        job = call(base, token, f"/api/jobs/{job['id']}")
        if job["state"] not in ("queued", "running"):
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
    with pytest.raises(urllib.error.HTTPError) as e:
        call(base, token, f"/api/sessions/{s['id']}/stop", b"")   # nothing running
    assert e.value.code == 409
    assert call(base, token, f"/api/sessions/{s['id']}")["agent_session"] == "live-1"
    other = next(p for p in sorted(SAMPLE.parent.iterdir()) if p != SAMPLE)
    job = call(base, token, "/api/upload", other.read_bytes(), {"X-Filename": other.name})
    for _ in range(1200):  # up to 2 min: Windows with antivirus is slow
        if call(base, token, f"/api/jobs/{job['id']}")["state"] not in ("queued", "running"):
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
                                                       "profile": {"title": "Orders rules", "jira_base_url": "https://jira.example.com/",
                                                                   "jira_email": "me@example.com"}}).encode())
    assert s["model"] == {**s["model"], "effective": "gpt-6-luna", "source": "override", "timeout_s": 600}
    assert s["model"]["tiers"]["basic"] == "small-1" and s["profile"]["jira_base_url"] == "https://jira.example.com"
    assert call(base, token, "/api/status")["model"] == "gpt-6-luna"
    for bad in ({"jira_base_url": "https://jira.example.com", "jira_email": ""}, {"jira_base_url": "", "jira_email": "me@example.com"},
                {"jira_base_url": "https://jira.example.com", "jira_email": "not-an-email"}):
        with pytest.raises(urllib.error.HTTPError) as e:  # Jira URL and e-mail are required
            call(base, token, "/api/settings", json.dumps({"profile": bad}).encode())
        assert e.value.code == 400
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
    for bad in ([{"name": "inv server", "path": "x"}], [{"name": "a", "path": "x"}, {"name": "A", "path": "y"}], [{"name": "a", "path": ""}]):
        with pytest.raises(urllib.error.HTTPError) as e:
            call(base, token, "/api/settings", json.dumps({"repos": {"list": bad}}).encode())
        assert e.value.code == 400


def test_usage_ai_credits_and_cycle(instance):
    from datetime import datetime, timezone
    from kb.publish import settings

    class Inner:
        name = "copilot-sdk"
        def usage_quota(self):
            return {"tbb": True, "plan": "business", "snapshots": {
                "chat": {"entitlement": -1, "used": 0, "remaining_pct": 100, "unlimited": True, "reset_ms": None, "tbb": False},
                "ai_credits": {"entitlement": 1900, "used": 808, "remaining_pct": 57.47, "unlimited": False,
                               "reset_ms": datetime(2026, 11, 1, tzinfo=timezone.utc).timestamp() * 1000, "tbb": True}}}
    gw = type("G", (), {"llm": type("L", (), {"inner": Inner()})()})()
    met = instance / "catalog" / "metering.jsonl"
    met.parent.mkdir(parents=True, exist_ok=True)
    met.write_text('{"at": "2026-10-02T10:00:00+00:00", "credits": 3.5}\n{"at": "2026-09-30T10:00:00+00:00", "credits": 9}\n')
    u = settings.usage(gw, datetime(2026, 10, 19, 12, tzinfo=timezone.utc))
    assert (u["unit"], u["used"], u["entitlement"], u["plan"]) == ("AI credits", 808, 1900, "business")
    assert (u["days_left"], u["business_days_left"], u["kb_month"]) == (13, 10, 3.5)   # only this month counts
    assert u["reset"].startswith("2026-11-01")


def test_uploads_queue_one_by_one_and_can_leave_the_queue(app):
    base, token = app
    serve.WRITE_LOCK.acquire()            # pretend another ingest is running
    serve.QUEUE.insert(0, "busy")
    try:
        a = call(base, token, "/api/upload", b"first file text\n", {"X-Filename": "a.txt"})
        b = call(base, token, "/api/upload", b"second file text\n", {"X-Filename": "b.txt"})
        assert (a["state"], a["ahead"], b["ahead"]) == ("queued", 1, 2)
        assert call(base, token, "/api/status")["queued"] == 2
        call(base, token, f"/api/jobs/{b['id']}/cancel", b"{}")
        for _ in range(50):
            if call(base, token, f"/api/jobs/{b['id']}")["state"] == "cancelled":
                break
            time.sleep(0.1)
        assert call(base, token, f"/api/jobs/{b['id']}")["state"] == "cancelled"
    finally:
        serve.WRITE_LOCK.release()
        serve._done_turn({"id": "busy"})
    for _ in range(600):
        if call(base, token, f"/api/jobs/{a['id']}")["state"] not in ("queued", "running"):
            break
        time.sleep(0.1)
    assert call(base, token, f"/api/jobs/{a['id']}")["state"] == "done"


def test_sdk_noise_is_one_line(capsys):
    import asyncio
    from kb.llm.adapters import quiet_sdk_noise
    loop = asyncio.new_event_loop()
    ctx = {"exception": ValueError("'destroy' is not a valid ShutdownType"), "handle": "<Handle CopilotClient.handle_notification>"}
    quiet_sdk_noise(loop, ctx); quiet_sdk_noise(loop, ctx)
    loop.close()
    assert capsys.readouterr().out.count("does not know") == 1


def test_usage_estimate_adds_what_kb_used_since_the_reading(instance):
    from kb.publish import settings
    u = {"checked_at": "2026-10-19T12:00:00+00:00", "used": 808, "entitlement": 1900, "remaining_pct": 57.47,
         "unlimited": False, "kb_month": 3.5}
    met = instance / "catalog" / "metering.jsonl"
    met.parent.mkdir(parents=True, exist_ok=True)
    met.write_text('{"at": "2026-10-19T11:59:00+00:00", "credits": 5}\n{"at": "2026-10-19T12:01:00+00:00", "credits": 1.5}\n')
    e = settings.usage_estimate(u)
    assert (e["used"], e["since_check"], e["kb_month"]) == (809.5, 1.5, 5.0) and round(e["remaining_pct"], 1) == 57.4


def test_dashboard_is_rebuilt_only_when_the_wiki_changes(instance, monkeypatch):
    from kb.knowledge import catalog
    from kb.publish import site
    catalog.init()
    calls = []
    real = site.collect_data
    monkeypatch.setattr(site, "collect_data", lambda: calls.append(1) or real())
    site.build(force=False); site.build(force=False)
    assert len(calls) == 1                                   # unchanged: last time's page
    (instance / "wiki").mkdir(exist_ok=True); (instance / "wiki" / "new.md").write_text("# New\n", encoding="utf-8")
    site.build(force=False)
    assert len(calls) == 2                                   # a new page: built again
    site.build()
    assert len(calls) == 3                                   # kb site and Rebuild always build


def test_tray_quit_and_restart(app, monkeypatch):
    from kb.publish import updater
    base, token = app
    monkeypatch.delenv("KB_LAUNCHER", raising=False)
    with pytest.raises(urllib.error.HTTPError):  # restart needs the launcher, else nothing would start the app again
        call(base, token, "/api/app/restart", b"{}")
    monkeypatch.setenv("KB_LAUNCHER", "1")
    assert call(base, token, "/api/app/restart", b"{}")["what"] == "restart" and updater.RESTART.is_set()
    updater.RESTART.clear()


def test_folder_upload_keeps_the_path(app, instance):
    """A file from a dropped folder: its path in the folder is the source's origin and the model is told the folder."""
    from kb.knowledge import catalog, wiki
    from kb.publish.server.ingest_api import clean_path
    base, token = app
    assert clean_path("..%2F..%2Fx%2Fb.docx") == "x/b.docx" and clean_path("C:\\Users\\a.pdf") == "C_/Users/a.pdf"
    assert "pdf" in " ".join(call(base, token, "/api/upload/types")["extensions"])
    job = call(base, token, "/api/upload", b"Minimum rest is 12 hours.\n",
               {"X-Filename": "rest.txt", "X-Path": "Client%20A%2FSpecs%2F2024%2Frest.txt", "X-Batch": "b1"})
    assert job["path"] == "Client A/Specs/2024/rest.txt" and job["batch"] == "b1"
    for _ in range(1200):
        job = call(base, token, f"/api/jobs/{job['id']}")
        if job["state"] not in ("queued", "running"):
            break
        time.sleep(0.1)
    rec = catalog.load(job["source_id"])
    assert rec["origin"]["ref"] == "Client A/Specs/2024/rest.txt" and rec["title"] == "rest"
    assert "Found in the folder: `Client A/Specs/2024/`" in wiki._extra(rec, instance / "raw" / rec["id"], 10)
    assert any(j["id"] == job["id"] for j in call(base, token, "/api/jobs"))


def test_sources_view_lists_quality_and_assesses_chosen_sources_again(app, instance):
    from kb.knowledge import catalog, wiki
    from scripted_agent import ScriptedAgent
    base, token = app
    for f in sorted(SAMPLE.parent.iterdir())[:2]:
        catalog.add_file(f)
    wiki.ingest_pending(runner=ScriptedAgent())
    q = call(base, token, "/api/sources/quality")
    assert len(q["sources"]) == 2 and q["run"] is None and set(q["prompts"]) == {"ingest", "backfill"}
    s = q["sources"][0]
    assert s["assessment"]["model_assessment"]["verdict"] == "useful" and s["assessment"]["prompt"] == q["prompts"]["ingest"]
    with pytest.raises(urllib.error.HTTPError) as e:
        call(base, token, "/api/sources/assess", json.dumps({"ids": []}).encode())
    assert e.value.code == 400

    def run(model):
        call(base, token, "/api/sources/assess", json.dumps({"ids": [s["id"]], "model": model}).encode())
        for _ in range(100):
            r = call(base, token, "/api/sources/quality")
            if r["run"]["state"] in ("done", "error", "cancelled"):
                return r
            time.sleep(0.1)
    r = run(False)                                          # measure again: the judgement made at ingest stays
    assert r["run"]["state"] == "done" and r["run"]["done"] == 1
    a = next(x for x in r["sources"] if x["id"] == s["id"])["assessment"]
    assert a["mode"] == "ingest" and a["model_assessment"]["verdict"] == "useful" and a.get("signals_updated")
    r = run(True)                                           # with the model: judged again with the current prompt
    a = next(x for x in r["sources"] if x["id"] == s["id"])["assessment"]
    assert a["mode"] == "backfill" and a["model_assessment"]["verdict"] == "core" and a["prompt"] == r["prompts"]["backfill"]


def test_an_assessment_prompt_of_the_knowledge_base_replaces_the_blueprints(instance):
    from kb.knowledge import agent, assess
    before = assess.prompt_version("backfill")
    (instance / "prompts").mkdir(parents=True, exist_ok=True)
    (instance / "prompts" / "assess.md").write_text("Own criteria for {{title}}.", encoding="utf-8")
    assert agent.prompt("assess", title="X") == "Own criteria for X." and assess.prompt_version("backfill") != before
