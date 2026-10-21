"""The changelog, read from Git history: Conventional Commit subjects (`type(scope): text`) grouped by the app version
(pyproject.toml) at each commit. Every merge to main bumps the version, so every merge is one entry."""
from __future__ import annotations

import re

from kb.publish import appgit

_CC = re.compile(r"^(?P<type>[A-Za-z]+)(?:\((?P<scope>[^)]*)\))?!?:\s*(?P<text>.+)$")
KINDS = {"feat": "Features", "fix": "Fixes"}


def parse(commit: str, date: str, subject: str) -> dict:
    """A commit subject as a changelog entry; anything that is not feat/fix is "Other"."""
    m = _CC.match(subject)
    typ, scope, text = (m["type"].lower(), m["scope"] or "", m["text"]) if m else ("other", "", subject)
    return {"commit": commit, "date": date, "type": typ, "scope": scope, "text": text, "kind": KINDS.get(typ, "Other")}


def commits(rng: str, limit: int = 0) -> list[dict]:
    out = appgit.git("log", "--format=%h\x1f%cs\x1f%s", *([f"-{limit}"] if limit else []), rng)
    return [parse(*line.split("\x1f", 2)) for line in out.splitlines() if line.count("\x1f") == 2]


def groups(limit: int = 500) -> list[dict]:
    """Every commit of this copy, newest first, grouped by version: a commit that changes `version` starts its group."""
    if not appgit.is_clone():
        return []
    log = [ln.split("\x1f", 3) for ln in appgit.git("log", "--topo-order", f"-{limit}", "--format=%H\x1f%h\x1f%cs\x1f%s").splitlines()]
    pos = {c[0]: i for i, c in enumerate(log)}
    bumps = [h for h in appgit.git("log", "--topo-order", "--format=%H", "-G", r"^version = ", "--", "pyproject.toml").splitlines() if h in pos]
    bounds = [(pos[h], appgit.version_at(h) or "?") for h in bumps]  # newest first
    out: list[dict] = []
    b = 0
    for i, (_, short, date, subject) in enumerate(log):
        while b < len(bounds) and i > bounds[b][0]:
            b += 1  # older than this bump: an earlier version
        ver = bounds[b][1] if b < len(bounds) else (f"before {bounds[-1][1]}" if bounds else "unversioned")
        if not out or out[-1]["version"] != ver:
            out.append({"version": ver, "date": date, "entries": []})
        out[-1]["entries"].append(parse(short, date, subject))
    return out


def markdown(gs: list[dict], all_types: bool = False) -> str:
    out = ["# Changelog", "", "Generated from Git history (`kb changelog --md`).", ""]
    for g in gs:
        entries = [e for e in g["entries"] if all_types or e["kind"] != "Other"]
        if not entries:
            continue
        out += [f"## {g['version']}", ""]
        for kind in ("Features", "Fixes", "Other"):
            ks = [e for e in entries if e["kind"] == kind]
            if ks:
                out += [f"### {kind}", ""] + [f"- {e['date']} {e['text']}" + (f" ({e['scope']})" if e["scope"] else "")
                                              + f" `{e['commit']}`" for e in ks] + [""]
    return "\n".join(out)
