"""Company branding (logo, header background, icon), kept out of Git: the copy's `branding/` folder, or the knowledge
base's own `instance/branding/` (wins). Shared as a branding.zip: `kb branding pack` makes it, Settings → Branding
(or `kb branding import`, or setup.cmd when branding.zip lies next to it) unpacks it, and on Windows the
Wiki shortcut gets the new icon.
"""
from __future__ import annotations

import io
import os
import subprocess
import zipfile
from pathlib import Path

from kb.core import config

STEMS = ("logo", "background", "icon")
EXTS = (".svg", ".png", ".jpg", ".jpeg", ".ico")
MAX_ZIP = 20_000_000


def folder() -> Path:
    return config.paths().root / "branding"


def dirs() -> list[Path]:
    from kb.knowledge import catalog
    return [catalog.instance() / "branding", folder()]


def find(stem: str, exts: tuple[str, ...] = (".svg", ".png", ".jpg", ".jpeg")) -> Path | None:
    return next((p for d in dirs() for ext in exts if (p := d / f"{stem}{ext}").exists()), None)


def state() -> dict:
    return {"folder": str(folder()), "files": {s: (str(p) if (p := find(s, EXTS)) else None) for s in STEMS}}


def import_zip(data: bytes) -> dict:
    """Unpack logo/background/icon files from a zip (flat or inside a folder) into branding/. Other files are ignored."""
    if len(data) > MAX_ZIP:
        raise ValueError(f"branding.zip is larger than {MAX_ZIP // 1_000_000} MB")
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise ValueError("not a .zip file") from e
    got = []
    folder().mkdir(exist_ok=True)
    for info in z.infolist():
        name = Path(info.filename).name.lower()  # basename only: no paths from the zip are trusted
        stem, ext = os.path.splitext(name)
        if info.is_dir() or stem not in STEMS or ext not in EXTS or info.file_size > MAX_ZIP:
            continue
        for old in folder().glob(f"{stem}.*"):  # one file per role: a new icon.png replaces icon.svg
            if old.suffix.lower() != ".ico" or ext == ".ico":
                old.unlink()
        (folder() / name).write_bytes(z.read(info))
        got.append(name)
    if not got:
        raise ValueError("no branding files in the zip (expected logo, background or icon as .png, .svg, .jpg or .ico)")
    return {"imported": sorted(got), "shortcut": refresh_shortcut(), **state()}


def pack(out: Path | None = None) -> Path:
    """branding/ (and instance/branding/ on top) as branding.zip to send to a colleague."""
    out = out or config.paths().root / "branding.zip"
    files = {p.name: p for d in reversed(dirs()) if d.exists() for p in d.iterdir()
             if p.suffix.lower() in EXTS and p.stem.lower() in STEMS}
    if not files:
        raise ValueError(f"no branding files in {folder()}")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, p in sorted(files.items()):
            z.write(p, f"branding/{name}")
    return out


def refresh_shortcut() -> str:
    """Windows: make the Wiki shortcut again, so it shows the new icon."""
    if os.name != "nt":
        return "skipped (not Windows)"
    script = config.paths().root / "setup" / "shortcut.ps1"
    r = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                       capture_output=True, text=True, timeout=60, env={**os.environ, "PSModulePath": ""})
    return "updated" if r.returncode == 0 else f"not updated: {(r.stderr or r.stdout).strip()[:200]}"
