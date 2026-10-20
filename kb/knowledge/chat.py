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

from kb.core import config
from kb.knowledge import agent, catalog
from kb.knowledge import tools as agent_tools
from kb.knowledge.tools.git import tools as git_tools  # noqa: F401  (kept for callers of chat.git_tools)
from kb.knowledge.tools.jira import jira_config, tools as jira_tools  # noqa: F401


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


def all_tools() -> list:
    """Every tool the assistant may call besides reading files (kb.knowledge.tools: search, Jira, Git, code)."""
    return agent_tools.all_tools()


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
    else:
        lines.append("No code repositories are configured.")
    lines += agent_tools.context_lines()  # one line per tool group: search, Jira, Git, code
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
                     read_roots=[r["path"] for r in rs], tools=all_tools(), attachments=list(attachments))
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
                                             tools=all_tools(), resume=self.resume)
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
