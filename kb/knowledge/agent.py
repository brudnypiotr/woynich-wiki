"""The model writes the wiki (Karpathy LLM Wiki pattern, as in the claude-obsidian `wiki-ingest` skill).

One agent session per task (ingest a source, answer a question, lint); a discussion keeps one session open
across its questions (LiveSession, ADR-0019). The model gets file tools and decides what
to read and which pages to create or update. Scripts do the plumbing around it: register and extract the source,
run the session inside a sandbox, check the result, commit, roll back on failure.

Sandbox (enforced in code for every tool call, not by the prompt):
  - tools: view, glob, grep/rg (read) and create, edit, apply_patch (write); no shell, web, MCP or memory;
  - read: only inside the instance folder;
  - write: only inside instance/wiki/ (or nothing, for questions).
"""
from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from kb.core import config

READ_TOOLS = {"view", "glob", "grep", "rg"}
WRITE_TOOLS = {"create", "edit", "apply_patch", "str_replace", "write"}
PATCH_FILE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", re.M)
PATH_KEYS = ("path", "paths", "file", "file_path", "filename", "file_name", "directory", "dir", "cwd")
PROMPTS = Path(__file__).resolve().parents[2] / "prompts"


def prompt(name: str, **values) -> str:
    text = (PROMPTS / f"{name}.md").read_text(encoding="utf-8")
    for k, v in values.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text


@dataclass
class Sandbox:
    root: Path
    write_dirs: tuple[str, ...] = ("wiki",)
    log: list[dict] = field(default_factory=list)
    read_roots: tuple = ()       # extra folders the model may read (code repositories), never write
    custom: tuple = ()           # names of our own tools (e.g. jira_get) the model may call
    progress: object = None      # progress(step, detail): live view of what the model reads and writes
    cancelled: object = None     # cancelled() -> bool: deny every further tool call so the model stops

    def _inside(self, p: str, sub: str | None = None) -> bool:
        base = (self.root / sub) if sub else self.root
        q = Path(p)
        q = q if q.is_absolute() else self.root / q
        try:
            q.resolve().relative_to(base.resolve())
            return True
        except (ValueError, OSError):
            return False

    def _readable(self, p: str) -> bool:
        if self._inside(p):
            return True
        q = Path(p)
        if not q.is_absolute():
            return False
        for r in self.read_roots:
            try:
                q.resolve().relative_to(Path(r).resolve())
                return True
            except (ValueError, OSError):
                pass
        return False

    def _rel(self, p: str) -> str:
        try:
            q = Path(p)
            return str((q if q.is_absolute() else self.root / q).resolve().relative_to(self.root.resolve()))
        except (ValueError, OSError):
            return p

    def paths_in(self, tool: str, args) -> list[str]:
        found: list[str] = []
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {"input": args}
        if not isinstance(args, dict):
            return found
        for k, v in args.items():
            if k.lower() in PATH_KEYS:
                found += [v] if isinstance(v, str) else [x for x in v if isinstance(x, str)] if isinstance(v, list) else []
            if isinstance(v, str) and "*** " in v:
                found += [m.strip() for m in PATCH_FILE.findall(v)]
        return found

    def decide(self, tool: str, args) -> tuple[bool, str]:
        """Policy for one tool call: (allowed, reason)."""
        paths = self.paths_in(tool, args)
        if tool in self.custom:
            return True, "custom tool"
        if tool in READ_TOOLS:
            bad = [p for p in paths if not self._readable(p)]
            return (not bad, f"reading outside the knowledge base and the configured repositories is not allowed: {bad[0]}" if bad else "read")
        if tool in WRITE_TOOLS:
            if not self.write_dirs:
                return False, "this task is read-only"
            if not paths:
                return False, "write without a file path"
            bad = [p for p in paths if not any(self._inside(p, d) for d in self.write_dirs)]
            return (not bad, f"you may only write inside {', '.join(d + '/' for d in self.write_dirs)}: {bad[0]}" if bad else "write")
        return False, f"tool {tool!r} is not available (no shell, web or other tools)"

    async def pre_tool_use(self, inp, invocation=None):
        tool = str(inp.get("toolName") or "")
        if self.cancelled and self.cancelled():
            self.log.append({"tool": tool, "ok": False, "why": "cancelled"})
            return {"permissionDecision": "deny", "permissionDecisionReason": "The user cancelled this task. Stop now and reply CANCELLED."}
        ok, why = self.decide(tool, inp.get("toolArgs"))
        if ok and self.progress:
            shown = ", ".join(self._rel(p) for p in self.paths_in(tool, inp.get("toolArgs"))[:2]) or tool
            self.progress("writing" if tool in WRITE_TOOLS else "reading", f"{tool} {shown}")
        self.log.append({"tool": tool, "ok": ok, "why": why, "paths": [self._rel(p) for p in self.paths_in(tool, inp.get("toolArgs"))[:3]]})
        if ok:
            return {"permissionDecision": "allow"}
        return {"permissionDecision": "deny", "permissionDecisionReason": why}

    def on_permission(self, req, invocation=None):
        """Second line of defence: the runtime may still ask for permission; apply the same path rules."""
        from copilot.rpc import PermissionDecisionApproveOnce, PermissionDecisionReject
        from copilot.session_events import PermissionRequestCustomTool, PermissionRequestRead, PermissionRequestWrite
        if isinstance(req, PermissionRequestCustomTool) and req.tool_name in self.custom:
            return PermissionDecisionApproveOnce()
        if isinstance(req, PermissionRequestRead) and self._readable(req.path):
            return PermissionDecisionApproveOnce()
        if isinstance(req, PermissionRequestWrite) and any(self._inside(req.file_name, d) for d in self.write_dirs):
            return PermissionDecisionApproveOnce()
        self.log.append({"tool": type(req).__name__, "ok": False, "why": "permission rejected"})
        return PermissionDecisionReject(feedback="Not allowed: read only inside the knowledge base, write only inside wiki/.")


