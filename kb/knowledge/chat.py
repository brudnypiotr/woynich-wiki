"""Conversation with the knowledge base: the model uses the wiki first and, when the question needs it, reads the
configured code repositories, fetches Jira issues and looks at attached screenshots. Read-only.

`ask` is one session per question (`kb ask`, `kb code-ask`); `Conversation` keeps one session open for a whole
discussion (`kb chat`, `kb serve`; ADR-0019), so follow-up questions build on what the model already read.

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
import threading
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
        item = {"name": r.get("name") or p.name, "path": p, "role": (r.get("role") or "").strip(),
                "description": (r.get("description") or "").strip(), "exists": p.is_dir(), "commit": None, "dirty": False}
        if (p / ".git").exists():
            item.update(_git_state(p))
        out.append(item)
    return out


_GIT: dict[str, tuple[float, dict]] = {}


def _git_state(p: Path, ttl: float = 60) -> dict:
    """Branch, commit and local changes of a repository, cached for a minute: `git status` on a large repository
    is slow on Windows, and this runs for every question and every Settings page."""
    hit = _GIT.get(str(p))
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    g = lambda *a: subprocess.run(["git", "-C", str(p), *a], capture_output=True, text=True, encoding="utf-8",
                                  errors="replace").stdout.strip()
    st = {"commit": g("rev-parse", "--short", "HEAD") or None, "branch": g("rev-parse", "--abbrev-ref", "HEAD") or None,
          "dirty": bool(g("status", "--porcelain", "--untracked-files=no"))}
    _GIT[str(p)] = (time.time(), st)
    return st


def architecture() -> str:
    """How the parts of the system fit together (profile `architecture`, edited in Settings)."""
    return str(config.load("profile").get("architecture") or "").strip()


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
    from kb.connectors import jira

    @define_tool(description="Fetch one Jira issue as compact text: fields, links, custom fields (e.g. found in release), "
                             "description and comments (cite comments as KEY#cN; a link's ?focusedCommentId= is the comment id shown). "
                             "Accepts a key or a Jira URL. Read-only.")
    def jira_get(params: JiraGet) -> str:
        return jira.get_text(params.key.strip(), **cfg)[:40_000]

    @define_tool(description="Search Jira with JQL; returns key, summary and status of matching issues. Read-only.")
    def jira_search(params: JiraSearch) -> str:
        issues = jira.Jira(**cfg).search(params.jql, max(1, min(20, params.limit)))
        return "\n".join(f"{i['key']}: {i['fields'].get('summary', '')} [{(i['fields'].get('status') or {}).get('name', '')}]"
                         for i in issues) or "no issues found"

    return [jira_get, jira_search]


class GitLog(BaseModel):
    repo: str = Field(description="Repository name, as listed under CODE REPOSITORIES")
    path: str = Field(default="", description="Only commits touching this file or folder (relative to the repository root)")
    grep: str = Field(default="", description="Only commits whose message contains this text (e.g. a Jira key)")
    author: str = Field(default="", description="Only commits by this author (name or e-mail, part is enough)")
    since: str = Field(default="", description="Only commits since this date, YYYY-MM-DD")
    limit: int = Field(default=20, description="Maximum number of commits (1-50)")


class GitShow(BaseModel):
    repo: str = Field(description="Repository name")
    commit: str = Field(description="Commit hash (at least 4 hex characters)")
    path: str = Field(default="", description="Show the change of this file only")


class GitBlame(BaseModel):
    repo: str = Field(description="Repository name")
    path: str = Field(description="File, relative to the repository root")
    start: int = Field(description="First line")
    end: int = Field(description="Last line (at most 200 lines after start)")


GIT_OUT = 40_000
_HASH = re.compile(r"[0-9a-fA-F]{4,40}")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _git(repo: str, *args: str) -> str:
    """Run one read-only git command in a configured repository: a fixed command and checked arguments, no shell,
    no pager, no external diff or text conversion, a time limit and a size limit on the output."""
    r = next((x for x in repos() if x["name"] == repo and x["exists"]), None)
    if r is None:
        return f"unknown repository {repo!r}; use one of: " + ", ".join(x["name"] for x in repos() if x["exists"])
    try:
        p = subprocess.run(["git", "-c", "core.pager=cat", "-c", "color.ui=false", "-C", str(r["path"]), *args],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    except subprocess.TimeoutExpired:
        return "git took longer than 30 s; narrow it down (path, since, limit)"
    out = (p.stdout if p.returncode == 0 else p.stderr).strip()
    return (out[:GIT_OUT] + "\n… (cut)" if len(out) > GIT_OUT else out) or "no output"


def _relpath(path: str) -> str:
    p = path.strip().replace("\\", "/").lstrip("/")
    if not p or p.startswith("-") or ".." in p.split("/") or re.match(r"[A-Za-z]:", p):
        raise ValueError(f"not a path inside the repository: {path!r}")
    return p


def git_tools() -> list:
    """Read-only Git history of the configured code repositories: who changed what, when and why."""
    if not any(r["exists"] for r in repos()):
        return []
    from copilot import define_tool

    @define_tool(description="Commit history of a code repository: hash, date, author and subject. Filter by file or "
                             "folder, message text (e.g. a Jira key), author or date. Cite a commit as `repo@hash`. Read-only.")
    def git_log(params: GitLog) -> str:
        args = ["log", f"-n{max(1, min(50, params.limit))}", "--date=short", "--format=%h %ad %an <%ae> %s"]
        if params.grep.strip():
            args += ["-i", f"--grep={params.grep.strip()}"]
        if params.author.strip():
            args.append(f"--author={params.author.strip()}")
        if params.since.strip():
            if not _DATE.fullmatch(params.since.strip()):
                return "since must be a date YYYY-MM-DD"
            args.append(f"--since={params.since.strip()}")
        try:
            return _git(params.repo, *args, "--", *([_relpath(params.path)] if params.path.strip() else []))
        except ValueError as e:
            return str(e)

    @define_tool(description="One commit of a code repository: author, date, full message, changed files and the diff "
                             "(optionally of one file only). Cite as `repo@hash`. Read-only.")
    def git_show(params: GitShow) -> str:
        if not _HASH.fullmatch(params.commit.strip()):
            return "commit must be a hash (4-40 hex characters)"
        try:
            only = [_relpath(params.path)] if params.path.strip() else []
        except ValueError as e:
            return str(e)
        return _git(params.repo, "show", "--no-ext-diff", "--no-textconv", "--stat", "--patch", "--date=iso",
                    "--format=commit %H%nAuthor: %an <%ae>%nDate: %ad%n%n%B", params.commit.strip(), "--", *only)

    @define_tool(description="Who last changed each line of a file (git blame): commit, author and date per line. "
                             "Use it to find the commit behind a rule or a value, then git_show it. Read-only.")
    def git_blame(params: GitBlame) -> str:
        start, end = max(1, params.start), max(1, params.end)
        if end < start or end - start > 200:
            return "give a range of at most 200 lines (start ≤ end)"
        try:
            return _git(params.repo, "blame", "--date=short", f"-L{start},{end}", "--", _relpath(params.path))
        except ValueError as e:
            return str(e)

    return [git_log, git_show, git_blame]


def _context(history, topic, attachments, focus) -> str:
    rs = repos()
    lines = []
    if rs:
        if architecture():
            lines.append("SYSTEM ARCHITECTURE (how the parts below fit together; follow a behaviour across tiers, e.g. "
                         "screen → API → service → database, and say which tier the answer comes from):\n" + architecture())
        lines.append("CODE REPOSITORIES you may read (read-only; cite as `name/path/to/file:LINE@commit`):")
        for r in rs:
            state = "missing on disk" if not r["exists"] else f"commit {r['commit'] or 'unknown'}" + (" (uncommitted local changes)" if r["dirty"] else "")
            role = f" ({r['role']})" if r["role"] else ""
            lines.append(f"- {r['name']}{role}: `{r['path'].as_posix()}` — {r['description'] or 'no description'} [{state}]")
        lines.append("GIT HISTORY: tools `git_log`, `git_show` and `git_blame` (read-only) show who changed what, when "
                     "and why; cite a commit as `name@hash`.")
    else:
        lines.append("No code repositories are configured.")
    lines.append("JIRA: tools `jira_get` and `jira_search` are available (read-only)." if jira_config() else "JIRA: not configured.")
    if topic:
        lines.append(f"DISCUSSION TOPIC: {topic}")
    if history:
        lines.append("EARLIER IN THIS CONVERSATION:\n" + "\n".join(f"Q: {h['question']}\nA: {h.get('answer_text', '')[:1200]}" for h in history[-4:]))
    return "\n".join(lines + _turn(attachments, focus))


def _turn(attachments, focus, changed=()) -> list[str]:
    """Context that belongs to one question (also sent with follow-ups in a long session)."""
    lines = []
    if changed:
        lines.append("WIKI UPDATED since your last answer (a source was ingested). Changed pages: "
                     + ", ".join(f"`{p}`" for p in sorted(changed)[:30]) + ". Re-read them before relying on what you remember.")
    if attachments:
        lines.append(f"ATTACHED: {len(attachments)} image(s) from the user (e.g. a screenshot of the application). Describe "
                     "what is shown and explain it using the wiki (screens, fields, rules, where to click).")
    if focus == "code":
        lines.append("FOCUS: this is a question about the code. Search the repositories (grep for identifiers, then read "
                     "the relevant files) and explain how it works, citing file and line.")
    return lines


def _finish(question, res, focus, attachments, t0, task: str) -> dict:
    inst = catalog.instance()
    agent.meter(task, res)
    reply = res.reply.strip()
    not_found = reply.upper().startswith("NOT FOUND")
    read = sorted({p for t in res.tools for p in t.get("paths", []) if t["ok"] and re.search(r"\.\w+$", p)})
    from kb.knowledge import verify
    out = {"question": question, "answer_text": reply, "not_found": not_found, "seconds": round(time.perf_counter() - t0, 1),
           "premium": res.premium, "credits": res.credits, "pages_read": read, "tools_used": sorted({t["tool"] for t in res.tools if t["ok"]}),
           "check": verify.check_answer(reply)}  # deterministic citation check, as `kb check-answer` in the CLI
    log = inst / "catalog" / "queries.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": catalog.now(), "question": question, "focus": focus, "not_found": not_found,
                            "seconds": out["seconds"], "premium": res.premium, "credits": res.credits, "attachments": len(attachments), "task": task},
                           ensure_ascii=False) + "\n")
    return out


def ask(question: str, runner=None, history=None, topic=None, attachments=(), focus: str = "wiki", save: bool = False,
        progress=None) -> dict:
    """One question, one agent session."""
    inst = catalog.instance()
    from kb.knowledge import wiki
    wiki.ensure_skeleton()
    rs = [r for r in repos() if r["exists"]]
    task = agent.prompt("chat", question=question, context=_context(history, topic, attachments, focus))
    t0 = time.perf_counter()
    runner = runner or agent.AgentRunner()
    res = runner.run(task, agent.model_for("query"), inst, write_dirs=(), progress=progress,
                     read_roots=[r["path"] for r in rs], tools=jira_tools() + git_tools(), attachments=list(attachments))
    out = _finish(question, res, focus, attachments, t0, "agent_code" if focus == "code" else "agent_query")
    if save and not out["not_found"]:
        out["saved"] = str(wiki.save_answer(question, out["answer_text"]))
    return out


class Conversation:
    """A discussion with one agent session kept open across questions (ADR-0019).

    The first question gets the full prompt; follow-ups only the question (plus attachments, focus and a note about
    wiki pages changed by an ingest since the last answer). `resume` reopens a saved session id after a restart; if
    that fails, the new session gets a summary of the earlier turns instead. One question at a time.
    """

    def __init__(self, topic: str | None = None, history=None, runner=None, resume: str | None = None):
        self.topic, self.history, self.resume = topic, list(history or []), resume
        self.runner = runner or agent.AgentRunner()
        self.live = None
        self.changed: set[str] = set()
        self.lock = threading.Lock()
        self.used = time.time()

    @property
    def session_id(self) -> str | None:
        return getattr(self.live, "id", None) if self.live else self.resume

    def wiki_changed(self, paths) -> None:
        self.changed |= {str(p).replace("\\", "/") for p in paths}  # wiki/... as in the prompts, also on Windows

    def ask(self, question: str, attachments=(), focus: str = "wiki", progress=None) -> dict:
        from kb.knowledge import wiki
        with self.lock:
            if self.live is not None:
                self.live.stopped = False  # a new question: a Stop from now on counts (a new session starts unstopped)
            self.used = time.time()
            t0 = time.perf_counter()
            inst = catalog.instance()
            wiki.ensure_skeleton()
            fresh = self.live is None
            if fresh:
                rs = [r for r in repos() if r["exists"]]
                self.live = self.runner.open(agent.model_for("query"), inst, read_roots=[r["path"] for r in rs],
                                             tools=jira_tools() + git_tools(), resume=self.resume)
            if fresh and not getattr(self.live, "resumed", False):
                task = agent.prompt("chat", question=question, context=_context(self.history, self.topic, attachments, focus))
            else:
                task = agent.prompt("chat-followup", question=question, context="\n".join(_turn(attachments, focus, self.changed)))
            try:
                res = self.live.send(task, list(attachments), progress=progress)
            except Exception:
                self.close()  # the next question starts a new session with the history
                raise
            self.changed = set()
            out = _finish(question, res, focus, attachments, t0, "agent_discussion")
            out["session"] = "new" if fresh and not getattr(self.live, "resumed", False) else ("resumed" if fresh else "continued")
            out["stopped"] = bool(getattr(self.live, "stopped", False))
            self.history.append({"question": question, "answer_text": out["answer_text"]})
            return out

    def stop(self) -> bool:
        """Stop the answer in progress (called from another thread). False if nothing is running."""
        live = self.live
        if not live or not self.lock.locked() or not hasattr(live, "abort"):
            return False
        live.abort()
        return True

    def close(self) -> None:
        live, self.live = self.live, None
        if live:
            self.resume = getattr(live, "id", None) or self.resume
            live.close()
