"""Riot Client control: find it, close it, open it, ask who is signed in, launch VALORANT.

Uses only process start/stop and Riot Client's own local (127.0.0.1) API.
No keyboard/mouse simulation, no game memory access, nothing touches Vanguard.
"""
from __future__ import annotations

import base64
import http.client
import json
import os
from pathlib import Path
import ssl
import sys
import subprocess
import time

from .errors import UserError
from .log import log

# Every process that belongs to the Riot Client itself (old and new names).
CLIENT_PROCESSES = {
    "riotclientservices.exe", "riot client.exe", "riotclientux.exe",
    "riotclientuxrender.exe", "riotclientcrashhandler.exe",
}
# Games that depend on the client. We never close these.
GAME_PROCESSES = {
    "valorant-win64-shipping.exe", "valorant.exe", "league of legends.exe",
    "leagueclient.exe", "leagueclientux.exe", "lor.exe", "2xko.exe",
}
VALORANT_PROCESSES = {"valorant-win64-shipping.exe", "valorant.exe"}
GAME_TITLES = {
    "valorant-win64-shipping.exe": "VALORANT", "valorant.exe": "VALORANT",
    "league of legends.exe": "League of Legends", "leagueclient.exe": "League of Legends",
    "leagueclientux.exe": "League of Legends", "lor.exe": "Legends of Runeterra", "2xko.exe": "2XKO",
}
# Vanguard (vgc.exe / vgtray.exe) is deliberately absent from both lists.

LAUNCH_PATH = "/product-launcher/v1/products/valorant/patchlines/live"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def valid_deceive(path) -> Path:
    exe = Path(str(path)).resolve()
    if not (exe.name.lower().startswith("deceive") and exe.suffix.lower() == ".exe" and exe.is_file()):
        raise UserError("Appear offline needs Deceive.exe, but it wasn't found where it was last set. "
                        "Choose it again in ··· → Appear offline setup.")
    return exe


def discover_deceive() -> str:
    """Look in the usual places for a Deceive.exe the user already downloaded."""
    home = Path.home()
    roots = [home / "Downloads", home / "Desktop", home / "Documents",
             Path(os.environ.get("LOCALAPPDATA", "")) / "Programs",
             Path(os.environ.get("ProgramFiles", "C:/Program Files")),
             Path(os.environ.get("APPDATA", "")) / "Deceive"]
    for root in roots:
        try:
            for depth in ("Deceive*.exe", "*/Deceive*.exe"):
                for hit in root.glob(depth):
                    if hit.is_file():
                        return str(hit)
        except OSError:
            continue
    return ""


def discover_client() -> str:
    """Find RiotClientServices.exe on any drive using Riot's own install index."""
    program_data = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
    candidates = []
    try:
        data = json.loads((program_data / "Riot Games" / "RiotClientInstalls.json").read_text(encoding="utf-8"))
        candidates += [data.get("rc_default", ""), data.get("rc_live", "")]
        candidates += list((data.get("associated_client") or {}).values())
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    for drive in "CDEFG":
        candidates.append(rf"{drive}:\Riot Games\Riot Client\RiotClientServices.exe")
    for value in candidates:
        if isinstance(value, str) and value:
            p = Path(value)
            if p.name.lower() == "riotclientservices.exe" and p.is_file():
                return str(p)
    return ""


def jwt_sub(token):
    """Read 'sub' (the account id) from a JWT payload. No signature check needed: it's only a label."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        sub = json.loads(base64.urlsafe_b64decode(payload)).get("sub")
        return sub.lower() if isinstance(sub, str) and 1 <= len(sub) <= 128 else None
    except (AttributeError, IndexError, ValueError, TypeError):
        return None


def parse_userinfo(info):
    """Return (account_id, 'Name#TAG') from Riot's userinfo response."""
    user = info.get("userInfo", info) if isinstance(info, dict) else None
    if isinstance(user, str):
        try:
            user = json.loads(user)
        except ValueError:
            return None, ""
    if not isinstance(user, dict):
        return None, ""
    sub = user.get("sub")
    sub = sub.lower() if isinstance(sub, str) and 1 <= len(sub) <= 128 else None
    acct = user.get("acct") if isinstance(user.get("acct"), dict) else {}
    return sub, riot_name(acct.get("game_name"), acct.get("tag_line"))


