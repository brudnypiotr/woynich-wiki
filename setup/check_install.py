"""Is this copy installed correctly? Read-only; run by doctor.ps1 with the app's own Python, prints one JSON object.

    python setup/check_install.py            (from any folder; the copy is the folder above this file)

Checks what has broken before, so a report says it at once:
  - the packages of requirements.txt are installed in this Python (an Update installs new ones; a failed pip does not);
  - `kb` is imported from this copy (the embeddable Python is shared by every copy; its woynich-wiki.pth points at
    whichever copy ran setup last, which is fine only while every launcher puts its own copy first);
  - the pre-commit guard of the repository and of the instance point at this copy's .githooks;
  - the setup this copy needs has run (setup/version.txt vs local/setup-version.txt), and no package installation is
    left over from an update (local/update-deps).
Standard library only: it must run even when packages are missing.
"""
from __future__ import annotations

import importlib.metadata as md
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8-sig").strip() if p.exists() else ""


def missing_packages() -> list[str]:
    out = []
    for line in _read(REPO / "requirements.txt").splitlines():
        name = re.split(r"[<>=!~;#\s\[]", line.strip(), maxsplit=1)[0]
        if not name:
            continue
        try:
            md.version(name)
        except md.PackageNotFoundError:
            out.append(name)
    return out


def kb_location() -> str:
    """Where `import kb` comes from with this copy first, as every launcher runs it."""
    sys.path.insert(0, str(REPO))
    try:
        import kb
        return str(Path(kb.__file__).resolve().parent.parent)
    except Exception as e:  # noqa: BLE001  a report, never a crash
        return f"error: {type(e).__name__}: {e}"
    finally:
        sys.path.pop(0)


def shared_pth() -> str | None:
    """The copy the embeddable Python's woynich-wiki.pth points at (None when there is none)."""
    for d in {Path(p) for p in sys.path if p.endswith("site-packages")}:
        f = d / "woynich-wiki.pth"
        if f.exists():
            return _read(f).splitlines()[0] if _read(f) else ""
    return None


def hooks(path: Path) -> str | None:
    if not (path / ".git").exists():
        return None
    try:
        r = subprocess.run(["git", "-C", str(path), "config", "core.hooksPath"], capture_output=True, text=True, timeout=30)
        return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "git not found"


def instance() -> Path:
    return Path(os.environ.get("KB_INSTANCE") or REPO / "instance")


def _same(a: str | None, b: Path) -> bool:
    return bool(a) and os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(str(b)))


def checks() -> list[dict]:
    """The findings as doctor.ps1 shows them: name, status (OK, WARN, FAIL, INFO), detail, advice."""
    out = []
    add = lambda name, status, detail, advice="": out.append({"name": name, "status": status, "detail": detail, "advice": advice})  # noqa: E731
    add("App Python", "INFO", f"{sys.version.split()[0]} at {sys.executable}"
        + (" (embeddable, shared by every copy)" if any(Path(sys.executable).parent.glob("python3*._pth")) else ""))
    miss = missing_packages()
    add("Packages (requirements.txt)", "FAIL" if miss else "OK", "missing: " + ", ".join(miss) if miss else "all installed",
        "run setup.cmd (or Update) when the network allows" if miss else "")
    where = kb_location()
    add("App code", "OK" if _same(where, REPO) else "FAIL", f"kb from {where}",
        "" if _same(where, REPO) else "this copy's code is not the one that runs: run setup.cmd in this folder")
    pth = shared_pth()
    if pth is not None:
        add("Shared Python points at", "OK" if _same(pth, REPO) else "INFO", pth or "(empty)",
            "" if _same(pth, REPO) else "another copy ran setup last; fine: every launcher runs its own copy first")
    repo_hooks, inst = hooks(REPO), instance()
    if repo_hooks is not None:
        ok = repo_hooks == ".githooks" or _same(repo_hooks, REPO / ".githooks")
        add("Pre-commit guard (repository)", "OK" if ok else "WARN", repo_hooks or "not set", "" if ok else "run setup.cmd")
    inst_hooks = hooks(inst)
    if inst_hooks is not None:
        ok = _same(inst_hooks, REPO / ".githooks")
        add("Pre-commit guard (instance)", "OK" if ok else "WARN", f"{inst_hooks or 'not set'} ({inst})",
            "" if ok else "it is set again at the next start of the app (0.19.3 or later)")
    need, done = _read(REPO / "setup" / "version.txt"), _read(REPO / "local" / "setup-version.txt")
    add("Setup for this version", "OK" if need and need == done else "WARN", f"needs {need or '?'}, done {done or 'never'}",
        "" if need and need == done else "start Wiki.cmd (it runs the setup first) or setup.cmd")
    if (REPO / "local" / "update-deps").exists():
        add("Packages after the last update", "WARN", "not installed yet", "start the app again, or run setup.cmd")
    return out


if __name__ == "__main__":
    print(json.dumps(checks(), ensure_ascii=True))
