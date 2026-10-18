"""Instance catalog: register sources (one commit each), keep originals, extract text with locators.

Instance layout (its own git repository, separate from the blueprint):
  inbox/            drop files here (`kb collect`)
  raw/<id>/         original.<ext> | source.json | text.md | extract.json | figures/ | claims.json
  store/<sha256>    originals larger than profile.store.max_git_bytes (git-ignored, back it up separately)
  wiki/             index.md, log.md, hot.md, sources/, topics/, glossary.md, discrepancies.md, answers/
  catalog/          metering.jsonl, queries.jsonl
  queue/            submissions (ingest as a service)
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from kb.core import config, gitops, schemas
from kb import extractors

INSTANCE_DIRS = ["inbox", "raw", "store", "wiki/sources", "wiki/topics", "wiki/answers", "catalog", "queue", "reports", "config"]
INSTANCE_GITIGNORE = "store/\ninbox/processed/\n.cache/\nsite/\nreports/\n*.tmp\n"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def instance() -> Path:
    return config.paths().instance


def init() -> Path:
    inst = instance()
    for d in INSTANCE_DIRS:
        (inst / d).mkdir(parents=True, exist_ok=True)
    gi = inst / ".gitignore"
    if not gi.exists():
        gi.write_text(INSTANCE_GITIGNORE, encoding="utf-8")
    if not (inst / ".git").exists():
        subprocess.run(["git", "init", "-q", str(inst)], check=True)
        hooks = config.paths().root / ".githooks"
        if hooks.exists():
            subprocess.run(["git", "-C", str(inst), "config", "core.hooksPath", str(hooks)], check=False)
        gitops.commit(inst, [gi], gitops.message("config", "initialise knowledge base instance"))
    return inst


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find(sid: str) -> Path | None:
    d = instance() / "raw" / sid
    return d if (d / "source.json").exists() else None


def load(sid: str) -> dict:
    return json.loads((instance() / "raw" / sid / "source.json").read_text(encoding="utf-8"))


def save(rec: dict) -> Path:
    schemas.validate("source_record", rec)
    p = instance() / "raw" / rec["id"] / "source.json"
    p.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def all_sources() -> list[dict]:
    raw = instance() / "raw"
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(raw.glob("*/source.json"))] if raw.exists() else []


def add_file(path: Path, *, connector: str = "manual", ref: str | None = None, title: str | None = None,
             kind: str | None = None, url: str | None = None, version: str | None = None,
             found_via: list[str] | None = None, commit: bool = True) -> tuple[dict, bool]:
    """Register one file. Returns (record, created). Idempotent: the same content is never added twice."""
    from kb.connectors.folder_inbox import KIND_BY_EXT
    inst = init()
    path = Path(path)
    digest = sha256(path)
    sid = digest[:12]
    if find(sid):
        return load(sid), False
    d = inst / "raw" / sid
    d.mkdir(parents=True, exist_ok=True)
    suffix = "".join(path.suffixes[-2:]) if path.name.endswith(".jira.json") else path.suffix.lower()
    limit = (config.load("profile").get("store") or {}).get("max_git_bytes", 20_000_000)
    size = path.stat().st_size
    if size > limit:
        (inst / "store").mkdir(exist_ok=True)
        stored = inst / "store" / f"{digest}{suffix}"
        shutil.copy2(path, stored)
        original, stored_in = stored, "store"
    else:
        original = d / f"original{suffix}"
        shutil.copy2(path, original)
        stored_in = "git"
    rec = {"id": sid, "key": None, "kind": kind or KIND_BY_EXT.get(path.suffix.lower(), "document" if suffix == ".jira.json" else "other"),
           "title": title or path.stem, "origin": {"connector": connector, "ref": ref or path.name, "url": url},
           "sha256": digest, "bytes": size, "mime": None, "version": version, "valid_from": None,
           "authority": None, "audience": "internal", "scope": "client", "stored_in": stored_in,
           "collected_at": now(), "found_via": found_via or [connector], "supersedes": None, "status": "new"}
    if suffix == ".jira.json":
        rec["kind"] = "ticket"
    rec = extract(rec, original, d)
    files = [d]
    save(rec)
    if commit:
        gitops.commit(inst, files, gitops.message("source", f"add {rec['title']}", scope=sid,
                                                   body=f"kind: {rec['kind']}\nsha256: {digest}\nstored_in: {stored_in}\nfound_via: {', '.join(rec['found_via'])}"))
    return rec, True


def extract(rec: dict, original: Path, d: Path) -> dict:
    ex = extractors.for_path(original)
    info = {"extractor": None, "chars": 0}
    if ex is None:
        (d / "text.md").write_text("", encoding="utf-8")
        info["note"] = "no extractor for this file type; registered as metadata only"
    else:
        try:
            out = ex.extract(original, out_dir=d) if type(ex).__name__ == "PdfExtractor" else ex.extract(original)
            (d / "text.md").write_text(out["text"], encoding="utf-8")
            info.update({"extractor": type(ex).__name__, "chars": len(out["text"]), **out.get("meta", {})})
            if out.get("meta", {}).get("title") and (rec["kind"] == "ticket" or rec["title"] in (original.stem, rec["origin"]["ref"], Path(rec["origin"]["ref"]).stem)):
                rec["title"] = out["meta"]["title"]
            if out.get("meta", {}).get("key"):
                rec["key"] = out["meta"]["key"]
            if out.get("meta", {}).get("updated"):
                rec["version"] = out["meta"]["updated"]
            rec["status"] = "extracted"
        except Exception as e:
            info["error"] = f"{type(e).__name__}: {e}"[:300]
            rec["status"] = "error"
            (d / "text.md").write_text("", encoding="utf-8")
    (d / "extract.json").write_text(json.dumps(info, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return rec


def collect_inbox() -> list[tuple[dict, bool]]:
    inst = init()
    inbox = inst / "inbox"
    done = inbox / "processed"
    results = []
    for p in sorted(inbox.rglob("*")):
        if not p.is_file() or done in p.parents or p.name.startswith("."):
            continue
        rec, created = add_file(p, connector="folder_inbox", ref=str(p.relative_to(inbox)), found_via=["inbox"])
        results.append((rec, created))
        target = done / p.relative_to(inbox)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(p), str(target))
    return results
