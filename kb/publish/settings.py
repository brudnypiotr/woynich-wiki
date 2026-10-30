"""Settings for `kb serve`: models, GitHub Copilot sign-in, keys and tokens, instance profile.

Changes go to the instance copies (instance/config/models.yaml, profile.yaml), which override the blueprint defaults
key by key, so the blueprint stays untouched. Secrets go to the secret store (Windows Credential Manager via keyring)
and are never sent back to the browser: the UI only learns whether a secret is set.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

import yaml

from kb.core import config, registry
from kb.core import secrets as secret_env
from kb.llm.adapters import find_copilot_cli

TOKEN_STEPS = ("Create a fine-grained token at https://github.com/settings/personal-access-tokens/new: "
               "1) Resource owner = your personal account (not the organisation); 2) Expiration = one year (Custom); "
               "3) Repository access = Public repositories; "
               "4) Permissions → the Account tab (not Repositories) → Add permissions → Copilot Requests; "
               "5) Generate token and paste it here. Classic tokens (ghp_…) do not work with Copilot.")
TOKEN_WARN_DAYS = 7
KNOWN_SECRETS = [
    {"name": "copilot-github-token", "label": "GitHub token for Copilot",
     "help": "Only needed when the browser sign-in is not possible (used as COPILOT_GITHUB_TOKEN). " + TOKEN_STEPS},
    {"name": "jira-token", "label": "Jira token",
     "help": "Personal access token (Jira Data Center) or API token (Jira Cloud). Not needed if the Windows credential copilot-jira (jira-snapshot skill) exists."},
]
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
TIERS = ("basic", "standard", "premium")


_STORE = None


def store():
    """The secret store (tests replace this function). Created once: loading keyring is slow on Windows."""
    global _STORE
    if _STORE is None:
        _STORE = registry.create("secret_stores", "keyring")
    return _STORE


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


def effective_model() -> str:
    """The model in use, cheaply (the status bar asks every few seconds)."""
    m = config.load("models")
    tiers = m.get("tiers") or {}
    q = (m.get("tasks") or {}).get("query", "standard")
    return os.environ.get("KB_MODEL") or m.get("model_override") or str((tiers.get(q) or {}).get("model") or "auto")


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
                  "recommended": str(m.get("recommended_model") or ""),
                  "timeout_s": int((m.get("agent") or {}).get("timeout_s") or 1800), "adapter": m.get("default_adapter")},
        "profile": {"title": (prof.get("instance") or {}).get("title") or "", "jira_base_url": jira.get("base_url") or "",
                    "jira_email": jira.get("email") or "",
                    "code_repos": _repos(), "architecture": str(prof.get("architecture") or "")},
        "secrets": secrets_state(),
        "copilot_cli": bool(find_copilot_cli()),
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
            email = str(b.get("jira_email") or "").strip()
            if not url or not email:  # both required (the e-mail signs in to Jira Cloud and names the user everywhere)
                raise ValueError("Jira URL and Jira e-mail are required")
            if not re.fullmatch(r"https?://[^\s]+", url):
                raise ValueError("Jira URL must start with https://")
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
                raise ValueError("Jira e-mail is not an e-mail address")
            j = data.setdefault("jira", {})
            j["base_url"], j["email"] = url, email
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
    if name == "copilot-github-token" and value.startswith("ghp_"):
        raise ValueError("this is a classic token: Copilot does not accept it. " + TOKEN_STEPS)
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


_EXPIRY: dict = {"at": 0.0, "token": None, "data": None}


def _parse_expiry(header: str):
    """GitHub-Authentication-Token-Expiration, e.g. "2027-10-27 09:15:00 UTC" (or with a +hhmm offset)."""
    from datetime import datetime, timezone
    m = re.match(r"\s*(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})\s*(UTC|[+-]\d{2}:?\d{2})?", header or "")
    if not m:
        return None
    off = (m.group(3) or "UTC").replace(":", "")
    when = datetime.strptime(f"{m.group(1)} {m.group(2)} {'+0000' if off == 'UTC' else off}", "%Y-%m-%d %H:%M:%S %z")
    return when.astimezone(timezone.utc)


def token_expiry(fetch=None, now=None) -> dict | None:
    """When the stored GitHub token for Copilot expires. GitHub says it in a response header on any API call made
    with the token (one GET /user, no AI credits). Asked again every 6 hours or when the token changes.
    None: no token, or GitHub could not be reached. {"expires": None} : a token without an expiry date."""
    import urllib.request
    from datetime import datetime, timezone
    token = os.environ.get("COPILOT_GITHUB_TOKEN")
    if not token:
        return None
    if _EXPIRY["token"] != token or time.time() - _EXPIRY["at"] > 6 * 3600:
        def get(tok):
            req = urllib.request.Request("https://api.github.com/user", headers={
                "Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json", "User-Agent": "woynich-wiki"})
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.headers.get("GitHub-Authentication-Token-Expiration")
        try:
            header = (fetch or get)(token)
            when = _parse_expiry(header) if header else None
            _EXPIRY.update(at=time.time(), token=token, data={"expires": when.isoformat() if when else None})
        except Exception:
            return None  # offline or proxy: try again next time, never block the app
    data = dict(_EXPIRY["data"] or {})
    if data.get("expires"):
        left = datetime.fromisoformat(data["expires"]) - (now or datetime.now(timezone.utc))
        data["days_left"] = max(0, left.days)
        data["expired"] = left.total_seconds() <= 0
        data["warn"] = left.days < TOKEN_WARN_DAYS
    return data


def check(gw, what: str = "all") -> dict:
    """Heartbeat of the credentials, no premium request: GitHub Copilot sign-in and one Jira /myself call.
    Each entry: ok (True / False / None = not configured), detail."""
    out = {}
    if what in ("all", "copilot"):
        f = getattr(gw.llm.inner, "auth_status", None)
        if not f:
            out["copilot"] = {"ok": None, "detail": f"the {getattr(gw.llm.inner, 'name', 'current')} adapter has no sign-in"}
        else:
            try:
                st = _plain(f()) or {}
                ok = bool(st.get("is_authenticated", st.get("isAuthenticated")))
                who = st.get("login") or st.get("user") or ""
                how = st.get("auth_type") or st.get("authType") or ""
                via = " (GitHub token from Keys and tokens)" if os.environ.get("COPILOT_GITHUB_TOKEN") else ""
                out["copilot"] = {"ok": ok, "detail": (f"signed in{' as ' + who if who else ''}{' · ' + how if how else ''}{via}" if ok
                                                       else (st.get("status_message") or st.get("statusMessage") or "not signed in: run kb login"))}
                exp = token_expiry() if via else None
                if ok and exp and exp.get("expires"):
                    out["copilot"]["detail"] += (" · token expired" if exp["expired"]
                                                 else f" · token expires on {exp['expires'][:10]} ({exp['days_left']} days)")
                lister = getattr(gw.llm.inner, "list_models", None)
                if ok and lister:  # a token can sign in and still be refused on the first question: ask for real, at no cost
                    try:
                        lister()
                    except Exception as e:
                        msg = str(e)
                        out["copilot"] = {"ok": False, "detail": (f"signed in{' as ' + who if who else ''}, but Copilot refuses: {msg[:200]}"
                                                                  + (f". {TOKEN_STEPS}" if via or "permission" in msg.lower() else ""))}
            except Exception as e:
                out["copilot"] = {"ok": False, "detail": f"{type(e).__name__}: {e}"[:300]}
    if what in ("all", "jira"):
        cfg = config.load("profile").get("jira") or {}
        if not cfg.get("base_url"):
            out["jira"] = {"ok": None, "detail": "not configured (Jira URL in Settings)"}
        else:
            try:
                from kb.connectors import jira
                me = jira.Jira(**cfg).whoami()
                out["jira"] = {"ok": True, "detail": f"authenticated as {me['name']}{' <' + me['email'] + '>' if me.get('email') else ''}"
                                                     f" · token from {me['source']}"}
            except Exception as e:
                out["jira"] = {"ok": False, "detail": (str(e) if isinstance(e, (PermissionError, RuntimeError)) else f"{type(e).__name__}: {e}")[:300]}
    return out


def _next_month_utc(now):
    from datetime import datetime, timezone
    return datetime(now.year + (now.month == 12), now.month % 12 + 1, 1, tzinfo=timezone.utc)


def usage(gw, now=None) -> dict:
    """Where we are in the billing cycle: the quota GitHub reports for this account (AI credits under usage-based
    billing, premium requests on legacy plans), the reset time (organisation plans: 1st of the month 00:00 UTC),
    days and working days left, and what this knowledge base used this month (metered)."""
    from datetime import datetime, timedelta, timezone
    now = now or datetime.now(timezone.utc)
    out = {"error": None, "plan": None, "unit": "AI credits", "entitlement": None, "used": None, "remaining_pct": None,
           "unlimited": False, "quota": None}
    f = getattr(gw.llm.inner, "usage_quota", None)
    reset = None
    if f:
        try:
            q = f()
            snaps = q.get("snapshots") or {}
            pick = (next((k for k, v in snaps.items() if v.get("tbb")), None)
                    or next((k for k in snaps if "premium" in k or "credit" in k), None)
                    or next((k for k, v in snaps.items() if not v.get("unlimited")), None))
            out.update(plan=q.get("plan"), unit="AI credits" if q.get("tbb") or (pick and snaps[pick].get("tbb")) else "premium requests")
            if pick:
                v = snaps[pick]
                out.update(quota=pick, entitlement=v["entitlement"], used=v["used"], remaining_pct=v["remaining_pct"],
                           unlimited=bool(v["unlimited"]))
                if v.get("reset_ms"):
                    reset = datetime.fromtimestamp(v["reset_ms"] / 1000, timezone.utc)
        except Exception as e:
            out["error"] = f"{type(e).__name__}: {e}"[:300]
    else:
        out["error"] = f"the {getattr(gw.llm.inner, 'name', 'current')} adapter reports no quota"
    reset = reset or _next_month_utc(now)
    first = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    kb_month = 0.0
    met = config.paths().metering
    if met.exists():
        for line in met.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
                if (e.get("credits") or 0) and datetime.fromisoformat(e["at"]) >= first:
                    kb_month += e["credits"]
            except (ValueError, KeyError, TypeError):
                pass
    today, end = now.date(), reset.date()
    business = sum(1 for i in range((end - today).days) if (today + timedelta(days=i)).weekday() < 5)
    out.update(reset=reset.isoformat(), days_left=max(0, (end - today).days), business_days_left=business,
               kb_month=round(kb_month, 2), checked_at=now.isoformat(timespec="seconds"))
    return out


def usage_estimate(u: dict) -> dict:
    """The last GitHub reading plus the AI credits this knowledge base metered since then (no runtime started)."""
    from datetime import datetime
    if not u or not u.get("checked_at"):
        return u
    since, met = 0.0, config.paths().metering
    checked = datetime.fromisoformat(u["checked_at"])
    if met.exists():
        for line in met.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
                if (e.get("credits") or 0) and datetime.fromisoformat(e["at"]) > checked:
                    since += e["credits"]
            except (ValueError, KeyError, TypeError):
                pass
    out = {**u, "since_check": round(since, 2), "kb_month": round((u.get("kb_month") or 0) + since, 2)}
    if since and out.get("used") is not None and out.get("entitlement") and not out.get("unlimited"):
        out["used"] = round(out["used"] + since, 2)
        out["remaining_pct"] = max(0.0, 100 - 100 * out["used"] / out["entitlement"])
    return out


def setup_state() -> dict:
    """First-run setup: done once Finish was pressed (instance/config/profile.yaml: setup.done_at), or when the instance
    already has sources (set up before the setup existed); what is configured."""
    from kb.knowledge import catalog
    prof = config.load("profile")
    return {"done": bool((prof.get("setup") or {}).get("done_at")) or bool(catalog.all_sources()),
            "jira": bool((prof.get("jira") or {}).get("base_url")), "repos": len(prof.get("code_repos") or [])}


def setup_done(done: bool = True) -> dict:
    data = _read("profile")
    if done:
        data.setdefault("setup", {})["done_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    else:
        data.pop("setup", None)
    _write("profile", data)
    return setup_state()


def login() -> dict:
    """Start `copilot login` (GitHub device flow) in its own console window on Windows."""
    cli = find_copilot_cli()
    if not cli:
        return {"ok": False, "message": "The browser sign-in needs the GitHub Copilot CLI and it is not on this PC (looked on PATH, "
                                        "winget, npm and VS Code). Use the GitHub token above instead (the button and the steps)."}
    if os.name == "nt":
        subprocess.Popen([cli, "login"], creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        return {"ok": True, "message": "A console window opened: follow the steps there, then press Check sign-in."}
    return {"ok": False, "message": "Run `kb login` in a terminal, then press Check sign-in."}
