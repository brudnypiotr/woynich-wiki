"""kb tray: the supervisor restarts kb serve after an update, stops on Quit or an error; a second start finds the app."""
import http.server
import json
import sys
import threading

import pytest

from kb.publish import appgit, tray, updater


@pytest.fixture
def local(tmp_path, monkeypatch):
    d = tmp_path / "local"; (d / "logs").mkdir(parents=True)
    monkeypatch.setattr(appgit, "local", lambda: d)
    monkeypatch.setattr(appgit, "root", lambda: tmp_path)
    monkeypatch.delenv("KB_INSTANCE", raising=False)
    return d


def fake_serve(tmp_path, codes):
    """A kb serve stand-in: prints the address like kb serve (the same one after a restart), exits with the next code."""
    n = tmp_path / "runs"
    script = (f"import pathlib, sys; f = pathlib.Path({str(n)!r}); i = int(f.read_text()) if f.exists() else 0; "
              f"f.write_text(str(i + 1)); print('woynich-wiki is running at http://127.0.0.1:8765/?t=tok', flush=True); "
              f"sys.exit({codes!r}[i])")
    return [sys.executable, "-c", script], n


def test_restarts_after_an_update_then_stops(tmp_path, local):
    cmd, runs = fake_serve(tmp_path, [updater.RESTART_CODE, 0])  # the same address after the restart: running again
    finish = [sys.executable, "-c", f"open({str(tmp_path / 'finished')!r}, 'w').write('1')"]
    states = []
    sup = tray.Supervisor(command=cmd, finish=finish, on_state=lambda s, d: states.append(s))
    assert sup.run() == 0
    assert runs.read_text() == "2" and (tmp_path / "finished").exists()
    assert states == ["starting", "running", "updating", "starting", "running", "stopped"]
    assert "kb serve exited with 3" in (local / "logs" / "tray.log").read_text()


def test_an_update_that_needs_the_setup_hands_over_to_the_launcher(tmp_path, local):
    """setup/version.txt changed with the update: the tray starts Wiki.cmd (which runs the setup) and stops."""
    (tmp_path / "setup").mkdir()
    (tmp_path / "setup" / "version.txt").write_text("3\n")
    (local / "setup-version.txt").write_text("2")
    cmd, runs = fake_serve(tmp_path, [updater.RESTART_CODE, 0])
    started = []
    sup = tray.Supervisor(command=cmd, finish=[sys.executable, "-c", "pass"], relaunch=lambda: started.append(1))
    assert sup.run() == 0 and started == [1] and runs.read_text() == "1"      # not started again here
    (local / "setup-version.txt").write_text("3")
    assert not updater.setup_needed()


def test_an_error_stops_and_says_so(tmp_path, local):
    cmd, runs = fake_serve(tmp_path, [1])
    states = []
    sup = tray.Supervisor(command=cmd, finish=["false"], on_state=lambda s, d: states.append((s, d)))
    assert sup.run() == 1 and runs.read_text() == "1"
    assert states[-1] == ("error", "the app stopped with an error (1)")


def test_second_start_finds_the_running_app(tmp_path, local, instance):
    assert tray.running_url() is None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), http.server.SimpleHTTPRequestHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/?t=abc"
        (instance / ".cache").mkdir(parents=True, exist_ok=True)
        (instance / ".cache" / "serve.json").write_text(json.dumps({"url": url}))  # as kb serve writes it
        assert tray.running_url() == url
    finally:
        srv.shutdown()
    assert tray.running_url() is None  # written, but gone: start a new one

def test_child_runs_this_copy_with_the_launcher_flag(local):
    cmd = tray.kb_command("serve")
    assert cmd[-1] == "serve" and "from kb.cli import main" in cmd[2]
    assert tray.Supervisor(command=["x"])._env()["KB_LAUNCHER"] == "1"


def test_one_lock_per_resource(tmp_path):
    from kb.core import singleton
    a, b = singleton.Lock(tmp_path / "x.lock"), singleton.Lock(tmp_path / "x.lock")
    assert a.acquire() and not b.acquire()   # a second holder is refused at once, no waiting
    a.release()
    assert b.acquire()
    b.release()


def test_double_start_gives_one_app(tmp_path, monkeypatch):
    """Regression: two starts 0.3 s apart (a quick double double-click) ran two kb serve on one knowledge base."""
    import time
    monkeypatch.setenv("KB_INSTANCE", str(tmp_path / "kb"))
    cmd = tray.kb_command("serve", "--no-browser", "--port", "0", "--adapter", "fake")
    first, second = tray.Supervisor(command=cmd), tray.Supervisor(command=cmd)
    t1 = threading.Thread(target=first.run, daemon=True); t1.start()
    time.sleep(0.3)
    t2 = threading.Thread(target=second.run, daemon=True); t2.start()
    t2.join(60)   # without the lock the second kb serve would just run: fail, don't hang
    if t2.is_alive():
        second.quit(); first.quit()
        pytest.fail("a second kb serve started on the same knowledge base")
    assert second.code == tray.ALREADY_RUNNING   # refused: the first one has it
    for _ in range(120):
        if first.url:
            break
        time.sleep(0.5)
    assert first.url and second.url is None
    first.quit(); t1.join(30)
    assert first.code == 0


def test_the_icon_is_named_after_the_knowledge_base(monkeypatch):
    from kb.core import config
    from kb.publish import branding
    monkeypatch.setattr(branding, "app_name", lambda: "Wiki")
    title = {"t": "Sales"}
    monkeypatch.setattr(config, "load", lambda name: {"instance": {"title": title["t"]}})
    url = "http://127.0.0.1:8766/?t=secret-token"
    assert tray.tooltip("running", url) == "Wiki Sales · port 8766" and "secret" not in tray.tooltip("running", url)
    assert tray.tooltip("starting", None) == "Wiki Sales: starting…"
    title["t"] = "Wiki Orders"            # no "Wiki Wiki Orders"
    assert tray.label() == "Wiki Orders"
    title["t"] = ""
    assert tray.label(url) == "Wiki · port 8766"
    title["t"] = "A very long knowledge base title that goes on and on and on"
    assert len(tray.tooltip("running", url)) <= 63
