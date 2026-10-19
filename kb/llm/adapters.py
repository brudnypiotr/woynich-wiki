"""LLM adapters. All of them run the model WITHOUT tool access: source text is data, never instructions."""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from kb.core.ports import LLM, LLMResult

# Windows limits a command line to ~32k characters; long prompts must go through the SDK.
CLI_MAX_PROMPT_CHARS = 28000


_NOTED: set[str] = set()


def _run(coro):
    async def main():
        asyncio.get_running_loop().set_exception_handler(quiet_sdk_noise)
        return await coro
    return asyncio.run(main())


def quiet_sdk_noise(loop, ctx) -> None:
    """Asyncio exception handler for Copilot SDK sessions. A runtime newer than the SDK sends events the SDK cannot
    parse (e.g. shutdown type 'destroy'); the SDK drops such an event inside a callback and the work continues.
    Print one short line per kind instead of a traceback each time."""
    exc = ctx.get("exception")
    if exc is not None and "handle_notification" in str(ctx.get("handle", "")) and isinstance(exc, (AssertionError, ValueError, KeyError, TypeError)):
        kind = f"{type(exc).__name__}: {exc}"[:120]
        if kind not in _NOTED:
            _NOTED.add(kind)
            print(f"note: the Copilot runtime sent an event this SDK version does not know ({kind}); ignored", flush=True)
        return
    loop.default_exception_handler(ctx)


