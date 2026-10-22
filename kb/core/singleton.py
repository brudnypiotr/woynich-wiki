"""One running copy per resource: an OS lock on a file, taken at once and released by the OS when the process ends
(also after a crash), so there is no stale lock to clean up. Windows: msvcrt.locking; elsewhere: fcntl.flock."""
from __future__ import annotations

import os
from pathlib import Path


class Lock:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._f = None

    def acquire(self) -> bool:
        """True when this process now holds the lock; False when another process does. Never waits."""
        if self._f:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        f = open(self.path, "a+b")  # noqa: SIM115  kept open while the lock is held
        try:
            if os.name == "nt":
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            return False
        self._f = f
        return True

    def release(self) -> None:
        if not self._f:
            return
        try:
            if os.name == "nt":
                import msvcrt
                self._f.seek(0)
                msvcrt.locking(self._f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._f.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        self._f.close()
        self._f = None
