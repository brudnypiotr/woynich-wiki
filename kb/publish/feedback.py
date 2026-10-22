"""Feedback: the user tells what happened, Luna asks a few short questions and writes a report, and everything the
author needs to understand it goes into one zip on the Desktop for the user to send (Teams, e-mail).

Luna asks at most MAX_ROUNDS rounds of questions (one message, up to three short questions), then writes the report;
after that the user only confirms. The package holds the report, the conversation, screenshots, diagnostics (no keys),
the app log, the user's discussions and the wiki as it is now. Company content: send it only inside the company.
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from kb.knowledge import catalog
from kb.publish import applog, appgit, diagnostics

MAX_ROUNDS = 2          # rounds of questions before Luna must write the report
REPORT_FIELDS = ("title", "kind", "what_happened", "expected", "steps", "where", "impact")

PROMPT = """You help a user of a project knowledge base app (chat with citations, Add sources, Wiki,
Settings, Welcome, About/Updates) report a problem or an idea to its author. The user may not be technical.

Talk to the user in the language they write in. Write the report in English (it is for the app's author).

Conversation so far (user and you):
{transcript}

{instruction}

Reply with JSON only, no other text:
{{"done": true|false,
  "message": "what you say to the user now, short and friendly, in the user's language",
  "report": {{"title": "...", "kind": "bug|idea|question", "what_happened": "...", "expected": "...",
             "steps": "...", "where": "screen or feature", "impact": "how much it blocks the user"}} }}
"""
ASK = ("If something essential for the author is missing (what the user did, what they expected, what happened instead, "
       "where in the app), set done=false and ask for it in ONE message with at most three short questions. Never ask "
       "for something the user already said or for details a diagnostics file shows (version, settings). If you have "
       "enough, set done=true, write the report and in message briefly say what you will send.")
FINISH = ("Do not ask anything more. Set done=true, write the best report you can from what you have (write "
          "'not given' where needed) and in message briefly say what you will send.")


def _transcript(messages: list[dict]) -> str:
    return "\n".join(f"{'User' if m.get('role') == 'user' else 'You'}: {str(m.get('text') or '').strip()}"
                     for m in messages if str(m.get("text") or "").strip())


def _parse(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        j = json.loads(m.group(0)) if m else {}
    except ValueError:
        j = {}
    if not isinstance(j, dict) or "message" not in j:  # not JSON: treat the reply as a question
        return {"done": False, "message": (text or "").strip()[:2000], "report": None}
    rep = j.get("report") if isinstance(j.get("report"), dict) else None
    return {"done": bool(j.get("done")), "message": str(j.get("message") or "").strip(),
            "report": {k: str(rep.get(k) or "").strip() for k in REPORT_FIELDS} if rep else None}


def converse(gw, messages: list[dict]) -> dict:
    """Luna's next turn. messages: [{role: user|assistant, text}], the user's first. After MAX_ROUNDS answers to her
    questions she must write the report."""
    answers = sum(1 for m in messages if m.get("role") == "user") - 1
    final = answers >= MAX_ROUNDS
    r = gw.run("feedback", PROMPT.format(transcript=_transcript(messages), instruction=FINISH if final else ASK),
               stage="feedback")
    out = _parse(r.text)
    if final and not out["done"]:  # the model asked again anyway: close it with what there is
        out = {"done": True, "message": out["message"] or "Thank you, I have what I need.",
               "report": out["report"] or {"title": "Feedback", "kind": "bug", "what_happened": _transcript(messages)}}
    out["rounds_left"] = max(0, MAX_ROUNDS - answers - (0 if out["done"] else 1))
    return out


def desktop() -> Path:
    """The user's Desktop (OneDrive-redirected too on Windows), else Downloads, else the app's local folder."""
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
                p = Path(os.path.expandvars(winreg.QueryValueEx(k, "Desktop")[0]))
            if p.is_dir():
                return p
        except OSError:
            pass
    for p in (Path.home() / "Desktop", Path.home() / "Downloads"):
        if p.is_dir():
            return p
    d = appgit.local() / "feedback"
    d.mkdir(parents=True, exist_ok=True)
    return d


def report_markdown(text: str, report: dict | None, messages: list[dict], app: dict) -> str:
    r = report or {}
    lines = [f"# {r.get('title') or 'Feedback'}", "",
             f"- kind: {r.get('kind') or '-'}", f"- app: {app.get('version')} ({app.get('commit')}, {app.get('branch')})",
             f"- created: {time.strftime('%Y-%m-%d %H:%M')}", ""]
    for k, label in (("what_happened", "What happened"), ("expected", "Expected"), ("steps", "Steps"),
                     ("where", "Where"), ("impact", "Impact")):
        if r.get(k):
            lines += [f"## {label}", "", r[k], ""]
    lines += ["## The user's words", "", text.strip() or "-", "", "## Conversation", ""]
    lines += [f"**{'User' if m.get('role') == 'user' else 'Luna'}:** {str(m.get('text') or '').strip()}  " for m in messages]
    return "\n".join(lines) + "\n"


def package(text: str, report: dict | None, messages: list[dict], screenshots: list[str], gw=None, jobs=()) -> dict:
    """Write feedback-<date>.zip to the Desktop. screenshots: data URLs (image/png, image/jpeg)."""
    inst = catalog.instance()
    app = diagnostics.version()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = desktop() / f"wiki-feedback-{stamp}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
        z.writestr("feedback.md", report_markdown(text, report, messages, app))
        z.writestr("feedback.json", json.dumps({"text": text, "report": report, "messages": messages, "app": app},
                                               ensure_ascii=False, indent=2))
        for i, url in enumerate(screenshots or [], 1):
            m = re.match(r"data:image/(png|jpeg|jpg|gif|webp);base64,(.+)$", url or "", re.S)
            if m:
                z.writestr(f"screenshots/{i}.{m[1].replace('jpeg', 'jpg')}", base64.b64decode(m[2]))
        try:
            rep = diagnostics.report(gw, list(jobs)) if gw else {"app": app}
        except Exception as e:  # noqa: BLE001  the package is still useful without full diagnostics
            rep = {"app": app, "diagnostics_error": f"{type(e).__name__}: {e}"}
        z.writestr("diagnostics.json", diagnostics.as_text(rep))
        for f in applog.files():
            z.write(f, f"logs/{f.name}")
        for top in ("sessions", "wiki"):  # the user's discussions; the wiki as it is now
            base = inst / top
            for p in sorted(base.rglob("*")) if base.exists() else []:
                if p.is_file():
                    z.write(p, f"instance/{p.relative_to(inst).as_posix()}")
        srcs = catalog.all_sources()
        z.writestr("instance/sources.json", json.dumps(srcs, ensure_ascii=False, indent=2))
        log = subprocess.run(["git", "-C", str(inst), "log", "-30", "--format=%h %cs %s"], capture_output=True,
                             text=True, encoding="utf-8", errors="replace").stdout
        z.writestr("instance/git-log.txt", log)
    from kb.publish import branding
    return {"path": str(out), "folder": str(out.parent), "bytes": out.stat().st_size, "sources": len(srcs),
            "contact": branding.settings().get("contact")}


def reveal(path: str) -> None:
    """Show the package in Explorer / Finder."""
    p = Path(path)
    if os.name == "nt":
        subprocess.Popen(["explorer", "/select,", str(p)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p.parent)])
