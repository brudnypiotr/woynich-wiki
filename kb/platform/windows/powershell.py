"""Run one of our PowerShell scripts: Windows PowerShell 5.1, no profile, our own module path (PS 7's modules break
5.1), output as UTF-8 JSON on the last line."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from kb.core.ports import Unavailable

HERE = Path(__file__).resolve().parent


def call(script: Path, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    """Run a .ps1 file with Windows PowerShell 5.1: no profile, our module path, no window. Raw result (bytes)."""
    cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script), *args]
    return subprocess.run(cmd, capture_output=True, timeout=timeout, env={**os.environ, "PSModulePath": ""},
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def run(script: str, *args: str, timeout: int = 120) -> dict:
    """Run kb/platform/windows/<script> and return the JSON it prints last; raise Unavailable with its message."""
    try:
        r = call(HERE / script, *args, timeout=timeout)
    except FileNotFoundError:
        raise Unavailable("Windows PowerShell was not found") from None
    except subprocess.TimeoutExpired:
        raise Unavailable(f"{script} did not finish within {timeout} s") from None
    out = r.stdout.decode("utf-8", errors="replace").strip().splitlines()
    try:
        data = json.loads(out[-1]) if out else {}
    except ValueError:
        data = {}
    if r.returncode or not data.get("ok"):
        why = data.get("error") or r.stderr.decode("utf-8", errors="replace").strip()[-300:] or f"exit code {r.returncode}"
        raise Unavailable(why)
    return data
