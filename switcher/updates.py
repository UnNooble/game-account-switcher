"""Update check: asks GitHub for the newest release and compares it with the installed version.

Only one small anonymous request goes out (no account data). Any failure is silent for the automatic
check. Works only while the repository's releases are public.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import VERSION
from .vault import atomic_write

REPO = "UnNooble/game-account-switcher"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
PAGE_PREFIX = f"https://github.com/{REPO}/"
RELEASES_URL = PAGE_PREFIX + "releases/latest"
CHECK_EVERY = 24 * 3600


@dataclass
class Result:
    status: str          # "newer" | "current" | "unavailable"
    version: str = ""
    url: str = ""


def parse_version(text) -> tuple:
    """'v3.7.0' -> (3, 7, 0). Returns () when it does not look like a version."""
    match = re.match(r"^\s*v?(\d+(?:\.\d+){0,3})", str(text or ""))
    return tuple(int(p) for p in match.group(1).split(".")) if match else ()


def is_newer(candidate, current=VERSION) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    if not a or not b:
        return False
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


def safe_url(url) -> str:
    """Only ever hand out a link to this project's own GitHub pages."""
    url = str(url or "")
    return url if url.startswith(PAGE_PREFIX) else RELEASES_URL


def check(opener=urllib.request.urlopen, current=VERSION, timeout=6) -> Result:
    request = urllib.request.Request(API_URL, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "GameAccountSwitcher"})
    try:
        with opener(request, timeout=timeout) as response:
            data = json.loads(response.read(200_000).decode("utf-8"))
        tag = str(data["tag_name"])
    except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError):
        return Result("unavailable")
    if data.get("draft") or data.get("prerelease"):
        return Result("current")
    if is_newer(tag, current):
        return Result("newer", tag.lstrip("vV"), safe_url(data.get("html_url")))
    return Result("current", tag.lstrip("vV"))


class Settings:
    """update.json in the data folder: {"auto": true, "last_check": 0}. Holds no secrets."""

    def __init__(self, root: Path):
        self.path = Path(root) / "update.json"

    def read(self) -> dict:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return {"auto": bool(raw.get("auto", True)), "last_check": float(raw.get("last_check", 0))}
        except (OSError, ValueError, TypeError, AttributeError):
            return {"auto": True, "last_check": 0.0}

    def write(self, **changes):
        data = {**self.read(), **changes}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(self.path, json.dumps(data).encode("utf-8"))
        except OSError:
            pass

    def due(self, now=None) -> bool:
        data = self.read()
        return data["auto"] and (now or time.time()) - data["last_check"] >= CHECK_EVERY


def check_in_background(deliver, check_fn=check):
    """Run the check on a thread; deliver(result) is called from that thread (queue it, don't touch Tk)."""
    threading.Thread(target=lambda: deliver(check_fn()), daemon=True).start()
