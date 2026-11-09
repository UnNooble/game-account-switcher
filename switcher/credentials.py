"""Riot username/password in Windows Credential Manager (never in the app's own files).

Windows encrypts these for your Windows user. You can see or delete them in
Control Panel → Credential Manager → Windows Credentials ("ValorantSwitcher/...").
"""
from __future__ import annotations

import json

from .errors import UserError

TARGET = "ValorantSwitcher/"
CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168


class Credentials:
    def __init__(self):
        import ctypes as C
        from ctypes import wintypes as W

        class FILETIME(C.Structure):
            _fields_ = [("lo", W.DWORD), ("hi", W.DWORD)]

        class CREDENTIAL(C.Structure):
            _fields_ = [("Flags", W.DWORD), ("Type", W.DWORD), ("TargetName", W.LPWSTR),
                        ("Comment", W.LPWSTR), ("LastWritten", FILETIME),
                        ("CredentialBlobSize", W.DWORD), ("CredentialBlob", C.POINTER(C.c_ubyte)),
                        ("Persist", W.DWORD), ("AttributeCount", W.DWORD), ("Attributes", C.c_void_p),
                        ("TargetAlias", W.LPWSTR), ("UserName", W.LPWSTR)]

        self.C, self.CREDENTIAL = C, CREDENTIAL
        api = C.WinDLL("advapi32", use_last_error=True)
        api.CredWriteW.argtypes = [C.POINTER(CREDENTIAL), W.DWORD]
        api.CredWriteW.restype = W.BOOL
        api.CredReadW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, C.POINTER(C.POINTER(CREDENTIAL))]
        api.CredReadW.restype = W.BOOL
        api.CredDeleteW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD]
        api.CredDeleteW.restype = W.BOOL
        api.CredFree.argtypes = [C.c_void_p]
        self.api = api

    def save(self, profile_id: str, username: str, password: str) -> None:
        C = self.C
        username, password = (username or "").strip(), password or ""
        if not username or not password:
            raise UserError("Enter both the Riot username and the password.")
        blob = json.dumps({"u": username, "p": password}).encode("utf-8")
        buf = (C.c_ubyte * len(blob)).from_buffer_copy(blob)
        cred = self.CREDENTIAL()
        cred.Type, cred.Persist = CRED_TYPE_GENERIC, CRED_PERSIST_LOCAL_MACHINE
        cred.TargetName = TARGET + profile_id
        cred.UserName = "riot-account"
        cred.CredentialBlobSize, cred.CredentialBlob = len(blob), C.cast(buf, C.POINTER(C.c_ubyte))
        try:
            if not self.api.CredWriteW(C.byref(cred), 0):
                raise UserError("Windows Credential Manager couldn't save the login.")
        finally:
            C.memset(buf, 0, len(blob))

    def load(self, profile_id: str):
        """(username, password) or None."""
        C = self.C
        ptr = C.POINTER(self.CREDENTIAL)()
        if not self.api.CredReadW(TARGET + profile_id, CRED_TYPE_GENERIC, 0, C.byref(ptr)):
            return None
        try:
            c = ptr.contents
            raw = C.string_at(c.CredentialBlob, c.CredentialBlobSize)
            data = json.loads(raw.decode("utf-8"))
            return data["u"], data["p"]
        except (ValueError, KeyError, TypeError):
            return None
        finally:
            self.api.CredFree(ptr)

    def has(self, profile_id: str) -> bool:
        return self.load(profile_id) is not None

    def delete(self, profile_id: str) -> None:
        self.api.CredDeleteW(TARGET + profile_id, CRED_TYPE_GENERIC, 0)


class NoCredentials:
    """Used in tests and when nothing is saved."""

    def __init__(self, items=None):
        self.items = dict(items or {})

    def save(self, pid, u, p):
        self.items[pid] = (u, p)

    def load(self, pid):
        return self.items.get(pid)

    def has(self, pid):
        return pid in self.items

    def delete(self, pid):
        self.items.pop(pid, None)