@dataclass
class AgentResult:
    reply: str
    seconds: float
    model: str
    tokens_in: int | None
    tokens_out: int | None
    premium: float | None
    tools: list[dict]
    credits: float | None = None   # GitHub AI credits (usage-based billing); total_nano_aiu / 1e9


def _quiet(lp, ctx):  # events the SDK cannot parse (attachment echo, newer runtime's shutdown types): harmless
    from kb.llm.adapters import quiet_sdk_noise
    quiet_sdk_noise(lp, ctx)


def _session_kwargs(box: Sandbox, model: str, root: Path, tools, streaming: bool = False) -> dict:
    # reasoning_summary: without it the runtime sends no thinking events (the CLI asks for it itself); "detailed",
    # not "concise": concise is only headings ("Analyzing code…"), detailed says what the model weighed
    kw = dict(on_permission_request=box.on_permission, hooks={"on_pre_tool_use": box.pre_tool_use},
              available_tools=sorted(READ_TOOLS | (WRITE_TOOLS if box.write_dirs else set()) | set(box.custom)),
              enable_skills=False, skip_custom_instructions=True, enable_config_discovery=False, working_directory=str(root),
              reasoning_summary="detailed")
    if streaming:
        kw["streaming"] = True
    if model and model != "auto":
        kw["model"] = model
    if tools:
        kw["tools"] = list(tools)
    return kw


async def _usage(session) -> tuple:
    """(tokens in, tokens out, premium requests, AI credits) of the session so far."""
    try:
        m = await session.rpc.usage.get_metrics()
        nano = getattr(m, "total_nano_aiu", None)
        return (sum((x.usage.input_tokens or 0) for x in m.model_metrics.values()),
                sum((x.usage.output_tokens or 0) for x in m.model_metrics.values()),
                getattr(m, "total_premium_request_cost", None), None if nano is None else nano / 1e9)
    except Exception:
        return None, None, None, None


