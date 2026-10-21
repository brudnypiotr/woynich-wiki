"""The app's log: everything `kb serve` prints (and Python errors) also goes to local/logs/serve.log, with the time,
so a feedback package or support can see what happened after the window was closed. Rotates at 1 MB, keeps 3 files."""
from __future__ import annotations

import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from kb.publish import appgit

MAX_BYTES, KEEP = 1_000_000, 3


def folder() -> Path:
    d = appgit.local() / "logs"
    d.mkdir(exist_ok=True)
    return d


def files() -> list[Path]:
    return sorted(folder().glob("serve.log*"))


class _Tee:
    """A stream that writes to the console and, line by line with a timestamp, to the rotating log file."""

    def __init__(self, stream, handler: RotatingFileHandler, tag: str):
        self.stream, self.handler, self.tag, self.buf, self.lock = stream, handler, tag, "", threading.Lock()

    def write(self, s: str) -> int:
        try:
            self.stream.write(s)
        except (UnicodeEncodeError, ValueError, OSError):
            pass
        with self.lock:
            self.buf += s
            *lines, self.buf = self.buf.split("\n")
            for line in lines:
                self._file(line)
        return len(s)

    def _file(self, line: str) -> None:
        try:
            self.handler.stream.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {self.tag} {line}\n")
            self.handler.stream.flush()
            if self.handler.stream.tell() > MAX_BYTES:
                self.handler.doRollover()
        except (OSError, ValueError):
            pass

    def flush(self) -> None:
        try:
            self.stream.flush()
        except (OSError, ValueError):
            pass

    def __getattr__(self, name):  # isatty, encoding, fileno, ... from the console stream
        return getattr(self.stream, name)


_STARTED = False


def start() -> Path:
    """Send stdout and stderr to the log file too (once per process)."""
    global _STARTED
    path = folder() / "serve.log"
    if not _STARTED:
        h = RotatingFileHandler(path, maxBytes=MAX_BYTES, backupCount=KEEP, encoding="utf-8")
        sys.stdout = _Tee(sys.stdout, h, "out")
        sys.stderr = _Tee(sys.stderr, h, "err")
        _STARTED = True
    return path
