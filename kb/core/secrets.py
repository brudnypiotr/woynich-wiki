"""Secrets never live in the repository. Default: Windows Credential Manager via `keyring` (per user, no admin)."""
from __future__ import annotations

import os

from kb.core.ports import SecretStore

SERVICE = "woynich-wiki"


class KeyringStore(SecretStore):
    def __init__(self, service: str = SERVICE, **_):
        import keyring  # imported lazily: optional dependency
        self._k = keyring
        self.service = service

    def get(self, name: str) -> str | None:
        return self._k.get_password(self.service, name)

    def set(self, name: str, value: str) -> None:
        self._k.set_password(self.service, name, value)

    def delete(self, name: str) -> None:
        try:
            self._k.delete_password(self.service, name)
        except self._k.errors.PasswordDeleteError:
            pass  # already gone


class EnvStore(SecretStore):
    """Read-only fallback: KB_SECRET_<NAME> environment variables (CI, service accounts)."""
    def __init__(self, **_):
        pass

    def get(self, name: str) -> str | None:
        return os.environ.get(f"KB_SECRET_{name.upper().replace('-', '_')}")

    def set(self, name: str, value: str) -> None:
        raise PermissionError("EnvStore is read-only; set the environment variable instead")


# Secrets that tools read from the environment: filled from the store when the variable is not set already.
ENV = {"copilot-github-token": "COPILOT_GITHUB_TOKEN"}


def apply_env(store: SecretStore | None = None) -> None:
    for name, var in ENV.items():
        if os.environ.get(var):
            continue
        try:
            value = (store or KeyringStore()).get(name)
        except Exception:  # keyring missing or locked: the Copilot CLI login still works
            return
        if value:
            os.environ[var] = value


def windows_credential(target: str) -> tuple[str, str] | None:
    """(user name, secret) of a generic credential in Windows Credential Manager, e.g. one stored with
    `cmdkey /generic:copilot-jira /user:<email> /pass:<token>` (as the jira-snapshot skill does). None elsewhere."""
    import sys
    if sys.platform != "win32":
        return None
    import ctypes
    import ctypes.wintypes as w

    class ATTR(ctypes.Structure):
        _fields_ = [("Keyword", w.LPWSTR), ("Flags", w.DWORD), ("ValueSize", w.DWORD), ("Value", ctypes.POINTER(ctypes.c_ubyte))]

    class CRED(ctypes.Structure):
        _fields_ = [("Flags", w.DWORD), ("Type", w.DWORD), ("TargetName", w.LPWSTR), ("Comment", w.LPWSTR),
                    ("LastWritten", w.FILETIME), ("CredentialBlobSize", w.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                    ("Persist", w.DWORD), ("AttributeCount", w.DWORD), ("Attributes", ctypes.POINTER(ATTR)),
                    ("TargetAlias", w.LPWSTR), ("UserName", w.LPWSTR)]
    adv = ctypes.windll.advapi32
    cred = ctypes.POINTER(CRED)()
    if not adv.CredReadW(ctypes.c_wchar_p(target), 1, 0, ctypes.byref(cred)):  # 1 = CRED_TYPE_GENERIC
        return None
    try:
        c = cred.contents
        if not c.CredentialBlobSize or not c.CredentialBlob:
            return None
        raw = ctypes.string_at(c.CredentialBlob, int(c.CredentialBlobSize))
        try:
            secret = raw.decode("utf-16-le").rstrip("\x00")
        except UnicodeDecodeError:
            secret = raw.decode("utf-8", errors="replace").rstrip("\x00")
        return c.UserName or "", secret
    finally:
        adv.CredFree(cred)
