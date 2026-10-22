"""The inbox: a folder the app's author shares in OneDrive for Business, synced on each user's laptop, where feedback
files and usage records land without the user sending anything. No admin rights, no Graph API: OneDrive uploads what
the app writes into the synced folder.

The author creates the folder, shares it with the team (can edit) and puts it in branding.json, shared as branding.zip:
    "inbox": {"folder": "Wiki Inbox", "share_url": "https://…sharepoint.com/…", "contact": "author@company.example"}
Each user adds it once to their OneDrive ("Add shortcut to My files"); it then appears as %OneDriveCommercial%\\<folder>.
Layout: feedback/<user>/<file>.zip, usage/<user>/<YYYY-MM>.jsonl. <user> is the work e-mail from `whoami /upn`.
Usage is shared unless the user turns it off (local/inbox.json); while the folder is not there, records wait in
local/usage-pending.jsonl and go out with the next one. KB_NO_USAGE=1 turns it off (the tests set it).
"""
from __future__ import annotations

import collections
import getpass
import json
import os
import re
import shutil
import subprocess
import threading
import time
from functools import lru_cache
from pathlib import Path

from kb.publish import appgit, branding

_LOCK = threading.Lock()


def config() -> dict:
    inbox = branding.settings().get("inbox")
    return inbox if isinstance(inbox, dict) else {}


def roots() -> list[Path]:
    """Where OneDrive folders live on this machine: the business one first."""
    out = [Path(os.environ[k]) for k in ("OneDriveCommercial", "OneDrive") if os.environ.get(k)]
    out += sorted(Path.home().glob("OneDrive - *"))
    seen, uniq = set(), []
    for p in out:
        if str(p).lower() not in seen:
            seen.add(str(p).lower())
            uniq.append(p)
    return uniq


def folder() -> Path | None:
    name = str(config().get("folder") or "").strip()
    if not name:
        return None
    return next((p for r in roots() if (p := r / name).is_dir()), None)


@lru_cache(maxsize=1)
def user() -> str:
    """The user's work e-mail (`whoami /upn` needs no admin rights), else the Git e-mail, else the login name."""
    for cmd in (["whoami", "/upn"] if os.name == "nt" else None, ["git", "config", "--global", "user.email"]):
        if not cmd:
            continue
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            v = r.stdout.strip().lower()
            if r.returncode == 0 and "@" in v:
                return _safe(v)
        except (OSError, subprocess.SubprocessError):
            continue
    return _safe(getpass.getuser().lower())


def _safe(name: str) -> str:
    return re.sub(r"[^\w.@+-]", "_", name)[:120] or "unknown"


def _prefs_file() -> Path:
    return appgit.local() / "inbox.json"


def prefs() -> dict:
    try:
        p = json.loads(_prefs_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        p = {}
    return {"share_usage": p.get("share_usage", True)}


def set_prefs(**kw) -> dict:
    p = {**prefs(), **{k: v for k, v in kw.items() if k in ("share_usage",)}}
    _prefs_file().parent.mkdir(parents=True, exist_ok=True)
    _prefs_file().write_text(json.dumps(p, indent=2), encoding="utf-8")
    return status()


def status() -> dict:
    c, f = config(), folder()
    return {"configured": bool(c.get("folder")), "connected": f is not None, "folder": str(f) if f else None,
            "name": c.get("folder"), "share_url": c.get("share_url"), "contact": c.get("contact"), "user": user(),
            **prefs()}


def deliver_feedback(zip_path: Path) -> Path | None:
    """Copy a feedback file into the inbox; None when the inbox is not there."""
    f = folder()
    if not f:
        return None
    dest = f / "feedback" / user() / zip_path.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(zip_path, dest)
    return dest


def record(kind: str, **data) -> None:
    """One usage record (question, model session, app start). Never raises: usage must not break the app."""
    try:
        if os.environ.get("KB_NO_USAGE") or not prefs()["share_usage"] or not config().get("folder"):
            return
        from kb.publish import diagnostics
        ev = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "kind": kind, "user": user(),
              "app": diagnostics.version().get("version"), **data}
        line = json.dumps(ev, ensure_ascii=False) + "\n"
        pending = appgit.local() / "usage-pending.jsonl"
        with _LOCK:
            f = folder()
            if not f:
                pending.parent.mkdir(parents=True, exist_ok=True)
                with pending.open("a", encoding="utf-8") as out:
                    out.write(line)
                return
            dest = f / "usage" / user() / f"{time.strftime('%Y-%m')}.jsonl"
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("a", encoding="utf-8") as out:
                if pending.exists():  # written while the folder was not there
                    out.write(pending.read_text(encoding="utf-8"))
                    pending.unlink()
                out.write(line)
    except Exception:  # noqa: BLE001
        pass


def report(base: Path | None = None) -> dict:
    """For the author: everyone's usage from the inbox (usage/<user>/*.jsonl)."""
    base = base or folder()
    if not base or not (base / "usage").is_dir():
        raise ValueError("no inbox with usage records here (connect the inbox folder or pass its path)")
    users: dict = collections.defaultdict(lambda: {"questions": 0, "sessions": 0, "errors": 0, "starts": 0,
                                                  "tokens": 0, "credits": 0.0, "days": set(), "last": "", "app": ""})
    recent = []
    for f in sorted((base / "usage").glob("*/*.jsonl")):
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            u = users[e.get("user") or f.parent.name]
            at = str(e.get("at") or "")
            u["days"].add(at[:10]); u["last"] = max(u["last"], at); u["app"] = e.get("app") or u["app"]
            k = e.get("kind")
            if k == "question":
                u["questions"] += 1
                recent.append({"at": at, "user": e.get("user"), "question": e.get("question"), "not_found": e.get("not_found")})
            elif k == "session":
                u["sessions"] += 1
                u["tokens"] += (e.get("tokens_in") or 0) + (e.get("tokens_out") or 0)
                u["credits"] += e.get("credits") or 0
                u["errors"] += 0 if e.get("ok", True) else 1
            elif k == "start":
                u["starts"] += 1
    rows = [{"user": k, **{**v, "days": len(v["days"]), "credits": round(v["credits"], 2)}} for k, v in users.items()]
    rows.sort(key=lambda r: r["last"], reverse=True)
    recent.sort(key=lambda r: r["at"], reverse=True)
    return {"folder": str(base), "users": rows, "recent_questions": recent[:30]}
