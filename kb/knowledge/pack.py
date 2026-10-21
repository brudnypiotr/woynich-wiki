"""Knowledge pack: a ready knowledge base in one file, so a team starts from a finished ingest instead of an empty one.

`export()` writes <title>.kbpack.zip: the wiki, every source (raw/: originals, extracted text with locators, records;
store/: the large originals), the project branding and the settings the whole team shares (title, Jira URL).
Never anything personal: discussions, usage logs, Jira e-mail, keys, model choice, code repository paths.

`import_pack()` replaces this knowledge base's wiki and sources with the pack's (no merging: the pack is the starting
point). The replaced wiki and sources stay in the instance's Git history; the user's own settings and discussions stay.
The pack holds company content: share it only through company channels (Teams, SharePoint), never a public repository.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath

from kb import __version__
from kb.core import config, gitops
from kb.knowledge import catalog

FORMAT = 1
CONTENT = ("wiki", "raw", "store")  # instance folders a pack carries and an import replaces
MANIFEST = "kbpack.json"


def _profile() -> dict:
    return config.load("profile")


def slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "knowledge-base"


def export(out: Path | None = None) -> dict:
    """Write the pack. Returns its path and what it holds."""
    from kb.publish import branding
    inst = catalog.instance()
    prof = _profile()
    title = (prof.get("instance") or {}).get("title") or "Knowledge base"
    sources = catalog.all_sources()
    if not sources:
        raise ValueError("this knowledge base has no sources yet: add and ingest them first")
    out = Path(out) if out else config.paths().root / f"{slug(title)}.kbpack.zip"
    shared = {"title": title, "jira_base_url": (prof.get("jira") or {}).get("base_url")}
    pages = sum(1 for _ in (inst / "wiki").rglob("*.md")) if (inst / "wiki").exists() else 0
    manifest = {"format": FORMAT, "title": title, "created": catalog.now(), "app_version": __version__,
                "sources": len(sources), "pages": pages, "settings": shared}
    tmp = out.with_name(out.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
        z.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2))
        for top in CONTENT:
            base = inst / top
            for p in sorted(base.rglob("*")) if base.exists() else []:
                if p.is_file() and not p.name.endswith(".tmp"):
                    z.write(p, f"instance/{p.relative_to(inst).as_posix()}")
        for name, p in sorted({p.name: p for d in reversed(branding.dirs()) if d.exists() for p in d.iterdir()
                               if p.suffix.lower() in branding.EXTS and p.stem.lower() in branding.STEMS}.items()):
            z.write(p, f"branding/{name}")
    tmp.replace(out)
    return {"path": str(out), "bytes": out.stat().st_size, **{k: manifest[k] for k in ("title", "sources", "pages")}}


def read_manifest(path: Path) -> dict:
    with zipfile.ZipFile(path) as z:
        try:
            m = json.loads(z.read(MANIFEST).decode("utf-8"))
        except KeyError:
            raise ValueError("not a knowledge pack (no kbpack.json inside)") from None
    if m.get("format") != FORMAT:
        raise ValueError(f"knowledge pack format {m.get('format')} is not supported by this version; update the app")
    return m


def _target(root: Path, name: str) -> Path | None:
    """Where a zip entry goes, or None when it must be skipped (anything outside the allowed folders or with ..)."""
    parts = PurePosixPath(name).parts
    if ".." in parts or not parts or name.endswith("/"):
        return None
    if parts[0] == "instance" and len(parts) > 2 and parts[1] in CONTENT:
        return root / "instance-new" / Path(*parts[1:])
    if parts[0] == "branding" and len(parts) == 2:
        return root / "branding" / parts[1]
    return None


def _commit(inst: Path, msg: str) -> None:
    """wiki/ and raw/ as they are now, additions and removals (gitops.commit needs paths Git already knows)."""
    git = lambda *a, **kw: subprocess.run(["git", "-C", str(inst), *a], **kw)
    git("add", "-A", "--", "wiki", "raw", check=True)
    if git("diff", "--cached", "--quiet").returncode != 0:
        git("commit", "-q", "-m", msg, check=True)


def import_pack(path: Path) -> dict:
    """Replace this knowledge base's wiki and sources with the pack's. One commit in the instance; the old content
    stays in its history. Personal settings and discussions are kept; the title and an empty Jira URL are set."""
    from kb.knowledge import search
    from kb.publish import branding, settings, site
    path = Path(path)
    if not zipfile.is_zipfile(path):
        raise ValueError("not a .zip file")
    m = read_manifest(path)
    inst = catalog.init()
    work = Path(tempfile.mkdtemp(prefix="kbpack-", dir=inst))  # same drive: the final moves are renames
    try:
        imported_branding = []
        with zipfile.ZipFile(path) as z:
            for info in z.infolist():
                t = _target(work, info.filename)
                if t is None:
                    continue
                t.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, t.open("wb") as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
        if not (work / "instance-new" / "raw").exists():
            raise ValueError("the knowledge pack has no sources")
        (work / "instance-old").mkdir()
        for top in CONTENT:  # renames: the old folders go aside first and are deleted with the work folder
            old, new = inst / top, work / "instance-new" / top
            if old.exists():
                old.replace(work / "instance-old" / top)
            if new.exists():
                new.replace(old)
            else:
                old.mkdir()
        if (work / "branding").exists():
            branding.folder().mkdir(exist_ok=True)
            for p in (work / "branding").iterdir():
                if p.suffix.lower() in branding.EXTS and p.stem.lower() in branding.STEMS:
                    shutil.copy2(p, branding.folder() / p.name)
                    imported_branding.append(p.name)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    shared = m.get("settings") or {}
    if shared.get("title"):
        settings.save({"profile": {"title": shared["title"]}})
    if shared.get("jira_base_url") and not (_profile().get("jira") or {}).get("base_url"):
        prof = settings._read("profile")  # the URL only: the e-mail is each person's own (Settings asks for it)
        prof.setdefault("jira", {})["base_url"] = shared["jira_base_url"]
        settings._write("profile", prof)
    _commit(inst, gitops.message("catalog", f"import knowledge pack {m.get('title')!r}",
                                 body=f"created {m.get('created')} with woynich-wiki {m.get('app_version')}; "
                                      f"{m.get('sources')} sources, {m.get('pages')} pages; the previous content is in the history"))
    search.rebuild()
    site.build()
    return {"title": m.get("title"), "sources": len(catalog.all_sources()), "pages": m.get("pages"),
            "created": m.get("created"), "branding": imported_branding,
            "shortcut": branding.refresh_shortcut() if imported_branding else "unchanged", "at": time.time()}
