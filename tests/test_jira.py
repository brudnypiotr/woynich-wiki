"""Jira connector: XML issue view → text with citable markers, attachments, links, credentials. Fake HTTP, no Jira."""
import subprocess
from pathlib import Path

import pytest

from kb.connectors import jira
from kb.extractors.office import JiraXmlExtractor
from kb.knowledge import catalog

PDF = Path(__file__).resolve().parents[1] / "samples" / "sources" / "example-air-om-a-ch7.pdf"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def issue(key, links=""):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="0.92"><channel><title>Jira</title><item>
<title>[{key}] Minimum rest at home base is 10h instead of 12h</title>
<link>https://jira.example.com/browse/{key}</link>
<key id="1">{key}</key><summary>Minimum rest at home base is 10h instead of 12h</summary>
<type>Bug</type><priority>High</priority><status>Done</status><resolution>Fixed</resolution>
<assignee accountid="a">Anna</assignee><reporter accountid="b">Marek</reporter>
<created>Mon, 1 Sep 2026 10:00:00 +0000</created><updated>Tue, 2 Sep 2026 12:00:00 +0000</updated>
<fixVersion>2026.2.2</fixVersion><component>Rules</component><labels><label>orders</label></labels>
<description>&lt;p&gt;The rule uses &lt;b&gt;10&lt;/b&gt; hours.&lt;/p&gt;&lt;ul&gt;&lt;li&gt;OM-A says 12&lt;/li&gt;&lt;li&gt;fix in MinRest&lt;/li&gt;&lt;/ul&gt;
&lt;table&gt;&lt;tr&gt;&lt;th&gt;Base&lt;/th&gt;&lt;th&gt;Hours&lt;/th&gt;&lt;/tr&gt;&lt;tr&gt;&lt;td&gt;Home&lt;/td&gt;&lt;td&gt;12&lt;/td&gt;&lt;/tr&gt;&lt;/table&gt;</description>
<comments><comment id="10" author="anna" created="Mon, 1 Sep 2026 11:00:00 +0000">&lt;p&gt;Confirmed with the client.&lt;/p&gt;</comment>
<comment id="11" author="marek" created="Tue, 2 Sep 2026 09:00:00 +0000">Fixed in &lt;code&gt;MinRest.java&lt;/code&gt;.</comment></comments>
<issuelinks>{links}</issuelinks>
<attachments><attachment id="501" name="screen.png" size="72" author="anna" created="x"/>
<attachment id="502" name="om-a.pdf" size="3000" author="anna" created="x"/></attachments>
<customfields><customfield id="customfield_1" key="x"><customfieldname>Found in release</customfieldname>
<customfieldvalues><customfieldvalue>2026.2.1</customfieldvalue></customfieldvalues></customfield>
<customfield id="customfield_2" key="y"><customfieldname>Rank</customfieldname><customfieldvalues><customfieldvalue>0|i0</customfieldvalue></customfieldvalues></customfield>
</customfields></item></channel></rss>"""


LINKS = """<issuelinktype id="1"><name>Relates</name><outwardlinks description="relates to">
<issuelink><issuekey id="2">EXA-151</issuekey></issuelink></outwardlinks></issuelinktype>"""


@pytest.fixture
def fake(monkeypatch):
    calls = []

    def request(self, url, accept):
        calls.append(url)
        if "issue-xml/EXA-150/" in url:
            return issue("EXA-150", LINKS).encode(), "application/xml"
        if "issue-xml/EXA-151/" in url:
            return issue("EXA-151").encode(), "application/xml"
        if url.endswith("/501"):
            return PNG, "image/png"
        if url.endswith("/502"):
            return PDF.read_bytes(), "application/pdf"
        raise AssertionError(url)
    monkeypatch.setattr(jira.Jira, "_request", request)
    return calls


CFG = {"base_url": "https://example.atlassian.net", "email": "me@example.com", "token": "t"}


def test_xml_to_text_with_markers(tmp_path):
    p = tmp_path / "EXA-150.jira.xml"; p.write_text(issue("EXA-150", LINKS), encoding="utf-8")
    out = JiraXmlExtractor().extract(p)
    t = out["text"]
    assert out["meta"]["key"] == "EXA-150" and out["meta"]["title"].startswith("EXA-150: Minimum rest")
    assert "Status: Done" in t and "Fix versions: 2026.2.2" in t and "Links: relates to EXA-151" in t
    assert "- Found in release: 2026.2.1" in t and "Rank" not in t
    assert "<!-- #description -->\nThe rule uses 10 hours." in t and "- OM-A says 12" in t and "| Home | 12 |" in t
    assert "<!-- #c 2 -->\nmarek" in t and "[comment id 11]: Fixed in MinRest.java." in t
    assert "Attachments: screen.png (1 KB), om-a.pdf (2 KB)" in t


def test_add_registers_issue_figures_attachments_and_links(instance, fake):
    res = jira.add(["https://example.atlassian.net/browse/EXA-150"], links=True, **CFG)
    assert [r["record"]["key"] for r in res] == ["EXA-150", "EXA-151"]
    rec = res[0]["record"]
    assert rec["kind"] == "ticket" and rec["origin"]["url"].endswith("/browse/EXA-150") and res[0]["created"]
    d = instance / "raw" / rec["id"]
    assert (d / "original.jira.xml").exists() and (d / "figures" / "screen.png").exists()
    assert "#c 1" in (d / "text.md").read_text(encoding="utf-8")
    assert res[0]["figures"] == 1 and res[0]["attachments"][0]["title"] == "EXA-150 attachment: om-a.pdf"
    assert subprocess.run(["git", "-C", str(instance), "status", "--porcelain"], capture_output=True, text=True).stdout == ""
    again = jira.add(["EXA-150"], **CFG)  # same content: nothing new
    assert not again[0]["created"]


def test_get_text_and_credentials(monkeypatch, fake, tmp_path):
    assert jira.get_text("EXA-150", **CFG).startswith("# EXA-150: Minimum rest")
    for v in ("JIRA_API_TOKEN", "JIRA_EMAIL"):
        monkeypatch.delenv(v, raising=False)
    from kb.core import secrets
    monkeypatch.setattr(secrets, "windows_credential", lambda t: ("me@example.com", "from-wcm") if t == "copilot-jira" else None)

    class NoStore:
        def get(self, name): return None
    monkeypatch.setattr(jira.registry, "create", lambda *a, **k: NoStore())
    j = jira.Jira("https://example.atlassian.net")
    assert (j.email, j.token) == ("me@example.com", "from-wcm")
    monkeypatch.setattr(secrets, "windows_credential", lambda t: None)
    with pytest.raises(RuntimeError, match="no Jira token"):
        jira.Jira("https://example.atlassian.net")
    monkeypatch.setenv("JIRA_API_TOKEN", "pat")
    assert jira.Jira("https://jira.example.com").email is None  # Data Center: bearer token, no e-mail


def test_data_center_uses_the_token_even_with_an_email(monkeypatch):
    seen = []

    class H:
        def get_content_type(self): return "application/json"

    class R:
        headers = H()
        def read(self): return b'{"displayName": "Me"}'
        def __enter__(self): return self
        def __exit__(self, *a): pass
    monkeypatch.setattr(jira.urllib.request, "urlopen", lambda req, timeout=None: seen.append(req.get_header("Authorization")) or R())
    jira.Jira("https://jira.example.com", email="me@example.com", token="pat").whoami()
    jira.Jira("https://example.atlassian.net", email="me@example.com", token="api").whoami()
    assert seen[0] == "Bearer pat" and seen[1].startswith("Basic ")


def test_login_page_is_an_auth_error(monkeypatch):
    class R:
        headers = type("H", (), {"get_content_type": lambda self: "text/html"})()
        def read(self): return b"<!doctype html><title>Log in with Atlassian account</title>"
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(jira.urllib.request, "urlopen", lambda *a, **k: R())
    with pytest.raises(PermissionError, match="login page"):
        jira.Jira(**CFG).issue_xml("EXA-1")


def test_heartbeat(monkeypatch, instance):
    from kb.llm.gateway import Gateway
    from kb.publish import settings

    def request(self, url, accept):
        assert url.endswith("/rest/api/3/myself?")
        return b'{"displayName": "Piotr", "emailAddress": "me@example.com"}', "application/json"
    monkeypatch.setattr(jira.Jira, "_request", request)
    me = jira.Jira(**CFG).whoami()
    assert me == {"name": "Piotr", "email": "me@example.com", "source": "argument"}

    gw = Gateway(cfg={"default_adapter": "fake", "adapters": {"fake": {"module": "kb.llm.adapters:FakeAdapter"}},
                      "tiers": {"standard": {"model": "m"}}, "tasks": {}}, log_path=instance / "m.jsonl")
    r = settings.check(gw)
    assert r["copilot"]["ok"] is None and r["jira"]["ok"] is None          # fake adapter, Jira not configured
    (instance / "config").mkdir(parents=True, exist_ok=True)
    (instance / "config" / "profile.yaml").write_text("jira:\n  base_url: https://example.atlassian.net\n  email: me@example.com\n")
    monkeypatch.setenv("JIRA_API_TOKEN", "t")
    r = settings.check(gw, "jira")
    assert r["jira"]["ok"] and "Piotr <me@example.com>" in r["jira"]["detail"] and "environment" in r["jira"]["detail"]

    def refused(self, url, accept):
        raise PermissionError("Jira refused the credentials (401); check the token and e-mail")
    monkeypatch.setattr(jira.Jira, "_request", refused)
    assert settings.check(gw, "jira")["jira"] == {"ok": False, "detail": "Jira refused the credentials (401); check the token and e-mail"}


def test_heartbeat_explains_errors(monkeypatch):
    import urllib.error

    def not_found(self, url, accept):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
    monkeypatch.setattr(jira.Jira, "_request", not_found)
    with pytest.raises(RuntimeError, match="check the Jira URL"):
        jira.Jira(**CFG).whoami()

    def offline(self, url, accept):
        raise urllib.error.URLError("getaddrinfo failed")
    monkeypatch.setattr(jira.Jira, "_request", offline)
    with pytest.raises(RuntimeError, match="cannot reach https://example.atlassian.net: getaddrinfo failed"):
        jira.Jira(**CFG).whoami()


def test_looking_an_issue_up_downloads_its_pictures_once_and_lists_them(instance, fake, tmp_path):
    """jira_get / kb jira get: the screenshots come along (the model decides whether to look), documents do not."""
    from kb.knowledge.tools.jira import images_dir
    t = jira.get_text("EXA-150", images=images_dir(), shown_from=instance, **CFG)
    shot = instance / ".cache" / "jira" / "EXA-150" / "screen.png"
    assert shot.read_bytes() == PNG and not (shot.parent / "om-a.pdf").exists()       # pictures only
    assert "## Images attached to the issue (downloaded)" in t and "- `.cache/jira/EXA-150/screen.png` (1 KB, attached by anna)" in t
    assert "view tool" in t
    n = sum(u.endswith("/501") for u in fake)
    jira.get_text("EXA-150", images=images_dir(), shown_from=instance, **CFG)
    assert sum(u.endswith("/501") for u in fake) == n                                  # cached: not fetched again
    assert "Images attached" not in jira.get_text("EXA-150", **CFG)                     # without images: as before


def test_the_pictures_folder_is_readable_by_the_model_and_ignored_by_git(instance):
    from kb.knowledge import catalog
    from kb.knowledge.agent import Sandbox
    from kb.knowledge.tools.jira import images_dir
    catalog.init()
    p = images_dir() / "EXA-1" / "a.png"
    p.parent.mkdir(parents=True); p.write_bytes(PNG)
    box = Sandbox(instance, write_dirs=())
    assert box.decide("view", {"path": str(p)})[0] and not box.decide("create", {"path": str(p)})[0]
    out = subprocess.run(["git", "-C", str(instance), "status", "--porcelain"], capture_output=True, text=True).stdout
    assert ".cache" not in out
