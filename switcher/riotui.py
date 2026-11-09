"""Fills in Riot Client's own sign-in window for you.

Riot removed the background login service this app used first, so for a login that has to be typed
(first time, or after Riot signed you out) the app now operates the real Riot window the way a screen
reader would: Windows UI Automation sets the username and password boxes, ticks "Stay signed in" and
presses the arrow. No keystrokes or mouse clicks are simulated. The work is done by assets/riot_ui.ps1,
run by Windows PowerShell (built into every Windows 10/11). The password goes to it over stdin only.
"""
from __future__ import annotations

import base64
import json
import re
import subprocess

from . import resource
from .log import log

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run_powershell(request: dict, timeout: float) -> dict:
    """Send one request to riot_ui.ps1 and return its JSON reply ({'ok': False, 'error': ...} on trouble)."""
    script = resource("assets", "riot_ui.ps1")
    payload = base64.b64encode(json.dumps(request).encode("utf-8"))
    try:
        done = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            input=payload, capture_output=True, timeout=timeout, creationflags=NO_WINDOW)
    except FileNotFoundError:
        return {"ok": False, "error": "Windows PowerShell wasn't found"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "the Riot window didn't answer in time"}
    except OSError as e:
        return {"ok": False, "error": f"couldn't start PowerShell ({e})"}
    out = done.stdout.decode("utf-8", "replace").strip()
    try:
        data = json.loads(out.splitlines()[-1]) if out else {}
    except ValueError:
        data = {}
    if not isinstance(data, dict) or not data:
        err = done.stderr.decode("utf-8", "replace").strip().splitlines()
        return {"ok": False, "error": (err[-1][:160] if err else "no answer from the Riot window")}
    return data


def classify(inventory: dict) -> str:
    """What Riot's window is showing: none | login | invalid | mfa_code | mfa_mobile | captcha | unknown."""
    if not inventory.get("found"):
        return "none"
    text = " ".join(inventory.get("texts") or []).lower()
    edits = inventory.get("edits") or []
    has_password = any(e.get("password") for e in edits)
    if has_password:
        if any(w in text for w in ("incorrect", "invalid", "doesn't match", "does not match", "wrong")):
            return "invalid"
        return "login"
    if "captcha" in text or "verify you are human" in text:
        return "captcha"
    if edits and any(w in text for w in ("code", "verification", "verify")):
        return "mfa_code"
    if any(w in text for w in ("riot mobile", "approve", "notification", "authenticat")):
        return "mfa_mobile"
    return "unknown"


_ADDRESS = re.compile(r"[^\s<>\"'(),;:]*@[^\s<>\"'(),;]+")
_PHONE = re.compile(r"\+?[\d*•·.]+(?:[\s\-][\d*•·.]+){1,4}")


def mfa_details(inventory: dict) -> dict:
    """Where Riot says the code comes from: {'method': email|mobile|authenticator|sms|unknown, 'destination': masked address/number}."""
    texts = [str(x) for x in (inventory.get("texts") or [])]
    joined = " ".join(texts)
    low = joined.lower()
    found = _ADDRESS.search(joined)
    destination = found.group(0).strip(".,") if found else ""
    if destination:
        return {"method": "email", "destination": destination}
    if "e-mail" in low or "email" in low:
        return {"method": "email", "destination": ""}
    if "riot mobile" in low:
        return {"method": "mobile", "destination": ""}
    if "authenticator" in low:
        return {"method": "authenticator", "destination": ""}
    if "text message" in low or "sms" in low or "phone" in low:
        phone = next((m.group(0).strip() for m in _PHONE.finditer(joined) if sum(c.isdigit() for c in m.group(0)) >= 2
                      and ("*" in m.group(0) or "•" in m.group(0))), "")
        return {"method": "sms", "destination": phone}
    return {"method": "unknown", "destination": ""}


class RiotUI:
    def __init__(self, run=run_powershell):
        self._run = run

    def fill_login(self, username: str, password: str, stay: bool = True, wait: float = 25) -> dict:
        reply = self._run({"cmd": "fill", "username": username, "password": password, "stay": stay,
                           "wait": wait}, timeout=wait + 40)
        log(f"Riot window: fill sign-in form -> ok={reply.get('ok')} stay={reply.get('stay')} "
            f"error={reply.get('error', '')}" + self._shape(reply))
        if reply.get("debug"):
            log(f"Riot window: what Windows can see: {json.dumps(reply['debug'])[:1800]}")
        return reply

    def inventory(self, wait: float = 0) -> dict:
        return self._run({"cmd": "inventory", "wait": wait}, timeout=wait + 30)

    def fill_code(self, code: str, wait: float = 6) -> dict:
        reply = self._run({"cmd": "code", "code": code, "wait": wait}, timeout=wait + 30)
        log(f"Riot window: enter code -> ok={reply.get('ok')} error={reply.get('error', '')}")
        if reply.get("debug"):
            log(f"Riot window: what Windows can see: {json.dumps(reply['debug'])[:1800]}")
        return reply

    def click(self, pattern: str, wait: float = 4) -> dict:
        reply = self._run({"cmd": "click", "pattern": pattern, "wait": wait}, timeout=wait + 30)
        log(f"Riot window: click /{pattern}/ -> ok={reply.get('ok')} clicked={reply.get('clicked', '')} "
            f"error={reply.get('error', '')}")
        return reply

    @staticmethod
    def _shape(reply: dict) -> str:
        """What the window looked like (control names only), so a miss can be diagnosed from the log."""
        if "edits" not in reply:
            return ""
        edits = ",".join(("pw:" if e.get("password") else "") + str(e.get("name"))[:20] for e in reply["edits"])
        buttons = ",".join(str(b.get("name"))[:16] or "?" for b in reply.get("buttons", []))
        return f" | edits=[{edits}] buttons=[{buttons}] checks={reply.get('checks')} texts={reply.get('texts', [])[:12]}"
