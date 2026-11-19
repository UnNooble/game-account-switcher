"""Profile list and settings (profiles.json). Holds no secrets.

Uses the same data folder as Valorant Profiles 2.x, so accounts that were
already set up in the old version keep working after upgrading.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import threading
import time
import uuid

from .errors import UserError
from .vault import atomic_write

SCHEMA = 3


def data_directory() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        raise UserError("This app runs on Windows 10 or 11.")
    return Path(base) / "ValorantProfiles"


def valid_id(value) -> bool:
    try:
        return str(uuid.UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


def clean_label(value) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        raise UserError("Give the account a name, for example Main or Alt.")
    if len(text) > 40:
        raise UserError("Keep the account name under 40 characters.")
    return text


def empty() -> dict:
    return {"version": SCHEMA, "profiles": [], "active": None, "settings": {"riot_path": "", "deceive_path": "", "appear_offline": False,
                                                                       "tracker_path": "", "stats_overlay": False,
                                                                       "animations": True, "close_action": "ask",
                                                                       "tidy_after_launch": True}}


CLOSE_ACTIONS = ("ask", "tray", "quit")
ICON_RE = re.compile(r"^(letter|custom|glyph:[a-z]{1,20})$")
COLOR_RE = re.compile(r"^#[0-9a-f]{6}$")


def _profile(p: dict) -> dict:
    """One account, with every optional field present and checked (older files simply lack them)."""
    icon = p.get("icon") if isinstance(p.get("icon"), str) and ICON_RE.match(p.get("icon")) else "letter"
    color = str(p.get("color") or "").lower()
    played = p.get("last_played")
    return {"id": p["id"], "label": clean_label(p["label"]), "riot_id": str(p.get("riot_id") or "")[:64],
            "icon": icon, "color": color if COLOR_RE.match(color) else "",
            "last_played": int(played) if isinstance(played, (int, float)) and played > 0 else 0}


class Store:
    """Thread-safe reader/writer. Every write is atomic."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.path = self.root / "profiles.json"
        self.lock = threading.RLock()

    def read(self) -> dict:
        with self.lock:
            if not self.path.exists():
                return empty()
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                return self._normalise(raw)
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                raise UserError(
                    "The profile list is damaged: " + str(self.path) +
                    "\nRename or delete that file to start fresh. Saved sessions are kept separately.") from None

    @staticmethod
    def _normalise(raw: dict) -> dict:
        # Accepts schema 1 (Valorant Profiles 2.x) and schema 3.
        if raw.get("version") not in (1, SCHEMA):
            raise ValueError("unknown schema")
        data = empty()
        seen = set()
        for p in raw["profiles"]:
            if not valid_id(p["id"]) or p["id"] in seen:
                raise ValueError("bad id")
            seen.add(p["id"])
            data["profiles"].append(_profile(p))
        active = raw.get("active")
        data["active"] = active if active in seen else None
        path = raw.get("settings", {}).get("riot_path", "")
        data["settings"]["riot_path"] = path if isinstance(path, str) else ""
        deceive = raw.get("settings", {}).get("deceive_path", "")
        data["settings"]["deceive_path"] = deceive if isinstance(deceive, str) else ""
        data["settings"]["appear_offline"] = bool(raw.get("settings", {}).get("appear_offline", False))
        tracker = raw.get("settings", {}).get("tracker_path", "")
        data["settings"]["tracker_path"] = tracker if isinstance(tracker, str) else ""
        data["settings"]["stats_overlay"] = bool(raw.get("settings", {}).get("stats_overlay", False))
        data["settings"]["animations"] = bool(raw.get("settings", {}).get("animations", True))
        data["settings"]["tidy_after_launch"] = bool(raw.get("settings", {}).get("tidy_after_launch", True))
        close = raw.get("settings", {}).get("close_action", "ask")
        data["settings"]["close_action"] = close if close in CLOSE_ACTIONS else "ask"
        return data

    def write(self, data: dict) -> None:
        with self.lock:
            data = dict(data, version=SCHEMA)
            atomic_write(self.path, json.dumps(data, indent=2).encode("utf-8"))

    def get(self, profile_id):
        return next((p for p in self.read()["profiles"] if p["id"] == profile_id), None)

    def add(self, label, riot_id="", profile_id=None) -> str:
        with self.lock:
            data = self.read()
            profile_id = profile_id or str(uuid.uuid4())
            data["profiles"].append(_profile({"id": profile_id, "label": label, "riot_id": riot_id}))
            self.write(data)
            return profile_id

    def update(self, profile_id, **fields) -> None:
        with self.lock:
            data = self.read()
            for p in data["profiles"]:
                if p["id"] == profile_id:
                    if "label" in fields:
                        p["label"] = clean_label(fields["label"])
                    if "riot_id" in fields:
                        p["riot_id"] = str(fields["riot_id"] or "")[:64]
                    if "icon" in fields or "color" in fields:
                        p.update(_profile(dict(p, icon=fields.get("icon", p["icon"]),
                                                  color=fields.get("color", p["color"]))))
            self.write(data)

    def remove(self, profile_id) -> None:
        with self.lock:
            data = self.read()
            data["profiles"] = [p for p in data["profiles"] if p["id"] != profile_id]
            if data["active"] == profile_id:
                data["active"] = None
            self.write(data)

    def move(self, profile_id, offset: int) -> None:
        with self.lock:
            data = self.read()
            items = data["profiles"]
            i = next((n for n, p in enumerate(items) if p["id"] == profile_id), None)
            if i is None or not 0 <= i + offset < len(items):
                return
            items[i], items[i + offset] = items[i + offset], items[i]
            self.write(data)

    def reorder(self, profile_ids) -> None:
        """Put the accounts in this order (from dragging). Unknown ids are ignored, missing ones keep their place
        at the end, so a stale list can never lose an account."""
        with self.lock:
            data = self.read()
            by_id = {p["id"]: p for p in data["profiles"]}
            ordered = [by_id.pop(i) for i in profile_ids if i in by_id]
            data["profiles"] = ordered + [p for p in data["profiles"] if p["id"] in by_id]
            self.write(data)

    def set_active(self, profile_id, played=True) -> None:
        """Mark the account as the current one; played=True also records now as its last-played time."""
        with self.lock:
            data = self.read()
            data["active"] = profile_id
            if played:
                for p in data["profiles"]:
                    if p["id"] == profile_id:
                        p["last_played"] = int(time.time())
            self.write(data)

    def set_tidy_after_launch(self, value: bool) -> None:
        with self.lock:
            data = self.read()
            data["settings"]["tidy_after_launch"] = bool(value)
            self.write(data)

    def set_close_action(self, value: str) -> None:
        with self.lock:
            data = self.read()
            data["settings"]["close_action"] = value if value in CLOSE_ACTIONS else "ask"
            self.write(data)

    def set_appear_offline(self, value: bool) -> None:
        with self.lock:
            data = self.read()
            data["settings"]["appear_offline"] = bool(value)
            self.write(data)

    def set_animations(self, value: bool) -> None:
        with self.lock:
            data = self.read()
            data["settings"]["animations"] = bool(value)
            self.write(data)

    def set_stats_overlay(self, value: bool) -> None:
        with self.lock:
            data = self.read()
            data["settings"]["stats_overlay"] = bool(value)
            self.write(data)

    def set_tracker_path(self, value: str) -> None:
        with self.lock:
            data = self.read()
            data["settings"]["tracker_path"] = value
            self.write(data)

    def set_deceive_path(self, value: str) -> None:
        with self.lock:
            data = self.read()
            data["settings"]["deceive_path"] = value
            self.write(data)

    def set_riot_path(self, value: str) -> None:
        with self.lock:
            data = self.read()
            data["settings"]["riot_path"] = value
            self.write(data)
