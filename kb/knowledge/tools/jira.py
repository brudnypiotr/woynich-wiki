"""Jira, read-only: one issue as compact text, or a JQL search (token in Windows Credential Manager)."""
from __future__ import annotations

from pydantic import BaseModel, Field

from kb.core import config


def jira_config() -> dict | None:
    cfg = config.load("profile").get("jira") or {}
    return cfg if cfg.get("base_url") else None


def available() -> bool:
    return jira_config() is not None


def context() -> str:
    return ("JIRA: tools `jira_get` and `jira_search` are available (read-only); `jira_get` also downloads the issue's "
            "pictures and lists their paths, look at them with `view` when they matter.") if available() else "JIRA: not configured."


def images_dir():
    """Where looked-up issues' pictures go: inside the instance (the model may read there), git-ignored, kept as a cache."""
    from kb.knowledge import catalog
    return catalog.instance() / ".cache" / "jira"


class JiraGet(BaseModel):
    key: str = Field(description="Issue key, e.g. PROJ-123")
    images: bool = Field(default=True, description="Download the issue's pictures (screenshots, diagrams) and list their "
                                                   "paths at the end; false only for a quick look at many issues")


class JiraSearch(BaseModel):
    jql: str = Field(description="JQL query, e.g. 'project = PROJ AND text ~ \"minimum rest\"'")
    limit: int = Field(default=10, description="Maximum number of issues (1-20)")


def tools() -> list:
    cfg = jira_config()
    from copilot import define_tool
    from kb.knowledge.tools import off_loop
    from kb.connectors import jira

    @define_tool(description="Fetch one Jira issue as compact text: fields, links, custom fields (e.g. found in release), "
                             "description and comments (cite comments as KEY#cN; a link's ?focusedCommentId= is the comment id shown). "
                             "Its pictures are downloaded and their paths listed at the end: look at one with the view tool "
                             "when the text refers to a screen, an error, a table or a diagram (you decide; not every one). "
                             "Accepts a key or a Jira URL. Read-only.")
    @off_loop
    def jira_get(params: JiraGet) -> str:
        from kb.knowledge import catalog
        return jira.get_text(params.key.strip(), images=images_dir() if params.images else None,
                             shown_from=catalog.instance(), **cfg)[:40_000]

    @define_tool(description="Search Jira with JQL; returns key, summary and status of matching issues. Read-only.")
    @off_loop
    def jira_search(params: JiraSearch) -> str:
        issues = jira.Jira(**cfg).search(params.jql, max(1, min(20, params.limit)))
        return "\n".join(f"{i['key']}: {i['fields'].get('summary', '')} [{(i['fields'].get('status') or {}).get('name', '')}]"
                         for i in issues) or "no issues found"

    return [jira_get, jira_search]