def riot_name(name, tag):
    name, tag = str(name or ""), str(tag or "")
    return (f"{name}#{tag}" if name and tag else name)[:64]


def is_authorized(auth, session):
    if isinstance(auth, dict) and auth.get("accessToken"):
        return True
    return isinstance(session, dict) and session.get("type") == "authenticated"



def _reason(raw: bytes) -> str:
    """Short, safe summary of a Riot reply for logs and messages: only its type/error/message words."""
    try:
        data = json.loads(raw)
    except ValueError:
        return ""
    if not isinstance(data, dict):
        return ""
    parts = []
    for key in ("type", "error", "errorCode", "message", "reason"):
        value = data.get(key)
        if isinstance(value, str) and value:
            parts.append(f"{key}={value[:60]}")
    return " ".join(parts)


class RiotClient:
    def __init__(self, exe_path: str = ""):
        import psutil
        self.psutil = psutil
        found = exe_path or discover_client()
        if not found:
            raise UserError("Riot Client wasn't found. Install VALORANT, or open Settings and choose "
                            "RiotClientServices.exe (usually C:\\Riot Games\\Riot Client).")
        self.exe = Path(found).resolve()
        if self.exe.name.lower() != "riotclientservices.exe" or not self.exe.is_file():
            raise UserError("Settings must point to RiotClientServices.exe.")
        self.install = self.exe.parent
        self.data = Path(os.environ["LOCALAPPDATA"]) / "Riot Games" / "Riot Client"
        self._last_status: dict = {}
        self._logged_identity = False
        from .riotui import RiotUI
        self.ui = RiotUI()          # fills in the Riot sign-in window when the background login service is gone
        log(f"Riot Client: {self.exe}")

    # ---------- processes ----------
    def _names(self):
        out = []
        for p in self.psutil.process_iter(["name"]):
            out.append(((p.info.get("name") or "").lower(), p))
        return out

    def game_running(self) -> bool:
        return any(n in GAME_PROCESSES for n, _ in self._names())

    def running_games(self) -> list:
        """Friendly names of the Riot games that are open right now, e.g. ['VALORANT']."""
        titles = []
        for name, _ in self._names():
            title = GAME_TITLES.get(name)
            if title and title not in titles:
                titles.append(title)
        return titles

    def close_game(self) -> None:
        """Close any open Riot game, like Task Manager's End task. Never touches Vanguard.

        Asks nicely first (a normal close request), then ends whatever is left.
        """
        targets = [(n, p) for n, p in self._names() if n in GAME_PROCESSES]
        if not targets:
            return
        log(f"closing game ({len(targets)} processes)")
        for name in sorted({n for n, _ in targets}):
            try:
                subprocess.run(["taskkill", "/IM", name], capture_output=True, timeout=10,
                               creationflags=NO_WINDOW)
            except (OSError, subprocess.SubprocessError):
                pass
        procs = [p for _, p in targets]
        _, alive = self.psutil.wait_procs(procs, timeout=8)
        for p in alive:
            try:
                p.terminate()
            except self.psutil.NoSuchProcess:
                pass
            except self.psutil.AccessDenied:
                raise UserError("Windows wouldn't let this app close the game (it may be running as "
                                "administrator). Close it yourself, then try again.") from None
        _, alive = self.psutil.wait_procs(alive, timeout=5)
        for p in alive:
            try:
                p.kill()
            except (self.psutil.NoSuchProcess, self.psutil.AccessDenied):
                pass
        deadline = time.monotonic() + 10
        while self.game_running() and time.monotonic() < deadline:
            time.sleep(0.3)
        if self.game_running():
            raise UserError("The game didn't close. Close it yourself, then try again.")
        time.sleep(1.0)  # let Windows release the game's files

    def valorant_running(self) -> bool:
        return any(n in VALORANT_PROCESSES for n, _ in self._names())

    def client_running(self) -> bool:
        return any(n in CLIENT_PROCESSES for n, _ in self._names())

    def _client_procs(self):
        procs = []
        for name, p in self._names():
            if name not in CLIENT_PROCESSES:
                continue
            try:
                exe = Path(p.exe()).resolve()
            except self.psutil.NoSuchProcess:
                continue
            except self.psutil.AccessDenied:
                raise UserError("Riot Client is running as administrator, so this app can't close it. "
                                "Close Riot from the system tray, then try again. Run Riot normally (not as admin).") from None
            if self.install not in exe.parents:
                # Riot's UX may live in a sibling folder on some installs; still a Riot process name,
                # but we only touch processes from the selected install.
                if "riot games" not in str(exe).lower():
                    raise UserError(f"A process named {name} is running from an unexpected folder:\n{exe}\n"
                                    "Close it yourself, then try again.")
            procs.append(p)
        return procs

    def close(self) -> None:
        """Close the Riot Client (and Deceive, if it was used) so login files are flushed and unlocked."""
        self._close_client()
        self.close_deceive()

    def close_deceive(self) -> None:
        for name, p in self._names():
            if name == "deceive.exe":
                log("closing Deceive")
                try:
                    p.terminate()
                except (self.psutil.NoSuchProcess, self.psutil.AccessDenied):
                    pass

    def _close_client(self) -> None:
        """Close the Riot Client so its login files are flushed and unlocked. Never signs out."""
        if self.game_running():
            raise UserError("Close VALORANT (or any Riot game) first. Your game was left running.")
        procs = self._client_procs()
        if not procs:
            return
        log(f"closing Riot Client ({len(procs)} processes)")
        # Polite exit first. NEVER call logout endpoints: signing out revokes the saved login.
        try:
            self.request("POST", "/process-control/v1/process/quit")
        except (OSError, ValueError, UserError, http.client.HTTPException):
            pass
        _, alive = self.psutil.wait_procs(procs, timeout=8)
        for p in alive:
            try:
                p.terminate()
            except self.psutil.NoSuchProcess:
                pass
            except self.psutil.AccessDenied:
                raise UserError("Windows wouldn't let this app close Riot Client. Close it from the "
                                "system tray and try again.") from None
        _, alive = self.psutil.wait_procs(alive, timeout=5)
        for p in alive:
            try:
                p.kill()
            except (self.psutil.NoSuchProcess, self.psutil.AccessDenied):
                pass
        deadline = time.monotonic() + 5
        while self.client_running() and time.monotonic() < deadline:
            time.sleep(0.3)
        if self.client_running():
            raise UserError("Riot Client is still running, so nothing was switched. Close it and try again.")
        if self.game_running():
            raise UserError("A Riot game started while switching. Close it and try again.")
        time.sleep(0.5)  # let Windows release file handles

    def open(self, deceive: str = "") -> None:
        """Start Riot the same way the official VALORANT shortcut does: it signs in, then starts the game.

        With `deceive` (path to the user's own Deceive.exe) Deceive starts Riot for us and makes the chat
        status read "offline" to friends. Deceive is a separate program; nothing of it is bundled here.
        """
        self._logged_identity = False
        if deceive:
            exe = valid_deceive(deceive)
            log("opening VALORANT through Deceive (appear offline)")
            subprocess.Popen([str(exe), "valorant"], cwd=str(exe.parent), creationflags=NO_WINDOW)
            return
        log("opening Riot Client with --launch-product=valorant")
        subprocess.Popen([str(self.exe), "--launch-product=valorant", "--launch-patchline=live"],
                         cwd=str(self.install), creationflags=NO_WINDOW)

    # ---------- local API ----------
    def _endpoint(self):
        lockfile = self.data / "Config" / "lockfile"
        try:
            if lockfile.stat().st_size > 4096:
                raise ValueError
            _name, pid, port, password, protocol = lockfile.read_text().strip().split(":")
            pid, port = int(pid), int(port)
            if protocol != "https" or not 0 < port < 65536 or not password:
                raise ValueError
            proc = self.psutil.Process(pid)
            exe = Path(proc.exe()).resolve()
            # Only hand the lockfile secret to the real Riot service from this install.
            if proc.name().lower() != "riotclientservices.exe":
                raise ValueError
            if exe.parent != self.install:
                # Some PCs have more than one Riot Client install. Use the one that's actually running.
                log(f"note: running Riot Client is in {exe.parent}, settings say {self.install}")
            return port, password
        except FileNotFoundError:
            raise UserError("Riot Client's local connection isn't ready yet.") from None
        except (OSError, ValueError, self.psutil.Error) as e:
            if self._last_status.get("lockfile") != type(e).__name__:
                self._last_status["lockfile"] = type(e).__name__
                log(f"lockfile not usable yet: {type(e).__name__}")
            raise UserError("Riot Client's local connection isn't ready yet.") from None

    def request_raw(self, method: str, path: str, body=None):
        """(status, raw bytes). The body is never logged: it may contain a password."""
        port, password = self._endpoint()
        # Riot's local API uses a self-signed certificate on 127.0.0.1. Verification is
        # disabled only for this loopback socket; no system certificate settings change.
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        conn = http.client.HTTPSConnection("127.0.0.1", port, timeout=5, context=ctx)
        try:
            auth = base64.b64encode(f"riot:{password}".encode()).decode()
            data = json.dumps(body).encode() if body is not None else (b"" if method in ("POST", "PUT") else None)
            conn.request(method, path, body=data, headers={"Authorization": "Basic " + auth,
                                                           "Content-Type": "application/json"})
            resp = conn.getresponse()
            raw = resp.read(4 * 1024 * 1024 + 1)
            self._log_status(method, path, resp.status)
            return resp.status, raw[: 4 * 1024 * 1024]
        finally:
            conn.close()

    def request(self, method: str, path: str, body=None):
        status, raw = self.request_raw(method, path, body)
        if not 200 <= status < 300:
            return None
        return json.loads(raw) if raw.strip() else True

    def _log_status(self, method, path, status):
        key = (method, path)
        if self._last_status.get(key) != status:  # log changes only, keeps the log short
            self._last_status[key] = status
            log(f"local API {method} {path} -> {status}")

    def _get(self, path):
        try:
            return self.request("GET", path)
        except (OSError, ValueError, http.client.HTTPException, UserError):
            return None

    def whoami(self):
        """(account_id, riot_id) of the signed-in account, or (None, '') if not signed in yet.

        Riot has changed these endpoints over the years, so several are tried, newest first.
        """
        auth = self._get("/rso-auth/v1/authorization")
        session = None if isinstance(auth, dict) and auth.get("accessToken") else self._get("/rso-auth/v1/session")
        if not is_authorized(auth, session):
            return None, ""
        auth = auth if isinstance(auth, dict) else {}
        sub = None
        for key in ("idToken", "accessToken"):
            tok = auth.get(key)
            sub = sub or jwt_sub(tok.get("token") if isinstance(tok, dict) else tok)
        info_sub, name = parse_userinfo(self._get("/rso-auth/v1/authorization/userinfo"))
        sub = sub or info_sub
        if not name:
            alias = self._get("/player-account/aliases/v1/active")
            if isinstance(alias, dict):
                name = riot_name(alias.get("game_name"), alias.get("tag_line"))
        if not sub:
            from .vault import SessionFiles
            sub = SessionFiles(self.data).offline_identity()
        if not sub and auth.get("currentAccountId"):
            sub = f"acct-{auth['currentAccountId']}"
        if not sub:
            log("signed in, but no account id could be read from any endpoint")
            return None, ""
        if not self._logged_identity:
            self._logged_identity = True
            log("signed-in account detected")
        return sub, name

    @staticmethod
    def _mfa_details(data):
        """Pull the 2FA method and masked destination out of Riot's response."""
        mf = data.get("multifactor") if isinstance(data, dict) else None
        if not isinstance(mf, dict):
            return {"method": "", "email": "", "length": 6}
        method = str(mf.get("method") or (mf.get("methods") or [""])[0] or "").lower()
        return {"method": method, "email": str(mf.get("email") or ""),
                "length": mf.get("multiFactorCodeLength") or 6}

    def sign_in(self, username: str, password: str) -> dict:
        """Sign in through Riot Client's own login service (the one its login screen uses).

        Returns {"status": ...} where status is one of
        'submitted', 'mfa', 'captcha', 'invalid', 'notready', 'unavailable'.
        For 'mfa' the dict also carries 'method' ('email'/'authenticator'/'sms'/'push'/''),
        'email' (masked destination, if any) and 'length' (expected code length).
        """
        try:
            self._endpoint()
        except UserError as e:
            log(f"automatic sign-in: client's local service not found ({e})")
            return {"status": "notready", "detail": "Riot Client's login service isn't up yet"}
        try:
            auth_status, auth_raw = self.request_raw(
                "POST", "/rso-auth/v2/authorizations", {"clientId": "riot-client", "trustLevels": ["always_trusted"]})
            log(f"automatic sign-in step 1 (open authorization): HTTP {auth_status} {_reason(auth_raw)}")
        except (OSError, ValueError, http.client.HTTPException, UserError) as e:
            log(f"automatic sign-in step 1 failed: {type(e).__name__}: {e}")
        try:
            status, raw = self.request_raw("PUT", "/rso-auth/v1/session/credentials",
                                           {"username": username, "password": password, "persistLogin": True})
        except (OSError, ValueError, http.client.HTTPException, UserError) as e:
            log(f"automatic sign-in step 2 failed: {type(e).__name__}: {e}")
            return {"status": "notready", "detail": f"couldn't reach Riot's login service ({type(e).__name__})"}
        text = raw.decode("utf-8", "replace").lower()
        try:
            data = json.loads(raw)
        except ValueError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        kind = str(data.get("type") or "").lower()
        if "captcha" in text:
            result = {"status": "captcha"}
        elif "auth_failure" in text or "invalid_credentials" in text or "credentials are incorrect" in text:
            result = {"status": "invalid"}
        elif kind == "multifactor" or "multifactor" in text:
            result = dict(self._mfa_details(data), status="mfa")
        elif status in (404, 405, 501):
            result = {"status": "unavailable"}
        elif 200 <= status < 300:
            result = {"status": "submitted"}
        else:
            result = {"status": "unavailable"}
        result["detail"] = f"HTTP {status} {_reason(raw)}".strip()
        result["http"] = status
        log(f"automatic sign-in result: {result['status']} ({result['detail']})")
        return result

    def submit_mfa(self, code: str) -> str:
        """Send a 2FA code to Riot. Returns 'ok', 'bad' (wrong code) or 'error' (unknown)."""
        code = "".join(ch for ch in str(code) if ch.isalnum())
        try:
            status, raw = self.request_raw("PUT", "/rso-auth/v1/session/multifactor",
                                           {"code": code, "rememberDevice": True})
        except (OSError, ValueError, http.client.HTTPException, UserError):
            return "error"
        text = raw.decode("utf-8", "replace").lower()
        if "multifactor_attempt_failed" in text or "invalid" in text or "auth_failure" in text:
            result = "bad"
        elif 200 <= status < 300:
            result = "ok"
        else:
            result = "error"
        log(f"2FA code result: {result} (HTTP {status})")
        return result

    def nudge_login(self):
        """Ask the client to sign in with its remembered login (what it does on its own at startup)."""
        try:
            self.request("POST", "/rso-auth/v2/authorizations",
                         {"clientId": "riot-client", "trustLevels": ["always_trusted"]})
        except (OSError, ValueError, http.client.HTTPException, UserError):
            pass

    def launch_valorant(self) -> None:
        """Ask the running client to start VALORANT. Falls back to Riot's own shortcut command."""
        try:
            if self.request("POST", LAUNCH_PATH):
                return
        except (OSError, ValueError, http.client.HTTPException, UserError):
            pass
        # Same command as the official desktop shortcut; forwarded to the running client.
        subprocess.Popen([str(self.exe), "--launch-product=valorant", "--launch-patchline=live"],
                         cwd=str(self.install), creationflags=NO_WINDOW)
