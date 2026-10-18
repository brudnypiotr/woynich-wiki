"""Conversation with the knowledge base: the model uses the wiki first and, when the question needs it, reads the
configured code repositories, fetches Jira issues and looks at attached screenshots. Read-only.

Used by `kb ask`, `kb code-ask`, `kb chat` and the Discuss tab of `kb serve`.

Code repositories are configured in instance/config/profile.yaml:
    code_repos:
      - name: inventory-service
        path: C:/Users/me/DEV/inventory-service
        description: Inventory backend (Java). Rules engine, stock, orders; look here for rule logic.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

from pydantic import BaseModel, Field

from kb.core import config
from kb.knowledge import agent, catalog


def repos() -> list[dict]:
    out = []
    for r in config.load("profile").get("code_repos") or []:
        p = Path(str(r.get("path", ""))).expanduser()
        if not p.is_absolute():
            p = (config.paths().root / p).resolve()
        item = {"name": r.get("name") or p.name, "path": p, "description": (r.get("description") or "").strip(),
                "exists": p.is_dir(), "commit": None, "dirty": False}
        if (p / ".git").exists():
            g = lambda *a: subprocess.run(["git", "-C", str(p), *a], capture_output=True, text=True, encoding="utf-8",
                                          errors="replace").stdout.strip()
            item["commit"] = g("rev-parse", "--short", "HEAD") or None
            item["branch"] = g("rev-parse", "--abbrev-ref", "HEAD") or None
            item["dirty"] = bool(g("status", "--porcelain", "--untracked-files=no"))
        out.append(item)
    return out


def jira_config() -> dict | None:
    cfg = config.load("profile").get("jira") or {}
    return cfg if cfg.get("base_url") else None


class JiraGet(BaseModel):
    key: str = Field(description="Issue key, e.g. PROJ-123")


class JiraSearch(BaseModel):
    jql: str = Field(description="JQL query, e.g. 'project = PROJ AND text ~ \"minimum rest\"'")
    limit: int = Field(default=10, description="Maximum number of issues (1-20)")


def jira_tools() -> list:
    """Read-only Jira tools for the model, if Jira is configured (token in Windows Credential Manager)."""
    cfg = jira_config()
    if not cfg:
        return []
    from copilot import define_tool
    from kb.connectors.jira import Jira
    from kb.extractors.office import JiraJsonExtractor

    def text_of(issue: dict) -> str:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / f"{issue['key']}.jira.json"
            p.write_text(json.dumps(issue), encoding="utf-8")
            return JiraJsonExtractor().extract(p)["text"]

    @define_tool(description="Fetch one Jira issue (description and comments) as text. Read-only.")
    def jira_get(params: JiraGet) -> str:
        j = Jira(**cfg)
        issue = j._get(f"issue/{params.key.strip()}", {"fields": "summary,description,comment,status,updated,resolution"})
        return text_of(issue)[:40_000]

    @define_tool(description="Search Jira with JQL; returns key, summary and status of matching issues. Read-only.")
    def jira_search(params: JiraSearch) -> str:
        j = Jira(**cfg)
        issues = j.search(params.jql, max(1, min(20, params.limit)))
        return "\n".join(f"{i['key']}: {i['fields'].get('summary', '')} [{(i['fields'].get('status') or {}).get('name', '')}]"
                         for i in issues) or "no issues found"

    return [jira_get, jira_search]


def _context(history, topic, attachments, focus) -> str:
    rs = repos()
    lines = []
    if rs:
        lines.append("CODE REPOSITORIES you may read (read-only; cite as `name/path/to/file:LINE@commit`):")
        for r in rs:
            state = "missing on disk" if not r["exists"] else f"commit {r['commit'] or 'unknown'}" + (" (uncommitted local changes)" if r["dirty"] else "")
            lines.append(f"- {r['name']}: `{r['path'].as_posix()}` — {r['description'] or 'no description'} [{state}]")
    else:
        lines.append("No code repositories are configured.")
    lines.append("JIRA: tools `jira_get` and `jira_search` are available (read-only)." if jira_config() else "JIRA: not configured.")
    if attachments:
        lines.append(f"ATTACHED: {len(attachments)} image(s) from the user (e.g. a screenshot of the application). Describe "
                     "what is shown and explain it using the wiki (screens, fields, rules, where to click).")
    if focus == "code":
        lines.append("FOCUS: this is a question about the code. Search the repositories (grep for identifiers, then read "
                     "the relevant files) and explain how it works, citing file and line.")
    if topic:
        lines.append(f"DISCUSSION TOPIC: {topic}")
    if history:
        lines.append("EARLIER IN THIS CONVERSATION:\n" + "\n".join(f"Q: {h['question']}\nA: {h.get('answer_text', '')[:1200]}" for h in history[-4:]))
    return "\n".join(lines)


def ask(question: str, runner=None, history=None, topic=None, attachments=(), focus: str = "wiki", save: bool = False,
        progress=None) -> dict:
    inst = catalog.instance()
    from kb.knowledge import wiki
    wiki.ensure_skeleton()
    rs = [r for r in repos() if r["exists"]]
    task = agent.prompt("chat", question=question, context=_context(history, topic, attachments, focus))
    t0 = time.perf_counter()
    runner = runner or agent.AgentRunner()
    res = runner.run(task, agent.model_for("query"), inst, write_dirs=(), progress=progress,
                     read_roots=[r["path"] for r in rs], tools=jira_tools(), attachments=list(attachments))
    agent.meter("agent_code" if focus == "code" else "agent_query", res)
    reply = res.reply.strip()
    not_found = reply.upper().startswith("NOT FOUND")
    read = sorted({p for t in res.tools for p in t.get("paths", []) if t["ok"] and re.search(r"\.\w+$", p)})
    out = {"question": question, "answer_text": reply, "not_found": not_found, "seconds": round(time.perf_counter() - t0, 1),
           "premium": res.premium, "pages_read": read, "tools_used": sorted({t["tool"] for t in res.tools if t["ok"]})}
    log = inst / "catalog" / "queries.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": catalog.now(), "question": question, "focus": focus, "not_found": not_found,
                            "seconds": out["seconds"], "premium": res.premium, "attachments": len(attachments)}, ensure_ascii=False) + "\n")
    if save and not not_found:
        out["saved"] = str(wiki.save_answer(question, reply))
    return out
