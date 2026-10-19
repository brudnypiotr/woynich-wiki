"""Settings for `kb serve`: models, GitHub Copilot sign-in, keys and tokens, instance profile.

Changes go to the instance copies (instance/config/models.yaml, profile.yaml), which override the blueprint defaults
key by key, so the blueprint stays untouched. Secrets go to the secret store (Windows Credential Manager via keyring)
and are never sent back to the browser: the UI only learns whether a secret is set.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import yaml

from kb.core import config, registry
from kb.core import secrets as secret_env

KNOWN_SECRETS = [
    {"name": "copilot-github-token", "label": "GitHub token for Copilot",
     "help": "Only needed when copilot login is not possible: a GitHub token with Copilot access (used as COPILOT_GITHUB_TOKEN)."},
    {"name": "jira-token", "label": "Jira token",
     "help": "Personal access token (Jira Data Center) or API token (Jira Cloud). Not needed if the Windows credential copilot-jira (jira-snapshot skill) exists."},
]
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
TIERS = ("basic", "standard", "premium")


def store():
    """The secret store (tests replace this function)."""
    return registry.create("secret_stores", "keyring")


def _inst(name: str) -> Path:
    return config.paths().instance / "config" / f"{name}.yaml"


def _read(name: str) -> dict:
    p = _inst(name)
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}


def _write(name: str, data: dict) -> None:
    p = _inst(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _secret_names() -> list[dict]:
    extra = [n for n in (_read("secrets").get("names") or []) if NAME.fullmatch(str(n))]
    known = {s["name"] for s in KNOWN_SECRETS}
    return KNOWN_SECRETS + [{"name": n, "label": n, "help": "Added in Settings."} for n in extra if n not in known]


def secrets_state() -> dict:
    try:
        st = store()
        items = [{**s, "set": bool(st.get(s["name"]))} for s in _secret_names()]
        return {"items": items, "error": None}
    except Exception as e:  # keyring not installed or locked
        return {"items": [{**s, "set": None} for s in _secret_names()], "error": f"{type(e).__name__}: {e}"[:300]}


def state() -> dict:
    m, prof = config.load("models"), config.load("profile")
    env = os.environ.get("KB_MODEL")
    tiers = {t: str(((m.get("tiers") or {}).get(t) or {}).get("model") or "auto") for t in TIERS}
    override = m.get("model_override")
    std = tiers.get((m.get("tasks") or {}).get("query", "standard"), "auto")
    jira = prof.get("jira") or {}
    return {
        "model": {"effective": env or override or std, "source": "env" if env else ("override" if override else "tiers"),
                  "override": override or "", "env": env, "tiers": tiers, "tasks": m.get("tasks") or {},
                  "timeout_s": int((m.get("agent") or {}).get("timeout_s") or 1800), "adapter": m.get("default_adapter")},
        "profile": {"title": (prof.get("instance") or {}).get("title") or "", "jira_base_url": jira.get("base_url") or "",
                    "jira_email": jira.get("email") or "",
                    "code_repos": _repos(), "architecture": str(prof.get("architecture") or "")},
        "secrets": secrets_state(),
        "copilot_cli": bool(shutil.which("copilot")),
        "files": {"models": str(_inst("models")), "profile": str(_inst("profile"))},
    }


REPO_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}")


def _repos() -> list[dict]:
    from kb.knowledge import chat
    return [{"name": r["name"], "role": r["role"], "path": str(r["path"]), "description": r["description"], "exists": r["exists"],
             "branch": r.get("branch"), "commit": r["commit"], "dirty": r["dirty"]} for r in chat.repos()]


def _save_repos(b: dict, data: dict) -> None:
    """Replace the list of code repositories (read-only for the assistant) and the architecture text."""
    if "list" in b:
        out, seen = [], set()
        for r in b["list"] or []:
            name, path = str(r.get("name") or "").strip(), str(r.get("path") or "").strip().strip('"')
            if not name and not path:
                continue
            if not REPO_NAME.fullmatch(name):
                raise ValueError(f"repository name {name!r}: letters, digits, dot, dash, underscore (it is used in citations)")
            if name.lower() in seen:
                raise ValueError(f"repository name {name!r} is used twice")
            if not path:
                raise ValueError(f"repository {name}: the folder is missing")
            seen.add(name.lower())
            item = {"name": name, "role": str(r.get("role") or "").strip()[:60] or None, "path": path,
                    "description": str(r.get("description") or "").strip()[:2000]}
            out.append({k: v for k, v in item.items() if v})
        data["code_repos"] = out
    if "architecture" in b:
        data["architecture"] = str(b["architecture"] or "").strip()[:6000] or None


def _model_id(v) -> str:
    v = str(v or "").strip()
    if len(v) > 80 or not re.fullmatch(r"[A-Za-z0-9._:/ -]*", v):
        raise ValueError(f"not a model id: {v!r}")
    return v


def save(body: dict) -> dict:
    if "model" in body:
        b, data = body["model"] or {}, _read("models")
        if "override" in b:
            data["model_override"] = _model_id(b["override"]) or None
        if "tiers" in b:
            tiers = data.setdefault("tiers", {})
            for t in TIERS:
                if t in b["tiers"]:
                    tiers.setdefault(t, {})["model"] = _model_id(b["tiers"][t]) or "auto"
        if "timeout_s" in b:
            s = int(b["timeout_s"])
            if not 60 <= s <= 4 * 3600:
                raise ValueError("agent timeout must be between 1 and 240 minutes")
            data.setdefault("agent", {})["timeout_s"] = s
        _write("models", data)
    if "profile" in body:
        b, data = body["profile"] or {}, _read("profile")
        if "title" in b:
            t = str(b["title"]).strip()[:120]
            if t:
                data.setdefault("instance", {})["title"] = t
        if "jira_base_url" in b or "jira_email" in b:
            url = str(b.get("jira_base_url") or "").strip().rstrip("/")
            if url and not re.fullmatch(r"https?://[^\s]+", url):
                raise ValueError("Jira URL must start with https://")
            j = data.setdefault("jira", {})
            j["base_url"] = url or None
            j["email"] = str(b.get("jira_email") or "").strip() or None
        _write("profile", data)
    if "repos" in body:
        data = _read("profile")
        _save_repos(body["repos"] or {}, data)
        _write("profile", data)
    return state()


def secret_set(name: str, value: str) -> dict:
    if not NAME.fullmatch(name or ""):
        raise ValueError("name: lowercase letters, digits and dashes")
    value = (value or "").strip()
    if not value:
        raise ValueError("value is empty")
    store().set(name, value)
    if name in secret_env.ENV:
        os.environ[secret_env.ENV[name]] = value  # this server uses it at once
    if name not in {s["name"] for s in _secret_names()}:
        data = _read("secrets")
        data["names"] = sorted(set(data.get("names") or []) | {name})
        _write("secrets", data)
    return secrets_state()


def secret_delete(name: str) -> dict:
    if not NAME.fullmatch(name or ""):
        raise ValueError("bad name")
    st = store()
    old = st.get(name)
    st.delete(name)
    var = secret_env.ENV.get(name)
    if var and old and os.environ.get(var) == old:
        os.environ.pop(var, None)
    data = _read("secrets")
    if name in (data.get("names") or []):
        data["names"] = [n for n in data["names"] if n != name]
        _write("secrets", data)
    return secrets_state()


def _plain(obj):
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    fields = {k: getattr(obj, k) for k in dir(obj) if not k.startswith("_") and not callable(getattr(obj, k, None))}
    return {k: _plain(v) for k, v in fields.items()} if fields else str(obj)


def models_available(gw) -> list[dict]:
    lister = getattr(gw.llm.inner, "list_models", None)
    if not lister:
        raise RuntimeError(f"the {gw.llm.inner.name if hasattr(gw.llm.inner, 'name') else 'current'} adapter cannot list models")
    return lister()


def account(gw) -> dict:
    inner, out = gw.llm.inner, {}
    for key, fn in (("auth", "auth_status"), ("quota", "quota")):
        f = getattr(inner, fn, None)
        if not f:
            out[key] = None
            continue
        try:
            out[key] = _plain(f())
        except Exception as e:
            out[key] = {"error": f"{type(e).__name__}: {e}"[:300]}
    out["token_from_store"] = bool(os.environ.get("COPILOT_GITHUB_TOKEN"))
    return out


def login() -> dict:
    """Start `copilot login` (GitHub device flow) in its own console window on Windows."""
    cli = shutil.which("copilot")
    if not cli:
        return {"ok": False, "message": "GitHub Copilot CLI not found. Install it, or store a GitHub token below."}
    if os.name == "nt":
        subprocess.Popen([cli, "login"], creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        return {"ok": True, "message": "A console window opened: follow the steps there, then press Check sign-in."}
    return {"ok": False, "message": "Run `kb login` in a terminal, then press Check sign-in."}