def _reply(ev) -> str:
    data = getattr(ev, "data", None)
    return getattr(data, "content", None) or str(data if data is not None else ev)


class AgentRunner:
    """Runs agent sessions with the Copilot SDK. Tests replace it with a scripted runner."""

    def __init__(self, timeout: int | None = None):
        self.timeout = timeout or int((config.load("models").get("agent") or {}).get("timeout_s", 1800))

    def run(self, task_prompt: str, model: str, root: Path, write_dirs=("wiki",), progress=None, cancelled=None,
            read_roots=(), tools=(), attachments=()) -> AgentResult:
        return asyncio.run(self._run(task_prompt, model, root, tuple(write_dirs), progress, cancelled,
                                     tuple(read_roots), list(tools), list(attachments)))

    def open(self, model: str, root: Path, read_roots=(), tools=(), resume: str | None = None) -> "LiveSession":
        """A long read-only session for a discussion (ADR-0019): send() several questions, the model keeps its context."""
        return LiveSession(self.timeout, model, root, read_roots, tools, resume)

    async def _run(self, task_prompt, model, root, write_dirs, progress=None, cancelled=None, read_roots=(), tools=(),
                   attachments=()) -> AgentResult:
        from copilot import CopilotClient
        asyncio.get_running_loop().set_exception_handler(_quiet)
        box = Sandbox(Path(root), write_dirs, progress=progress, cancelled=cancelled, read_roots=read_roots,
                      custom=tuple(t.name for t in tools))
        t0 = time.perf_counter()
        client = CopilotClient(working_directory=str(root))
        await client.start()
        try:
            session = await client.create_session(**_session_kwargs(box, model, root, tools))
            att = [{"type": "file", "path": str(Path(a).resolve())} for a in attachments]
            ev = await session.send_and_wait(task_prompt, attachments=att or None, timeout=float(self.timeout))
            tin, tout, premium, credits = await _usage(session)
            return AgentResult(_reply(ev), round(time.perf_counter() - t0, 1), model, tin, tout, premium, box.log, credits)
        finally:
            await client.stop()


