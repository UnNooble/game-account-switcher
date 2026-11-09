"""Riot "Stay signed in" files: snapshot, restore, encrypt, crash recovery.

Only an allowlist of Riot login files is ever touched. Everything else in
Riot's folder (settings, logs, game installs) is left alone.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import time

from .errors import UserError

# Relative to %LOCALAPPDATA%\Riot Games\Riot Client
LOGIN_FILES = ("Data/RiotGamesPrivateSettings.yaml", "Data/RiotClientPrivateSettings.yaml",
               # Per-account client settings (region etc.). Working switchers swap this too.
               "Config/RiotClientSettings.yaml")
LOGIN_TREES = ("Data/Cookies", "Data/Sessions")
MAIN_FILE = LOGIN_FILES[0]
MAX_BYTES = 64 * 1024 * 1024
MAX_FILES = 5000
# Riot's login file is ~0.5 KB when signed out and ~2.5 KB once "Stay signed in" has saved a token.
TOKEN_MIN_BYTES = 1024

_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10))}
_SUB = re.compile(r'name:\s*"?sub"?\s*\n(?:[^\n]*\n){0,6}?\s*value:\s*"?([0-9a-fA-F-]{36})"?')


def atomic_write(path: Path, raw: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False, prefix=".tmp-") as f:
            tmp = Path(f.name)
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                # Antivirus or Windows Search can hold a file for a moment.
                if attempt == 4:
                    raise
                time.sleep(0.4)
    finally:
        if tmp and tmp.exists():
            tmp.unlink()


class DPAPI:
    """Windows current-user encryption. Only this Windows user on this PC can decrypt."""

    def __init__(self):
        import ctypes as C
        from ctypes import wintypes as W

        class Blob(C.Structure):
            _fields_ = [("size", W.DWORD), ("data", C.POINTER(C.c_ubyte))]

        self.C, self.Blob = C, Blob
        self.crypt = C.WinDLL("crypt32", use_last_error=True)
        self.kernel = C.WinDLL("kernel32", use_last_error=True)
        self.kernel.LocalFree.argtypes = [C.c_void_p]
        self.kernel.LocalFree.restype = C.c_void_p
        for name in ("CryptProtectData", "CryptUnprotectData"):
            fn = getattr(self.crypt, name)
            fn.argtypes = [C.POINTER(Blob), C.c_void_p, C.POINTER(Blob), C.c_void_p,
                           C.c_void_p, W.DWORD, C.POINTER(Blob)]
            fn.restype = W.BOOL

    def _run(self, raw: bytes, decrypt: bool) -> bytes:
        C = self.C
        buf = (C.c_ubyte * len(raw)).from_buffer_copy(raw)
        src, dst = self.Blob(len(raw), buf), self.Blob()
        fn = self.crypt.CryptUnprotectData if decrypt else self.crypt.CryptProtectData
        try:
            # 0x1 = CRYPTPROTECT_UI_FORBIDDEN
            if not fn(C.byref(src), None, None, None, None, 0x1, C.byref(dst)):
                raise UserError("Windows could not unlock this saved login. It only works for the same "
                                "Windows user on the same PC. Use Edit → Sign in again.")
            return C.string_at(dst.data, dst.size)
        finally:
            C.memset(buf, 0, len(raw))
            if dst.data:
                C.memset(dst.data, 0, dst.size)
                self.kernel.LocalFree(dst.data)

    def encrypt(self, raw: bytes) -> bytes:
        return self._run(raw, False)

    def decrypt(self, raw: bytes) -> bytes:
        return self._run(raw, True)


class SessionFiles:
    """Reads and writes the allowlisted login files inside Riot's data folder."""

    def __init__(self, riot_data: Path):
        self.base = Path(riot_data)

    def _safe(self, relative: str) -> Path:
        target = self.base / relative
        chain = [p for p in (*reversed(target.parents), target) if p == self.base or self.base in p.parents]
        for item in chain:
            try:
                info = os.lstat(item)
            except FileNotFoundError:
                break
            # 0x400 = FILE_ATTRIBUTE_REPARSE_POINT (symlinks and junctions)
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise UserError("Riot's login folder contains a link or junction. Switching was stopped "
                                "to protect your other files.")
        return target

    @staticmethod
    def allowed(name: str) -> bool:
        p = PurePosixPath(name)
        if (not name or p.is_absolute() or str(p) != name or "\\" in name or ":" in name or ".." in p.parts
                or any(ord(c) < 32 for c in name)
                or any(part.endswith((" ", ".")) or part.split(".")[0].upper() in _RESERVED for part in p.parts)):
            return False
        return name in LOGIN_FILES or any(name.startswith(t + "/") for t in LOGIN_TREES)

    def snapshot(self) -> dict:
        paths = [self._safe(n) for n in LOGIN_FILES]
        for tree in LOGIN_TREES:
            root = self._safe(tree)
            if root.is_dir():
                for parent, dirs, files in os.walk(root, followlinks=False):
                    for child in files:
                        paths.append(self._safe((Path(parent) / child).relative_to(self.base).as_posix()))
                    for child in dirs:
                        self._safe((Path(parent) / child).relative_to(self.base).as_posix())
        result: dict = {}
        total = 0
        for path in paths:
            if path.is_file():
                raw = path.read_bytes()
                total += len(raw)
                if total > MAX_BYTES or len(result) >= MAX_FILES:
                    raise UserError("Riot's login data is unexpectedly large. Nothing was changed.")
                result[path.relative_to(self.base).as_posix()] = base64.b64encode(raw).decode()
        return result

    @classmethod
    def clean(cls, files) -> dict:
        """Keep only allowlisted entries (older snapshots may hold extra files)."""
        if not isinstance(files, dict) or len(files) > MAX_FILES:
            raise ValueError("bad snapshot")
        out, total = {}, 0
        for name, value in files.items():
            if not isinstance(name, str) or not isinstance(value, str):
                raise ValueError("bad snapshot")
            if cls.allowed(name):
                total += len(value) * 3 // 4
                if total > MAX_BYTES:
                    raise ValueError("snapshot too large")
                base64.b64decode(value, validate=True)
                out[name] = value
        return out

    def apply(self, files: dict) -> None:
        files = self.clean(files)
        current = self.snapshot()  # also pre-checks every existing path for links
        for name in files:
            self._safe(name)
        for name, value in files.items():
            atomic_write(self._safe(name), base64.b64decode(value))
        for name in current.keys() - files.keys():
            self._safe(name).unlink(missing_ok=True)

    def text(self, name=MAIN_FILE) -> str:
        try:
            return self._safe(name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def has_remembered_login(self) -> bool:
        body = self.text()
        return "ssid" in body or len(body.encode()) >= TOKEN_MIN_BYTES

    def describe(self) -> str:
        """Safe one-line summary for the log: sizes and flags only, never contents."""
        body = self.text()
        sessions = self.base / "Data" / "Sessions"
        n = sum(1 for _ in sessions.rglob("*") if _.is_file()) if sessions.is_dir() else 0
        return (f"login file {len(body.encode())} bytes, token={'yes' if self.has_remembered_login() else 'no'}, "
                f"Sessions files={n}")

    def offline_identity(self):
        """Best effort: the account id inside Riot's saved login file, if readable."""
        match = _SUB.search(self.text())
        return match.group(1).lower() if match else None


class Vault:
    """Encrypted per-profile snapshots plus a crash-recovery journal."""

    def __init__(self, data_root: Path, files: SessionFiles, crypto):
        self.dir = Path(data_root) / "sessions"
        self.files, self.crypto = files, crypto
        self.journal = self.dir / "recovery.bin"

    def path(self, profile_id: str) -> Path:
        from .store import valid_id
        if not valid_id(profile_id):
            raise UserError("Invalid profile.")
        return self.dir / (profile_id + ".bin")

    def _write(self, path: Path, value: dict) -> None:
        atomic_write(path, self.crypto.encrypt(json.dumps(value, separators=(",", ":")).encode()))

    def _read(self, path: Path) -> dict:
        try:
            if path.stat().st_size > MAX_BYTES * 2:
                raise ValueError("too large")
            value = json.loads(self.crypto.decrypt(path.read_bytes()))
            value["files"] = SessionFiles.clean(value["files"])
            return value
        except (ValueError, KeyError, TypeError):
            raise UserError("A saved login is damaged. Use Edit → Sign in again for that account.") from None

    def load(self, profile_id):
        path = self.path(profile_id)
        return self._read(path) if path.exists() else None

    def identity(self, profile_id):
        try:
            saved = self.load(profile_id)
        except UserError:
            return None
        return saved.get("identity") if saved else None

    def find(self, identity, profile_ids):
        for pid in profile_ids:
            if identity and self.identity(pid) == identity:
                return pid
        return None

    def capture(self, profile_id: str, identity: str, require_token=True) -> None:
        """Save Riot's current login files as this profile."""
        from .log import log
        log(f"saving login for profile {profile_id[:8]}: {self.files.describe()}")
        if require_token and not self.files.has_remembered_login():
            raise UserError("Riot didn't keep this login. Sign in again and make sure "
                            "'Stay signed in' is ticked.")
        self._write(self.path(profile_id), {"identity": identity, "files": self.files.snapshot(),
                                            "saved_at": int(time.time())})

    def delete(self, profile_id: str) -> None:
        self.path(profile_id).unlink(missing_ok=True)

    # Restoring is journaled: if the PC loses power mid-copy, the next run
    # puts back the previous files instead of leaving a half-written mix.
    def restore(self, files) -> None:
        if self.journal.exists():
            raise UserError("A previous switch needs recovery first.")
        self._write(self.journal, {"files": self.files.snapshot()})
        self.files.apply(files or {})
        self.journal.unlink()

    def blank(self) -> dict:
        """Files for a clean Riot login screen: no login, but keep the client's own settings."""
        return {k: v for k, v in self.files.snapshot().items() if k.startswith("Config/")}

    def needs_recovery(self) -> bool:
        return self.journal.exists()

    def recover(self) -> None:
        if self.journal.exists():
            self.files.apply(self._read(self.journal)["files"])
            self.journal.unlink()
