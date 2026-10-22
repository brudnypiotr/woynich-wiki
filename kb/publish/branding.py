"""Company branding (logo, header background, icon), kept out of Git: the copy's `branding/` folder, or the knowledge
base's own `instance/branding/` (wins). Shared as a branding.zip: `kb branding pack` makes it, with branding.json
carrying what is the same for the whole team: the knowledge base title, the app name (desktop shortcut, window) and the
author's e-mail (contact: where feedback goes). Welcome, Settings → Project branding, `kb branding import` or setup.cmd (when
branding.zip lies next to it) unpacks it, sets the title, and on Windows gives the shortcut the icon and the name.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import zipfile
from pathlib import Path

from kb.core import config

STEMS = ("logo", "background", "icon")
EXTS = (".svg", ".png", ".jpg", ".jpeg", ".ico")
MAX_ZIP = 20_000_000
APP_NAME = "Wiki"  # default app name; branding.json "app_name" overrides it


def folder() -> Path:
    return config.paths().root / "branding"


def dirs() -> list[Path]:
    from kb.knowledge import catalog
    return [catalog.instance() / "branding", folder()]


def find(stem: str, exts: tuple[str, ...] = (".svg", ".png", ".jpg", ".jpeg")) -> Path | None:
    return next((p for d in dirs() for ext in exts if (p := d / f"{stem}{ext}").exists()), None)


def settings() -> dict:
    """branding.json of this copy (instance/branding/ wins over branding/): {title, app_name, contact}; {} when none."""
    for d in dirs():
        try:
            data = json.loads((d / "branding.json").read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, ValueError):
            continue
    return {}


def save_settings(patch: dict) -> dict:
    """Merge team-wide settings into branding.json (the one this copy reads; else branding/). None removes a key."""
    target = next((d / "branding.json" for d in dirs() if (d / "branding.json").exists()), folder() / "branding.json")
    data = {**settings(), **patch}
    data = {k: v for k, v in data.items() if v not in (None, "", {})}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def app_name() -> str:
    return str(settings().get("app_name") or "").strip() or APP_NAME


def state() -> dict:
    return {"folder": str(folder()), "app_name": app_name(), "contact": settings().get("contact") or "",
            "files": {s: (str(p) if (p := find(s, EXTS)) else None) for s in STEMS}}


def import_zip(data: bytes) -> dict:
    """Unpack logo/background/icon files from a zip (flat or inside a folder) into branding/. Other files are ignored."""
    if len(data) > MAX_ZIP:
        raise ValueError(f"branding.zip is larger than {MAX_ZIP // 1_000_000} MB")
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise ValueError("not a .zip file") from e
    got, title, meta = [], None, None
    folder().mkdir(exist_ok=True)
    for info in z.infolist():
        if Path(info.filename).name.lower() == "branding.json" and info.file_size < 100_000:
            try:
                meta = json.loads(z.read(info).decode("utf-8"))
                title = str(meta.get("title") or "").strip() or None
            except (ValueError, UnicodeDecodeError, AttributeError):
                raise ValueError("branding.json in the zip is not valid JSON") from None
            (folder() / "branding.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            continue
        name = Path(info.filename).name.lower()  # basename only: no paths from the zip are trusted
        stem, ext = os.path.splitext(name)
        if info.is_dir() or stem not in STEMS or ext not in EXTS or info.file_size > MAX_ZIP:
            continue
        for old in folder().glob(f"{stem}.*"):  # one file per role: a new icon.png replaces icon.svg
            if old.suffix.lower() != ".ico" or ext == ".ico":
                old.unlink()
        (folder() / name).write_bytes(z.read(info))
        got.append(name)
    if not got and not meta:
        raise ValueError("no branding files in the zip (expected logo, background or icon as .png, .svg, .jpg or .ico)")
    if title:  # the knowledge base title the colleague who packed it uses
        from kb.publish import settings
        settings.save({"profile": {"title": title}})
    return {"imported": sorted(got), "title": title, "shortcut": refresh_shortcut() if got or meta else "unchanged",
            **state()}


def pack(out: Path | None = None) -> Path:
    """branding/ (and instance/branding/ on top) as branding.zip to send to a colleague, with the knowledge base title."""
    out = out or config.paths().root / "branding.zip"
    files = {p.name: p for d in reversed(dirs()) if d.exists() for p in d.iterdir()
             if p.suffix.lower() in EXTS and p.stem.lower() in STEMS}
    if not files:
        raise ValueError(f"no branding files in {folder()}")
    meta = settings()  # the same for the whole team; personal settings (Jira e-mail, keys) never
    title = (config.load("profile").get("instance") or {}).get("title")
    if title:
        meta["title"] = title
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, p in sorted(files.items()):
            z.write(p, f"branding/{name}")
        if meta:
            z.writestr("branding/branding.json", json.dumps(meta, ensure_ascii=False, indent=2))
    return out


def refresh_shortcut() -> str:
    """Windows: make the desktop shortcut again, so it shows the new icon and name."""
    if os.name != "nt":
        return "skipped (not Windows)"
    script = config.paths().root / "setup" / "shortcut.ps1"
    r = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                       capture_output=True, text=True, timeout=60, env={**os.environ, "PSModulePath": ""})
    return "updated" if r.returncode == 0 else f"not updated: {(r.stderr or r.stdout).strip()[:200]}"