class LiveSession:
    """One agent session kept open across questions (a discussion). Read-only sandbox, same rules as `run`.

    The SDK is asynchronous; the session lives on its own event loop in a background thread, so the (threaded) web
    server and the terminal chat can call send() synchronously. `resume` reopens a session saved earlier (after a
    restart); `resumed` tells whether that worked, otherwise a new session was started.
    """

    def __init__(self, timeout: int, model: str, root: Path, read_roots=(), tools=(), resume: str | None = None):
        self.timeout, self.model, self.resumed = timeout, model, False
        self.box = Sandbox(Path(root), (), read_roots=tuple(read_roots), custom=tuple(t.name for t in tools))
        self.loop = asyncio.new_event_loop()
        self.loop.set_exception_handler(_quiet)
        threading.Thread(target=self.loop.run_forever, daemon=True, name="kb-live-session").start()
        self._seen = (0, 0, 0.0, 0.0)
        self._thinking: dict[str, str] = {}
        self.stopped = False
        try:
            self._call(self._start(Path(root), list(tools), resume), 120)
        except Exception:
            self.close()
            raise

    def _call(self, coro, timeout=None):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    async def _start(self, root, tools, resume):
        from copilot import CopilotClient
        self.client = CopilotClient(working_directory=str(root))
        await self.client.start()
        kw = _session_kwargs(self.box, self.model, root, tools, streaming=True)
        if resume:
            try:
                self.session = await self.client.resume_session(resume, **kw)
                self.resumed = True
            except Exception:
                self.session = None
        if not self.resumed:
            self.session = await self.client.create_session(**kw)
        self.id = getattr(self.session, "session_id", None) or getattr(self.session, "id", None)
        try:
            self.session.on(self._event)
        except Exception:
            pass
        tin, tout, prem, cred = await _usage(self.session)
        self._seen = (tin or 0, tout or 0, prem or 0.0, cred or 0.0)

    def _event(self, ev) -> None:
        """Thinking and intent from the runtime, for the live view (tool calls come from the sandbox hook)."""
        kind = str(getattr(getattr(ev, "type", None), "value", getattr(ev, "type", "")))
        data = getattr(ev, "data", None)
        if kind == "assistant.message" and getattr(data, "content", None):
            self._final = data.content  # with streaming on, keep the answer even if send_and_wait returns no message
        elif kind == "assistant.message_delta" and getattr(data, "delta_content", None):
            self._partial += data.delta_content
        say = self.box.progress
        if not say:
            return
        if kind == "assistant.reasoning_delta" and getattr(data, "delta_content", None):
            rid = getattr(data, "reasoning_id", "")
            self._thinking[rid] = self._thinking.get(rid, "") + data.delta_content
            say("thinking", self._thinking[rid].strip())  # the live view replaces the growing entry
        elif kind == "assistant.reasoning" and getattr(data, "content", None):
            say("thinking", data.content.strip())
        elif kind == "assistant.intent" and getattr(data, "intent", None):
            say("intent", data.intent.strip())

    async def _send(self, prompt, attachments):
        self._final, self._partial, self._thinking = None, "", {}
        att = [{"type": "file", "path": str(Path(a).resolve())} for a in attachments]
        try:
            ev = await self.session.send_and_wait(prompt, attachments=att or None, timeout=float(self.timeout))
        except Exception:
            if not self.stopped:
                raise
            ev = None
        if self.stopped:  # keep what the model had written, mark the rest as stopped
            reply = ((self._final or self._partial or "").strip() + "\n\n_(stopped by the user)_").strip()
        else:
            reply = getattr(getattr(ev, "data", None), "content", None) or self._final or self._partial or _reply(ev)
        return reply, await _usage(self.session)

    def abort(self) -> bool:
        """Stop the answer being written (the session stays usable for the next question)."""
        self.stopped = True
        try:
            self._call(self.session.abort(), 15)
            return True
        except Exception:
            return False  # the sandbox still denies every further tool call

    def send(self, prompt: str, attachments=(), progress=None, cancelled=None) -> AgentResult:
        self.stopped = False
        self.box.progress = progress
        self.box.cancelled = lambda: self.stopped or bool(cancelled and cancelled())
        n, t0 = len(self.box.log), time.perf_counter()
        reply, now = self._call(self._send(prompt, list(attachments)), self.timeout + 60)
        # the runtime reports totals for the session: keep only this question's share
        seen = self._seen
        self._seen = tuple(v if v is not None else o for v, o in zip(now, seen))
        d = [None if v is None else (v - o if v >= o else v) for v, o in zip(now, seen)]
        return AgentResult(reply, round(time.perf_counter() - t0, 1), self.model, d[0], d[1], d[2], self.box.log[n:], d[3])

    def close(self) -> None:
        try:
            if getattr(self, "client", None):
                self._call(self.client.stop(), 30)
        except Exception:
            pass
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)


def model_for(task: str) -> str:
    from kb.llm.gateway import Gateway
    return Gateway(adapter="fake").model_for(task)[1]


def meter(task: str, res: AgentResult | None, source_id: str | None = None, error: str | None = None) -> None:
    ev = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "task": task, "stage": task, "source_id": source_id,
          "adapter": "copilot-sdk-agent", "model": res.model if res else None, "tier": None,
          "tokens_in": res.tokens_in if res else None, "tokens_out": res.tokens_out if res else None, "cost": None,
          "premium": res.premium if res else None, "credits": res.credits if res else None, "duration_s": res.seconds if res else None, "ok": error is None, "error": error,
          "tool_calls": len(res.tools) if res else None, "denied": sum(1 for t in res.tools if not t["ok"]) if res else None}
    p = config.paths().metering
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")
