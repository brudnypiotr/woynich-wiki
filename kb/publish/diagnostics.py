"""Version of the app and a diagnostics report for support (About in `kb serve`, `kb diagnostics`).

The report is technical state only: versions, configuration flags, counts, credential checks (no AI credits) and the
last errors. It never contains keys, tokens or the content of sources and pages.
"""
from __future__ import annotations

import json
import os
import platform
import sys
import time
from importlib import metadata

from kb.core import config
from kb.publish import appgit

_VERSION: dict | None = None


def version() -> dict:
    """The app's version (pyproject.toml) and the Git commit of this copy of the repository, read once."""
    global _VERSION
    if _VERSION is None:
        root = config.paths().root
        try:
            import tomllib
            v = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
        except Exception:
            v = "unknown"
        try:
            commit, date = (appgit.git("log", "-1", "--format=%h %cs").split() + ["", ""])[:2]
            branch = appgit.git("rev-parse", "--abbrev-ref", "HEAD")
            dirty = bool(appgit.git("status", "--porcelain", "--untracked-files=no"))
        except appgit.GitError:  # no git on this computer, or a copy without Git history
            commit = date = branch = ""; dirty = False
        _VERSION = {"version": v, "commit": commit or None, "date": date or None, "branch": branch or None, "dirty": dirty}
    return _VERSION


def _pkg(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def report(gw, jobs=()) -> dict:
    """Everything support needs to see what this installation is and how it is doing. jobs: recent upload jobs."""
    from kb.knowledge import catalog, chat, pages
    from kb import platform as platform_services
    from kb.publish import settings
    st = settings.state()
    inst = catalog.instance()
    wiki = pages.wiki()
    errors = [{"file": j.get("filename"), "state": j.get("state"), "error": j.get("error")}
              for j in sorted(jobs, key=lambda j: j.get("seq", 0), reverse=True) if j.get("state") == "error"][:5]
    return {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "app": version(),
        "runtime": {"python": sys.version.split()[0], "executable": sys.executable, "os": platform.platform(),
                    "github-copilot-sdk": _pkg("github-copilot-sdk"), "keyring": _pkg("keyring"), "pillow": _pkg("pillow"), "xlrd": _pkg("xlrd"), "pydantic": _pkg("pydantic")},
        "paths": {"repository": str(config.paths().root), "instance": str(inst),
                  "instance_from": "KB_INSTANCE" if os.environ.get("KB_INSTANCE") else "default"},
        "model": {k: st["model"][k] for k in ("effective", "source", "recommended", "timeout_s", "adapter")},
        "setup": settings.setup_state(),
        "knowledge_base": {"sources": len(catalog.all_sources()),
                           "pages": sum(1 for _ in wiki.rglob("*.md")) if wiki.exists() else 0,
                           "discussions": len(list((inst / "sessions").glob("*.json"))) if (inst / "sessions").exists() else 0},
        "jira": {"configured": bool(st["profile"]["jira_base_url"]), "cloud": ".atlassian.net" in st["profile"]["jira_base_url"]},
        "code_repos": [{"name": r["name"], "exists": r["exists"], "branch": r.get("branch"), "commit": r["commit"], "dirty": r["dirty"]}
                       for r in chat.repos()],
        "secrets": {x["name"]: x["set"] for x in st["secrets"]["items"]} | ({"error": st["secrets"]["error"]} if st["secrets"]["error"] else {}),
        "formats": platform_services.status(),  # OCR (and later Office) on this laptop, cheap checks only
        "checks": settings.check(gw),  # GitHub Copilot sign-in and one Jira request, no AI credits
        "recent_errors": errors,
    }


def as_text(r: dict) -> str:
    return json.dumps(r, ensure_ascii=False, indent=2, default=str)