class FakeAdapter(LLM):
    """Deterministic adapter for tests: returns a canned reply or echoes a JSON wrapper of the prompt."""
    name = "fake"

    def __init__(self, reply: str | None = None, **_):
        self.reply = reply

    def complete(self, prompt, model, attachments=None, response_schema=None):
        text = self.reply if self.reply is not None else json.dumps({"echo": prompt[:80]})
        return LLMResult(text=text, model=model or "fake", tokens_in=len(prompt) // 4, tokens_out=len(text) // 4)


class CopilotCLIAdapter(LLM):
    """`copilot -p <prompt> --output-format json --model <m> --usage-output-file <f>` (non-interactive prompt mode).

    No --allow-* flags are passed, so the CLI cannot approve tool use in prompt mode.
    """
    name = "copilot-cli"

    def __init__(self, command: str = "copilot", extra_args: list[str] | None = None, timeout: int = 600, **_):
        self.command = command
        self._argv = None
        self.extra_args = list(extra_args or [])
        self.timeout = timeout

    def argv(self) -> list[str]:
        """How to start the CLI. On Windows an npm install is a `copilot.CMD` shim: Python cannot start it by name, and
        running it through cmd.exe would mangle long prompts (quoting, 8 KB limit). Run its JavaScript with node instead."""
        if self._argv is None:
            path = shutil.which(self.command) or self.command
            self._argv = [path]
            if path.lower().endswith((".cmd", ".bat")):
                import re
                from pathlib import Path
                shim = Path(path)
                m = re.search(r'%~?dp0%?\\?([^"%]+?\.(?:js|mjs|cjs))', shim.read_text(encoding="utf-8", errors="replace"), re.I)
                if m:
                    script = shim.parent / m.group(1).lstrip("\\")
                    node = shim.parent / "node.exe"
                    self._argv = [str(node) if node.exists() else (shutil.which("node") or "node"), str(script)]
        return self._argv

    def available(self) -> bool:
        return shutil.which(self.command) is not None

    def _supports(self, flag: str) -> bool:
        """CLI versions differ (e.g. --usage-output-file appeared in 1.0.81); detect from --help once."""
        if not hasattr(self, "_help"):
            try:
                r = subprocess.run([*self.argv(), "--help"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
                self._help = r.stdout + r.stderr
            except Exception:
                self._help = ""
        return flag in self._help

    def complete(self, prompt, model, attachments=None, response_schema=None):
        if len(prompt) > CLI_MAX_PROMPT_CHARS:
            raise ValueError(f"prompt has {len(prompt)} chars; command-line limit is ~{CLI_MAX_PROMPT_CHARS}. Use the copilot-sdk adapter.")
        with tempfile.TemporaryDirectory() as td:
            usage = Path(td) / "usage.json"
            cmd = [*self.argv(), "-p", prompt, *self.extra_args]
            if self._supports("--output-format"):
                cmd += ["--output-format", "json"]
            if self._supports("--usage-output-file"):
                cmd += ["--usage-output-file", str(usage)]
            if model and model != "auto":
                cmd += ["--model", model]
            for a in attachments or []:
                cmd += ["--attachment", str(a)]
            r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=self.timeout)
            if r.returncode != 0:
                raise RuntimeError(f"copilot exited {r.returncode}: {r.stderr.strip()[:500]}")
            events = []
            for line in r.stdout.splitlines():
                if line.strip().startswith("{"):
                    try:
                        events.append(json.loads(line))
                    except ValueError:
                        pass
            usage_data = json.loads(usage.read_text(encoding="utf-8")) if usage.exists() else None
        tin, tout = _sum_tokens(usage_data)
        return LLMResult(text=_final_text(events) or r.stdout.strip(), model=model, tokens_in=tin, tokens_out=tout,
                         raw={"events": events, "usage": usage_data})


class CopilotSDKAdapter(LLM):
    """GitHub Copilot SDK for Python (`pip install github-copilot-sdk`, Python 3.11+, bundles the CLI).

    Isolation for ingest (source text is data): no tools at all (`available_tools=[]`), no skills, no custom
    instructions or config discovery, an empty temporary working directory, and every permission request rejected.
    """
    name = "copilot-sdk"

    def __init__(self, timeout: int = 600, **_):
        self.timeout = timeout

    async def _run(self, prompt, model, attachments, response_schema=None):
        import tempfile
        from copilot import CopilotClient  # optional dependency
        with tempfile.TemporaryDirectory() as workdir:
            client = CopilotClient(working_directory=workdir)
            await client.start()
            try:
                kwargs = dict(on_permission_request=_reject_permission, available_tools=[], enable_skills=False,
                              skip_custom_instructions=True, enable_config_discovery=False, working_directory=workdir)
                if model and model != "auto":
                    kwargs["model"] = model
                session = await client.create_session(**kwargs)
                send = {"timeout": float(self.timeout)}
                if response_schema:
                    send["response_schema"] = response_schema
                event = await session.send_and_wait(prompt, **send)
                data = getattr(event, "data", None)
                text = getattr(data, "content", None)
                if text is None:
                    text = str(data if data is not None else event)
                tin = tout = premium = None
                try:
                    m = await session.rpc.usage.get_metrics()
                    tin = sum((mm.usage.input_tokens or 0) for mm in m.model_metrics.values())
                    tout = sum((mm.usage.output_tokens or 0) for mm in m.model_metrics.values())
                    premium = getattr(m, "total_premium_request_cost", None)
                except Exception:
                    premium = None
                return LLMResult(text=text, model=model, tokens_in=tin, tokens_out=tout, raw={"premium": premium})
            finally:
                await client.stop()

    def complete(self, prompt, model, attachments=None, response_schema=None):
        return _run(self._run(prompt, model, attachments, response_schema))

    def quota(self) -> dict:
        """Remaining Copilot entitlement of the signed-in user (premium requests, chat, completions)."""
        async def go():
            from copilot import CopilotClient
            from copilot.rpc import AccountGetQuotaRequest
            client = CopilotClient()
            await client.start()
            try:
                res = await client.rpc.account.get_quota(AccountGetQuotaRequest())
                return {k: {"used": getattr(v, "used_requests", None), "entitlement": getattr(v, "entitlement_requests", None),
                            "remaining_pct": getattr(v, "remaining_percentage", None), "resets": str(getattr(v, "reset_date", "") or "")}
                        for k, v in (res.quota_snapshots or {}).items()}
            finally:
                await client.stop()
        return _run(go())

    def usage_quota(self) -> dict:
        """Billing state from the runtime: plan, token-based billing (AI credits) and quota snapshots in their own
        units, with reset times. Opens a session but sends no prompt, so it costs nothing."""
        async def go():
            import tempfile
            from copilot import CopilotClient
            with tempfile.TemporaryDirectory() as wd:
                client = CopilotClient(working_directory=wd)
                await client.start()
                try:
                    session = await client.create_session(on_permission_request=_reject_permission, available_tools=[],
                                                          enable_skills=False, skip_custom_instructions=True,
                                                          enable_config_discovery=False, working_directory=wd)
                    try:
                        q = await session.rpc.quota.refresh()
                    except Exception:
                        q = await session.rpc.quota.get()
                    snaps = {k: {"entitlement": v.entitlement_requests, "used": v.used_requests,
                                 "remaining_pct": v.remaining_percentage, "unlimited": v.is_unlimited_entitlement,
                                 "overage": v.overage, "reset_ms": v.reset_date_epoch_ms, "tbb": v.token_based_billing}
                             for k, v in (q.snapshots or {}).items()}
                    try:
                        await client.delete_session(session.session_id)
                    except Exception:
                        pass
                    return {"tbb": q.is_tbb_user, "plan": str(getattr(q.plan_tier, "value", q.plan_tier)), "snapshots": snaps}
                finally:
                    await client.stop()
        return _run(go())

    def auth_status(self):
        async def go():
            from copilot import CopilotClient
            client = CopilotClient()
            await client.start()
            try:
                return await client.get_auth_status()
            finally:
                await client.stop()
        return _run(go())

    def list_models(self) -> list[dict]:
        async def go():
            from copilot import CopilotClient
            client = CopilotClient()
            await client.start()
            try:
                models = await client.list_models()
                return [{"id": m.id, "name": m.name, "policy": getattr(getattr(m, "policy", None), "state", None)} for m in models]
            finally:
                await client.stop()
        return _run(go())


def _reject_permission(request, invocation):
    """Never approve anything: woynich-wiki runs the model without tools."""
    from copilot.generated.rpc import PermissionDecisionReject
    return PermissionDecisionReject(feedback="woynich-wiki runs the model without tools")


def _final_text(events: list[dict]) -> str | None:
    """Last `assistant.message` content in the JSONL event stream (never reasoning or streaming deltas);
    falls back to a `result` event."""
    final = fallback = None
    for ev in events:
        t = str(ev.get("type", ""))
        if "reasoning" in t or "delta" in t:
            continue
        data = ev.get("data") if isinstance(ev.get("data"), dict) else ev
        content = data.get("content") or data.get("text") or data.get("message")
        if not isinstance(content, str) or not content.strip():
            continue
        if t == "assistant.message":
            final = content
        elif t == "result" or "assistant" in t:
            fallback = content
    return final or fallback


def _sum_tokens(obj) -> tuple[int | None, int | None]:
    """Tokens from the CLI usage file. It repeats the same numbers in modelMetrics, agentMetrics and
    providerModelMetrics, so read modelMetrics only; walk the whole object only for other formats."""
    if isinstance(obj, dict) and isinstance(obj.get("modelMetrics"), dict):
        tin = sum(int((m.get("usage") or {}).get("inputTokens") or 0) for m in obj["modelMetrics"].values())
        tout = sum(int((m.get("usage") or {}).get("outputTokens") or 0) for m in obj["modelMetrics"].values())
        return tin, tout
    tin = tout = 0
    seen = False

    def walk(o):
        nonlocal tin, tout, seen
        if isinstance(o, dict):
            for k, v in o.items():
                kl = k.lower().replace("_", "")
                if isinstance(v, (int, float)) and kl in ("inputtokens", "prompttokens"):
                    tin += int(v); seen = True
                elif isinstance(v, (int, float)) and kl in ("outputtokens", "completiontokens"):
                    tout += int(v); seen = True
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(obj)
    return (tin, tout) if seen else (None, None)
