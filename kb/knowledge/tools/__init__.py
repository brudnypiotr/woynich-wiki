"""Tools the assistant may call besides reading files, one module per group.

Each group module has:
    available() -> bool    whether it can work here (e.g. Jira configured, a code repository on disk)
    context()   -> str     one line for the prompt: what the tools are for (also said when not available)
    tools()     -> list    the tools, made with copilot.define_tool (+ @off_loop); called only when available()

To add a group: write a module here (copy jira.py or kb.py as a start), add its name to GROUPS, add a test in
tests/ (see test_git_tools.py) and a line to prompts/chat.md if the model needs a rule for when to use it. Tools are read-only:
the sandbox allows them by name (kb.knowledge.agent.Sandbox.custom), and they must never change files or systems.
Helpers shared by the repository tools are in repo.py (not a group).
"""
from __future__ import annotations

import importlib

GROUPS = ["kb", "jira", "git", "code"]


def off_loop(fn):
    """Run a blocking tool (network, git, disk) in a worker thread. The SDK calls a plain function on the session's
    event loop, so a slow tool (Jira pictures) froze the session: Stop could not reach it until the tool finished.
    Put it between @define_tool and the function; the signature and type hints stay those of the function."""
    import asyncio
    import functools

    @functools.wraps(fn)
    async def run(*args):
        return await asyncio.to_thread(fn, *args)
    return run


def _modules():
    return [importlib.import_module(f"kb.knowledge.tools.{g}") for g in GROUPS]


def all_tools() -> list:
    return [t for m in _modules() if m.available() for t in m.tools()]


def context_lines() -> list[str]:
    return [line for m in _modules() if (line := m.context())]
