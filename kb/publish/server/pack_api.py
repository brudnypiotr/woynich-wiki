"""Knowledge pack download and import (kb/knowledge/pack.py does the work). Both stream: a pack with the large
originals can be hundreds of MB."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from urllib.parse import quote

from kb.knowledge import pack
from kb.publish.server import WRITE_LOCK, chat_api
from kb.publish.server.http import route
from kb.publish.server.update_api import update_blocker

MAX_PACK = 8_000_000_000


@route("GET", r"/api/pack/export")
def export(h):
    if WRITE_LOCK.locked():
        raise ValueError("sources are being added to the wiki; export when Add sources is done")
    tmp = Path(tempfile.mkdtemp(prefix="kbpack-out-"))
    try:
        with WRITE_LOCK:
            r = pack.export(tmp / "pack.zip")
        name = f"{pack.slug(r['title'])}.kbpack.zip"
        f = tmp / "pack.zip"
        h.send_response(200)
        h.send_header("Content-Type", "application/zip")
        h.send_header("Content-Length", str(f.stat().st_size))
        h.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(name)}")
        h.send_header("Cache-Control", "no-store")
        h.end_headers()
        with f.open("rb") as src:
            shutil.copyfileobj(src, h.wfile, 1 << 20)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@route("POST", r"/api/pack/import")
def import_(h):
    if (why := update_blocker()):
        raise ValueError(why.replace("Update when", "Import when"))
    n = int(h.headers.get("Content-Length") or 0)
    if not n or n > MAX_PACK:
        raise ValueError("choose a knowledge pack (.kbpack.zip)")
    tmp = Path(tempfile.mkdtemp(prefix="kbpack-in-"))
    try:
        f = tmp / "pack.zip"
        with f.open("wb") as out:
            left = n
            while left:
                chunk = h.rfile.read(min(left, 1 << 20))
                if not chunk:
                    break
                out.write(chunk); left -= len(chunk)
        with WRITE_LOCK:
            chat_api.close_live(fresh=True)  # open discussions read the old wiki
            r = pack.import_pack(f)
        return h.send(200, r)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
