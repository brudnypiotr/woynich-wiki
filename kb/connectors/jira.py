"""Jira connector (read-only): one issue as the Jira **XML issue view** (description and comments as HTML, links,
sub-tasks, custom fields, attachment list in one compact request), attachments, and JQL search.

Credentials, first found wins (the token never goes into the repository):
  1. `token=` / `email=` arguments, or JIRA_API_TOKEN / JIRA_EMAIL environment variables,
  2. the secret store: `kb secrets set jira-token` (Settings → Keys and tokens), email from the profile,
  3. a generic Windows credential (default `copilot-jira`, user = Atlassian e-mail, password = API token), the one
     the jira-snapshot skill stores: `cmdkey /generic:copilot-jira /user:<email> /pass:<token>`.
Jira Cloud (`*.atlassian.net`): e-mail + API token (basic auth). Jira Data Center: personal access token (bearer).
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from kb.core import registry
from kb.core.ports import Connector, FetchedItem

FIELDS = "summary,status"  # search only needs keys; the issue itself comes as XML
XML_FIELDS = ["title", "summary", "description", "key", "link", "type", "status", "resolution", "priority", "assignee",
              "reporter", "created", "updated", "resolved", "labels", "version", "fixVersion", "component", "attachments",
              "issuelinks", "subtasks", "comments", "allcustom"]
KEY = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
DOC_EXT = {".pdf", ".docx", ".doc", ".xlsx", ".pptx", ".txt", ".md", ".eml", ".msg", ".vtt", ".csv", ".json", ".xml", ".log", ".html"}
MAX_ATTACHMENT = 25_000_000


def issue_key(value: str) -> str:
    m = KEY.search(value.upper())
    if not m:
        raise ValueError(f"no Jira issue key in {value!r}")
    return m.group(1)


class Jira(Connector):
    name = "jira"

    def __init__(self, base_url: str, email: str | None = None, token: str | None = None, secret_name: str = "jira-token",
                 secret_store: str = "keyring", credential: str = "copilot-jira", api: str | None = None, **options):
        super().__init__(**options)
        self.base = base_url.rstrip("/")
        self.cloud = "atlassian.net" in self.base
        self.api = api or ("3" if self.cloud else "2")
        self.email, self.token = self._credentials(email, token, secret_name, secret_store, credential)

    def _credentials(self, email, token, secret_name, secret_store, credential):
        self.source = "argument" if token else "environment (JIRA_API_TOKEN)"
        email, token = email or os.environ.get("JIRA_EMAIL"), token or os.environ.get("JIRA_API_TOKEN")
        if not token:
            self.source = f"Keys and tokens ({secret_name})"
            try:
                token = registry.create("secret_stores", secret_store).get(secret_name)
            except Exception:
                token = None
        if not token and credential:
            from kb.core.secrets import windows_credential
            self.source = f"Windows credential {credential}"
            found = windows_credential(credential)
            if found:
                email, token = email or found[0], found[1]
        if not token:
            raise RuntimeError(f"no Jira token: Settings → Keys and tokens → Jira token (or `kb secrets set {secret_name}`), "
                               f"or a Windows credential `{credential}` (cmdkey /generic:{credential} /user:<email> /pass:<token>)")
        if self.cloud and not email:
            raise RuntimeError("Jira Cloud needs the Atlassian e-mail: Settings → Jira e-mail, or the user name of the "
                               f"`{credential}` Windows credential")
        return email, token

    # ------------------------------------------------------------------ HTTP
    def _request(self, url: str, accept: str) -> tuple[bytes, str]:
        req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "woynich-wiki"})
        if self.cloud:  # Cloud: e-mail + API token; Data Center: personal access token (an e-mail, if known, is not used)
            req.add_header("Authorization", "Basic " + base64.b64encode(f"{self.email}:{self.token}".encode()).decode())
        else:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                body, ctype = r.read(), r.headers.get_content_type() or ""
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise PermissionError(f"Jira refused the credentials ({e.code}); check the token and e-mail") from e
            raise
        if "html" in ctype.lower() or b"log in with atlassian account" in body[:4000].lower():
            raise PermissionError("Jira returned a login page instead of data; the token is missing, wrong or expired")
        return body, ctype

    def _get(self, path: str, params: dict) -> dict:
        url = f"{self.base}/rest/api/{self.api}/{path}?{urllib.parse.urlencode(params)}"
        return json.loads(self._request(url, "application/json")[0].decode("utf-8"))

    # ------------------------------------------------------------------ reading
    def whoami(self) -> dict:
        """One cheap authenticated request: who the credentials belong to (heartbeat)."""
        try:
            me = self._get("myself", {})
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise RuntimeError(f"{self.base} is not a Jira site (404): check the Jira URL, e.g. https://<site>.atlassian.net") from e
            raise RuntimeError(f"Jira answered {e.code} {e.reason}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"cannot reach {self.base}: {e.reason} (network, VPN or proxy?)") from e
        return {"name": me.get("displayName") or me.get("name"), "email": me.get("emailAddress"), "source": self.source}

    def issue_xml(self, key: str) -> str:
        key = issue_key(key)
        q = "&".join(f"field={urllib.parse.quote(f)}" for f in XML_FIELDS)
        body, _ = self._request(f"{self.base}/si/jira.issueviews:issue-xml/{key}/{key}.xml?{q}", "application/xml,text/xml,*/*")
        text = body.decode("utf-8", errors="replace")
        ET.fromstring(text)  # must be XML
        return text

    def attachment(self, att_id: str, name: str) -> bytes:
        url = (f"{self.base}/rest/api/3/attachment/content/{att_id}" if self.cloud
               else f"{self.base}/secure/attachment/{att_id}/{urllib.parse.quote(name)}")
        return self._request(url, "*/*")[0]

    def search(self, jql: str, limit: int = 50) -> list[dict]:
        issues, start = [], 0
        while len(issues) < limit:
            if self.api == "3":
                data = self._get("search/jql", {"jql": jql, "fields": FIELDS, "maxResults": min(50, limit - len(issues)),
                                                **({"nextPageToken": start} if start else {})})
                issues += data.get("issues", [])
                start = data.get("nextPageToken")
                if not start:
                    break
            else:
                data = self._get("search", {"jql": jql, "fields": FIELDS, "startAt": start, "maxResults": min(50, limit - len(issues))})
                issues += data.get("issues", [])
                start += len(data.get("issues", []))
                if start >= data.get("total", 0) or not data.get("issues"):
                    break
        return issues[:limit]

    def list(self):
        raise NotImplementedError("use search(jql)")

    def fetch(self, ref, dest_dir, attachments: bool = True) -> FetchedItem:
        """Save `<KEY>.jira.xml` and, if asked, its attachments in `<KEY>-attachments/`."""
        key = issue_key(ref)
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        xml = self.issue_xml(key)
        dst = dest_dir / f"{key}.jira.xml"
        dst.write_text(xml, encoding="utf-8")
        item = FetchedItem(path=dst, title=key, kind="ticket", ref=key, mime="application/xml")
        item.meta.update(attachments=[], warnings=[])
        if attachments:
            adir = dest_dir / f"{key}-attachments"
            for a in ET.fromstring(xml).iter("attachment"):
                att_id, name, size = a.get("id", ""), Path(a.get("name", "") or "").name, int(a.get("size") or 0)
                if not att_id.isdigit() or not name:
                    continue
                if size > MAX_ATTACHMENT:
                    item.meta["warnings"].append(f"{name}: {size // 1_000_000} MB, skipped (limit {MAX_ATTACHMENT // 1_000_000} MB)")
                    continue
                try:
                    data = self.attachment(att_id, name)
                except Exception as e:
                    item.meta["warnings"].append(f"{name}: not downloaded ({type(e).__name__}: {e})"[:200])
                    continue
                adir.mkdir(exist_ok=True)
                p = adir / re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
                if p.exists():
                    p = p.with_name(f"{p.stem}-{att_id}{p.suffix}")
                p.write_bytes(data)
                item.meta["attachments"].append(p)
        return item


def _jira(**cfg) -> Jira:
    if not cfg.get("base_url"):
        raise RuntimeError("Jira is not configured: Settings → Jira URL (jira.base_url in instance/config/profile.yaml)")
    return Jira(**cfg)


def get_text(key: str, **cfg) -> str:
    """One issue as compact text (for the assistant and `kb jira get`); nothing is stored."""
    from kb.extractors.office import JiraXmlExtractor
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / f"{issue_key(key)}.jira.xml"
        p.write_text(_jira(**cfg).issue_xml(key), encoding="utf-8")
        return JiraXmlExtractor().extract(p)["text"]


def linked_keys(xml_path: Path) -> list[str]:
    root = ET.fromstring(Path(xml_path).read_bytes())
    keys = [k.text.strip() for k in root.iter("issuekey") if k.text] + [s.text.strip() for s in root.iter("subtask") if s.text]
    return sorted(set(keys))


def add(keys: list[str], links: bool = False, attachments: bool = True, found_via: str | None = None, **cfg) -> list[dict]:
    """Register issues as sources (one commit each): the XML snapshot, its images as figures the model looks at
    during ingest, and its document attachments as separate sources. `links=True` also adds linked issues and
    sub-tasks (one level). Returns one entry per issue: record, created, attachments, warnings."""
    from kb.core import gitops
    from kb.knowledge import catalog
    j = _jira(**cfg)
    todo, done, out = [issue_key(k) for k in keys], set(), []
    first = set(todo)
    with tempfile.TemporaryDirectory() as tmp:
        while todo:
            key = todo.pop(0)
            if key in done:
                continue
            done.add(key)
            item = j.fetch(key, Path(tmp) / key, attachments=attachments)
            rec, created = catalog.add_file(item.path, connector="jira", ref=key, kind="ticket", url=f"{j.base}/browse/{key}",
                                            found_via=[found_via or f"jira:{key}"], commit=False)
            docs = []
            if created:
                d = catalog.instance() / "raw" / rec["id"]
                for p in item.meta["attachments"]:
                    if p.suffix.lower() in IMAGE_EXT:
                        (d / "figures").mkdir(exist_ok=True)
                        shutil.copy2(p, d / "figures" / p.name)
                gitops.commit(catalog.instance(), [d], gitops.message("source", f"add {rec['title']}", scope=rec["id"],
                                                                      body=f"kind: ticket\nurl: {j.base}/browse/{key}"))
            for p in item.meta["attachments"]:
                if p.suffix.lower() in DOC_EXT:
                    docs.append(catalog.add_file(p, connector="jira", ref=f"{key}/{p.name}", title=f"{key} attachment: {p.name}",
                                                 url=f"{j.base}/browse/{key}", found_via=[f"jira:{key}"]))
            out.append({"record": rec, "created": created, "attachments": [r for r, _ in docs],
                        "figures": sum(p.suffix.lower() in IMAGE_EXT for p in item.meta["attachments"]), "warnings": item.meta["warnings"]})
            if links and key in first:  # one level only
                todo += [k for k in linked_keys(item.path) if k not in done]
    return out


def collect(jql: str, limit: int = 50, **cfg):
    """`kb collect jira --jql`: every matching issue as a source (XML snapshot and attachments)."""
    keys = [i["key"] for i in _jira(**cfg).search(jql, limit)]
    return [(r["record"], r["created"]) for r in add(keys, found_via=f"jql:{jql}", **cfg)]
