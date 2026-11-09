"""Passphrase-protected backup you can carry to another PC or a USB stick.

Normal saved logins are locked to one Windows user on one PC (DPAPI). A backup
can't be, so it is encrypted with a passphrase YOU choose instead:

    scrypt(passphrase, random salt) -> 32-byte key -> Fernet (authenticated AES).

The backup file holds working logins. Anyone with the file AND the passphrase can
sign into these accounts, so keep it like a password and choose a strong passphrase.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os

from .errors import UserError

MAGIC = b"VASBK1\n"                 # file header: Valorant Account Switcher BacKup v1
SALT_BYTES = 16
SCRYPT = dict(n=2 ** 15, r=8, p=1, dklen=32, maxmem=128 * 1024 * 1024)   # ~100 ms, memory-hard
MAX_BACKUP = 128 * 1024 * 1024


def _key(passphrase: str, salt: bytes) -> bytes:
    raw = hashlib.scrypt((passphrase or "").encode("utf-8"), salt=salt, **SCRYPT)
    return base64.urlsafe_b64encode(raw)


def _fernet(key: bytes):
    from cryptography.fernet import Fernet  # bundled dependency
    return Fernet(key)


def check_passphrase(passphrase: str) -> None:
    if len(passphrase or "") < 8:
        raise UserError("Choose a passphrase of at least 8 characters. Anyone with the backup and this "
                        "passphrase can sign into these accounts, so make it a good one.")


def export_bundle(profiles: list[dict], passphrase: str, box=None) -> bytes:
    """profiles: [{id,label,riot_id,identity,files,(username,password)}]. Returns bytes to save."""
    check_passphrase(passphrase)
    payload = json.dumps({"version": 1, "profiles": profiles}, separators=(",", ":")).encode("utf-8")
    if box is not None:  # test seam
        return MAGIC + b"\x00" * SALT_BYTES + box.encrypt(payload)
    salt = os.urandom(SALT_BYTES)
    token = _fernet(_key(passphrase, salt)).encrypt(payload)
    return MAGIC + salt + token


def import_bundle(blob: bytes, passphrase: str, box=None) -> list[dict]:
    if len(blob) > MAX_BACKUP:
        raise UserError("That backup file is too large to be valid.")
    if not blob.startswith(MAGIC):
        raise UserError("That file isn't a Game Account Switcher backup.")
    body = blob[len(MAGIC):]
    salt, token = body[:SALT_BYTES], body[SALT_BYTES:]
    try:
        if box is not None:
            payload = box.decrypt(token)
        else:
            from cryptography.fernet import InvalidToken
            try:
                payload = _fernet(_key(passphrase, salt)).decrypt(token)
            except InvalidToken:
                raise UserError("Wrong passphrase, or the backup file is damaged.") from None
        data = json.loads(payload)
        if data.get("version") != 1 or not isinstance(data["profiles"], list):
            raise ValueError
        return data["profiles"]
    except (ValueError, KeyError, TypeError):
        raise UserError("That backup couldn't be read. Check the passphrase and the file.") from None


# ---- glue between the backup and the app's own stores ----

def gather(store, vault, creds, include_passwords: bool) -> list[dict]:
    """Collect every profile that has a usable saved login into portable form."""
    out = []
    for p in store.read()["profiles"]:
        saved = vault.load(p["id"])
        if not saved:
            continue
        entry = {"label": p["label"], "riot_id": p.get("riot_id", ""),
                 "identity": saved.get("identity", ""), "files": saved["files"]}
        if include_passwords:
            login = creds.load(p["id"])
            if login:
                entry["username"], entry["password"] = login
        out.append(entry)
    if not out:
        raise UserError("There are no saved logins to back up yet. Add an account first.")
    return out


def apply(profiles: list[dict], store, vault, creds) -> tuple[int, int]:
    """Write imported profiles onto THIS PC. Re-encrypts logins with this PC's protection.

    Returns (added, updated). Matches existing accounts by Riot identity so re-importing
    doesn't create duplicates.
    """
    import uuid

    existing = store.read()["profiles"]
    by_identity = {vault.identity(p["id"]): p["id"] for p in existing if vault.identity(p["id"])}
    added = updated = 0
    for entry in profiles:
        identity = entry.get("identity") or ""
        files = entry.get("files")
        if not isinstance(files, dict) or not identity:
            continue
        pid = by_identity.get(identity)
        if pid:
            updated += 1
        else:
            pid = str(uuid.uuid4())
            store.add(entry.get("label") or "Imported", entry.get("riot_id", ""), profile_id=pid)
            added += 1
        vault._write(vault.path(pid), {"identity": identity, "files": vault.files.clean(files)})
        if entry.get("username") and entry.get("password"):
            try:
                creds.save(pid, entry["username"], entry["password"])
            except (UserError, OSError):
                pass
    return added, updated
