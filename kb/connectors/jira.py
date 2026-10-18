"""Jira connector: fetches issues by JQL (REST API, read-only) and saves each as `<KEY>.jira.json` for the extractor.

Auth (token never in the repo, `kb secrets set jira-token`):
  Jira Cloud:          base_url https://<site>.atlassian.net, email + API token (basic auth)
  Jira Server / DC:    personal access token (bearer), no email
"""
from __future__ import annotations

import base64
import json
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

from kb.core import registry
from kb.core.ports import Connector, FetchedItem

FIELDS = "summary,description,comment,status,issuetype,priority,labels,components,fixVersions,created,updated,resolution"


class Jira(Connector):
    name = "jira"

    def __init__(self, base_url: str, email: str | None = None, token: str | None = None, secret_name: str = "jira-token",
                 secret_store: str = "keyring", api: str | None = None, **options):
        super().__init__(**options)
        self.base = base_url.rstrip("/")
        self.email = email
        self.token = token or registry.create("secret_stores", secret_store).get(secret_name)
        if not self.token:
            raise RuntimeError(f"no Jira token: run `kb secrets set {secret_name}`")
        self.api = api or ("3" if "atlassian.net" in self.base else "2")

    def _get(self, path: str, params: dict) -> dict:
        url = f"{self.base}/rest/api/{self.api}/{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        if self.email:
            req.add_header("Authorization", "Basic " + base64.b64encode(f"{self.email}:{self.token}".encode()).decode())
        else:
            req.add_header("Authorization", f"Bearer {self.token}")
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))

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

    def fetch(self, ref, dest_dir):
        issue = self._get(f"issue/{ref}", {"fields": FIELDS})
        return self._save(issue, dest_dir)

    def _save(self, issue: dict, dest_dir: Path) -> FetchedItem:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dst = dest_dir / f"{issue['key']}.jira.json"
        issue["self_url"] = f"{self.base}/browse/{issue['key']}"
        dst.write_text(json.dumps(issue, ensure_ascii=False, indent=1), encoding="utf-8")
        return FetchedItem(path=dst, title=issue["key"], kind="ticket", ref=issue["key"], mime="application/json")


def collect(jql: str, limit: int = 50, **cfg):
    from kb.knowledge import catalog
    j = Jira(**cfg)
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        for issue in j.search(jql, limit):
            item = j._save(issue, Path(tmp))
            out.append(catalog.add_file(item.path, connector="jira", ref=issue["key"], kind="ticket",
                                        url=issue["self_url"], found_via=[f"jql:{jql}"]))
    return out
