"""Feedback: Luna asks at most two rounds of questions, then writes a report; the package goes to the Desktop."""
import json
import zipfile

from kb.knowledge import catalog
from kb.llm.gateway import Gateway
from kb.publish import feedback


def gw(reply, tmp_path):
    cfg = {"default_adapter": "fake", "adapters": {"fake": {"module": "kb.llm.adapters:FakeAdapter", "reply": reply}},
           "tiers": {"standard": {"model": "m"}, "basic": {"model": "m"}}, "tasks": {}}
    return Gateway(cfg=cfg, log_path=tmp_path / "metering.jsonl")


ASKING = json.dumps({"done": False, "message": "Which screen were you on?", "report": None})


def test_luna_asks_then_must_finish(tmp_path, instance):
    g = gw(ASKING, tmp_path)
    msgs = [{"role": "user", "text": "Update does nothing"}]
    r = feedback.converse(g, msgs)
    assert not r["done"] and r["message"] == "Which screen were you on?" and r["rounds_left"] == 1
    msgs += [{"role": "assistant", "text": r["message"]}, {"role": "user", "text": "About"},
             {"role": "assistant", "text": "And then?"}, {"role": "user", "text": "nothing happened"}]
    r = feedback.converse(g, msgs)            # two answers given: she may not ask again
    assert r["done"] and r["report"] and r["rounds_left"] == 0


def test_report_from_json_and_plain_text_replies(tmp_path, instance):
    rep = {"title": "Update button silent", "kind": "bug", "what_happened": "no reaction", "where": "About"}
    r = feedback.converse(gw("Sure!\n" + json.dumps({"done": True, "message": "Thanks", "report": rep}), tmp_path),
                          [{"role": "user", "text": "x"}])
    assert r["done"] and r["report"]["title"] == "Update button silent" and r["report"]["expected"] == ""
    r = feedback.converse(gw("What did you expect?", tmp_path), [{"role": "user", "text": "x"}])
    assert not r["done"] and r["message"] == "What did you expect?"


def test_package_on_the_desktop(tmp_path, instance, monkeypatch):
    catalog.init()
    (instance / "wiki" / "index.md").write_text("# Index\n", encoding="utf-8")
    (instance / "sessions").mkdir(exist_ok=True); (instance / "sessions" / "s1.json").write_text('{"topic": "rest"}')
    monkeypatch.setattr(feedback, "desktop", lambda: tmp_path)
    png = "data:image/png;base64,iVBORw0KGgo="
    r = feedback.package("It broke", {"title": "Broken", "kind": "bug"}, [{"role": "user", "text": "It broke"}], [png])
    names = zipfile.ZipFile(r["path"]).namelist()
    assert r["path"].startswith(str(tmp_path)) and "wiki-feedback-" in r["path"]
    for n in ("feedback.md", "feedback.json", "diagnostics.json", "screenshots/1.png", "instance/wiki/index.md",
              "instance/sessions/s1.json", "instance/sources.json", "instance/git-log.txt"):
        assert n in names, n
    assert "# Broken" in zipfile.ZipFile(r["path"]).read("feedback.md").decode()
