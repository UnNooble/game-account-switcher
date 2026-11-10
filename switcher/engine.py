"""The account switch, step by step.

Normal switch (account already saved):  one Riot restart.
  1. Refuse if a Riot game is running.
  2. Note who is signed in now, close Riot, re-save that account's latest tokens.
  3. Put the chosen account's saved login files in place (journaled).
  4. Start Riot like the official VALORANT shortcut does (--launch-product=valorant).
  5. Confirm via Riot's local API that it signed into the expected account; make sure VALORANT starts.

Adding an account (or a saved login expired): Riot opens on its login screen. You sign in there
with "Stay signed in" ticked. We wait until Riot has actually written its token to disk (it does
this a few seconds after login), save it encrypted, and let VALORANT start. No extra restart.
"""
from __future__ import annotations

import time

from .errors import Cancelled, UserError
from .log import log
from .riotui import classify, mfa_details

LOGIN_WAIT = 15 * 60       # time allowed for you to type a password / 2FA
AUTO_LOGIN_GRACE = 30      # a saved login normally signs in well within this
NUDGE_AFTER = 4            # if a saved login hasn't signed in yet, ask Riot to use it
TOKEN_WAIT = 30            # Riot writes the remembered token a few seconds after sign-in
LAUNCH_WAIT = 5 * 60       # updates and Vanguard can make launch slow
RESEND_LAUNCH_EVERY = 20
FIRST_RESEND = 6           # if Riot hasn't started the game by itself this soon after sign-in, ask it to
UI_CHECK_EVERY = 4         # how often we look at what the Riot window is showing
AUTO_SIGNIN_GIVE_UP = 40   # if Riot's login service never answers, fall back to the Riot window


class Engine:
    def __init__(self, riot, vault, store, notify, cancel, clock=time.monotonic, sleep=time.sleep, creds=None,
                 ask=None):
        from .credentials import NoCredentials
        self.riot, self.vault, self.store = riot, vault, store
        self.creds = creds if creds is not None else NoCredentials()
        self.notify, self.cancel = notify, cancel
        self.clock, self.sleep = clock, sleep
        self.ask = ask if ask is not None else (lambda kind, data: None)

    # ---------- helpers ----------
    def step(self, n, text):
        log(f"step {n}: {text}")
        self.notify("status", {"step": n, "message": text})

    def check(self):
        if self.cancel.is_set():
            raise Cancelled()

    def profile_ids(self):
        return [p["id"] for p in self.store.read()["profiles"]]

    def save_outgoing(self, outgoing):
        """Re-save the account we're leaving: Riot may have refreshed its tokens while you played."""
        if outgoing:
            pid = self.vault.find(outgoing, self.profile_ids())
        else:
            # Riot wasn't running. Only re-save if the files on disk provably belong
            # to the last account we switched to.
            pid = self.store.read()["active"]
            offline = self.vault.files.offline_identity()
            if not pid or not offline or self.vault.identity(pid) != offline:
                return
            outgoing = offline
        if pid:
            try:
                self.vault.capture(pid, outgoing)  # refuses to overwrite a good save with a token-less file
            except UserError:
                log("outgoing login had no token; kept the previous save")

    def wait_for_login(self, expected, label, fresh, login=None):
        """Wait until Riot reports a signed-in account. Returns (id, riot_id, needed_new_login).

        login = (username, password) lets the app sign in by itself when there's no valid saved login.
        """
        start = self.clock()
        warned, nudged = fresh, fresh
        tried, auto_since = False, None
        watch = None            # set once we're operating the Riot sign-in window
        if fresh and not login:
            self.step(1, f"Sign in to {label} in the Riot window and tick 'Stay signed in'. "
                         "Do any 2FA / email code there too. Waiting…")
        elif fresh:
            self.step(1, f"Signing in to {label}…")
        while self.clock() - start < LOGIN_WAIT:
            self.check()
            account, riot_id = self.riot.whoami()
            if account:
                if expected and account != expected:
                    raise UserError(f"Riot signed into a different account ({riot_id or 'unknown'}), not {label}. "
                                    "Close VALORANT if it opened. If the saved username is wrong, fix it with ⋯ → Edit login.")
                return account, riot_id, fresh or tried or self.clock() - start > AUTO_LOGIN_GRACE
            elapsed = self.clock() - start
            if not nudged and elapsed > NUDGE_AFTER:
                nudged = True
                self.riot.nudge_login()
            # Automatic sign-in: right away for a new login, or once a saved login has clearly expired.
            if login and not tried and (fresh or elapsed > NUDGE_AFTER + 4):
                auto_since = auto_since if auto_since is not None else self.clock()
                result = self.riot.sign_in(*login)
                status = result["status"]
                gone = status == "unavailable" and result.get("http") in (404, 405, 501)
                if status in ("notready", "unavailable") and not gone and self.clock() - auto_since < AUTO_SIGNIN_GIVE_UP:
                    self.sleep(1)
                    continue
                tried, warned = True, True
                if status == "invalid":
                    raise UserError(f"Riot says the username or password for {label} is wrong. "
                                    "Fix it with ⋯ → Edit login, then try again.")
                if status == "mfa":
                    self.handle_mfa(result, label)
                elif status == "captcha":
                    self.step(1, "Riot wants a captcha this time (it does that occasionally). Finish signing in "
                                 "in the Riot window; next time it's automatic again.")
                elif status == "submitted":
                    self.step(1, f"Signing in to {label}…")
                else:
                    why = result.get("detail") or "no reason given"
                    log(f"background sign-in unavailable: {status} ({why}); using the Riot window instead")
                    if self.fill_riot_window(login, label):
                        watch = {"since": self.clock(), "last": 0.0, "bad": 0, "state": None, "quiet": 0.0,
                                 "tries": 0, "nagged": False}
                    else:
                        self.step(1, f"Couldn't fill in the Riot window for you. Sign in to {label} there "
                                     "and tick 'Stay signed in'.")
            if watch is not None and self.clock() - watch["last"] >= UI_CHECK_EVERY:
                watch["last"] = self.clock()
                if self.watch_riot_window(label, watch) == "off":
                    watch = None
            if not warned and elapsed > AUTO_LOGIN_GRACE:
                warned = True
                self.step(1, f"Riot is asking for a login, so {label}'s saved login has expired. Sign in there "
                             "with 'Stay signed in' ticked (or save the password with ⋯ → Edit login to make "
                             "this automatic).")
            self.sleep(1)
        raise UserError("Timed out waiting for the Riot login. Nothing was saved. Try again when ready.")

    def fill_riot_window(self, login, label):
        """Type the login into Riot's own sign-in window (UI Automation, no simulated input). True if submitted."""
        ui = getattr(self.riot, "ui", None)
        if ui is None:
            return False
        self.step(1, f"Filling in the Riot sign-in for {label}…")
        reply = ui.fill_login(login[0], login[1], stay=True)
        self.check()
        if not reply.get("ok"):
            log(f"could not fill the Riot window: {reply.get('error', 'unknown')}")
            return False
        if not reply.get("stay", True):
            log("could not tick 'Stay signed in' in the Riot window; the login may not be remembered")
            self.notify("warning", "Riot's 'Stay signed in' box couldn't be ticked automatically, so this login "
                                   "may not be remembered. The saved password will sign in again when needed.")
        self.step(1, f"Signing in to {label}…")
        return True

    def watch_riot_window(self, label, watch):
        """After the form is submitted: notice what Riot shows next (2FA, wrong password, captcha) and handle it."""
        if self.clock() < watch["quiet"]:
            return "wait"
        inventory = self.riot.ui.inventory()
        state = classify(inventory)
        if state != watch["state"]:
            log(f"Riot window shows: {state}" + (f" ({mfa_details(inventory)['method']})" if state.startswith('mfa') else ""))
        previous, watch["state"] = watch["state"], state
        if state.startswith("mfa") and state != previous:
            log(f"Riot verification page text: {(inventory.get('texts') or [])[:14]}")
        if state == "invalid":
            watch["bad"] += 1
            if watch["bad"] >= 2 and self.clock() - watch["since"] > 6:
                raise UserError(f"Riot says the username or password for {label} is wrong. "
                                "Fix it with the card's ··· → Username & password, then try again.")
            return "wait"
        watch["bad"] = 0
        if state == "captcha":
            if previous != "captcha":
                self.step(1, "Riot wants a captcha ('I'm not a robot'). Finish it in the Riot window; the rest "
                             "is automatic.")
            return "wait"
        if state in ("mfa_code", "mfa_mobile"):
            if state == "mfa_mobile" and previous == "mfa_mobile":
                return "wait"          # already asked about this page; keep waiting for the approval
            return self.ask_riot_code(label, state, watch, mfa_details(inventory))
        if state == "login" and not watch["nagged"] and self.clock() - watch["since"] > 25:
            watch["nagged"] = True
            self.step(1, "Riot is still on its sign-in page. If a captcha ('I'm not a robot') showed up, finish "
                         "it in the Riot window.")
        return "wait"

    def ask_riot_code(self, label, state, watch, details=None):
        """Riot's window wants a 2FA code (or a Riot Mobile approval). Ask here, type it there."""
        watch["tries"] += 1
        if watch["tries"] > 8:
            self.step(1, "Too many tries. Finish the verification in the Riot window. Waiting…")
            return "off"
        details = details or {"method": "unknown", "destination": ""}
        method, where = details["method"], details["destination"]
        mobile = state == "mfa_mobile"
        if method == "email":
            source = f"Riot emailed a code to {where}" if where else "Riot emailed you a code"
            message = f"{source}. Open that inbox, then enter the code here to finish signing in to {label}:"
            self.step(1, f"Waiting for the code Riot emailed to {where or 'you'}…")
        elif method == "sms":
            message = (f"Riot texted a code to {where}. " if where else "Riot texted you a code. ") + \
                      f"Enter it here to finish signing in to {label}:"
            self.step(1, "Waiting for the code Riot texted you…")
        elif method == "authenticator":
            message = f"Open your authenticator app and enter its 6-digit code for Riot to finish signing in to {label}:"
            self.step(1, "Waiting for the code from your authenticator app…")
        elif method == "mobile" or mobile:
            message = ("Approve the sign-in in your Riot Mobile app, or type the code it shows. You can also have "
                       f"Riot email you a code instead. Signing in to {label}:")
            self.step(1, "Waiting for your approval in Riot Mobile (or a code)…")
        else:
            message = f"Riot asked for a verification code. Enter it to finish signing in to {label}:"
            self.step(1, "Waiting for your verification code…")
        code = self.ask("mfa_code", {"label": label, "mobile": mobile or method == "mobile", "method": method,
                                     "destination": where, "message": message})
        self.check()
        if code is None:
            self.step(1, "Finish the verification in the Riot window. Waiting…")
            return "off"
        if code == "":                               # "I approved it"
            self.step(1, "Checking…")
            watch["quiet"] = self.clock() + 8
            return "wait"
        if code == "__email__":                      # "Email me a code instead"
            self.step(1, "Asking Riot to email you a code…")
            self.riot.ui.click(r"(?i)e-?mail|another|different|other|try")
            watch["quiet"] = self.clock() + 4
            watch["state"] = None
            return "wait"
        reply = self.riot.ui.fill_code(code)
        if not reply.get("ok"):
            self.step(1, "Couldn't type the code into the Riot window. Enter it there. Waiting…")
            return "off"
        self.step(1, "Verifying the code…")
        watch["quiet"] = self.clock() + 6
        watch["state"] = None
        return "wait"

    def handle_mfa(self, info, label):
        """Collect the 2FA code in the app and send it to Riot. whoami() is the real success check."""
        method = (info.get("method") or "").lower()
        where = {"email": f"an email code{(' to ' + info['email']) if info.get('email') else ''}",
                 "sms": "a text message code", "authenticator": "a code from your authenticator app",
                 "totp": "a code from your authenticator app"}.get(method)
        if method in ("push", "riot_mobile", "mobile"):
            # Riot Mobile approval: nothing to type. Keep polling whoami in the outer loop.
            self.step(1, "Approve the login in your Riot Mobile app. Waiting…")
            return
        for attempt in range(6):
            self.check()
            if self.riot.whoami()[0]:   # finished in the Riot window, or already done
                return
            prompt = where or ("the verification code Riot just sent you (email, text, or your "
                               "authenticator app)")
            code = self.ask("mfa_code", {"label": label, "method": method, "email": info.get("email", ""),
                                         "length": info.get("length", 6),
                                         "message": f"Riot sent {prompt}. Enter it to finish signing in to {label}:"
                                         if attempt == 0 else "That code didn't work. Try again:"})
            self.check()
            if code is None:
                # User closed the box: let them finish in the Riot window instead.
                self.step(1, "Enter the code in the Riot window to finish signing in. Waiting…")
                return
            if code == "":
                # "I approved it" (Riot Mobile): re-check whether sign-in completed.
                self.step(1, "Checking…")
                self.sleep(1)
                continue
            outcome = self.riot.submit_mfa(code)
            if outcome == "ok" or self.riot.whoami()[0]:
                return
            if outcome == "error":
                # Our 2FA call may not match this Riot version. Fall back to the Riot window.
                self.step(1, "Couldn't send the code automatically. Type it into the Riot window instead. Waiting…")
                return
            self.sleep(1)  # 'bad' code: loop and ask again
        self.step(1, "Too many wrong codes. Type the code into the Riot window to finish. Waiting…")

    def wait_for_token(self) -> bool:
        start = self.clock()
        while self.clock() - start < TOKEN_WAIT:
            self.check()
            if self.vault.files.has_remembered_login():
                self.sleep(2)  # let Riot finish writing the rest (Sessions folder)
                return True
            self.sleep(1)
        return False

    def save_new_login(self, profile_id, label, account, riot_id):
        self.step(2, "Signed in. Saving the login…")
        has_token = self.wait_for_token()
        pid = profile_id or self.store.add(label, riot_id)
        try:
            for attempt in range(3):  # Riot is running; its files can be busy for a moment
                try:
                    self.vault.capture(pid, account, require_token=False)
                    break
                except OSError:
                    if attempt == 2:
                        raise
                    self.sleep(1)
        except (UserError, OSError):
            if not profile_id:
                self.store.remove(pid)
            raise UserError("Couldn't save the login files (Windows or antivirus blocked them). "
                            "Try again; if it keeps happening, check Controlled Folder Access.") from None
        if not has_token:
            self.notify("warning", "Riot didn't save a remembered login for this account — 'Stay signed in' was "
                                   "probably not ticked. You can play now, but next time use ⋯ → Sign in again.")
        return pid

    def deceive_for(self, profile_id) -> str:
        """Path to Deceive when the Appear offline switch is on (saved accounts only), else ''."""
        if not profile_id:
            return ""
        settings = self.store.read()["settings"]
        if not settings.get("appear_offline"):
            return ""
        from .riot import discover_deceive
        path = settings.get("deceive_path", "") or discover_deceive()
        if not path:
            raise UserError("Appear offline is on, but Deceive wasn't found. "
                            "Use ··· → Appear offline setup to download it, or switch Appear offline off.")
        return path

    def start_tracker(self) -> None:
        """Stats overlay switch: start the user's Overwolf. A problem here never stops the game."""
        settings = self.store.read()["settings"]
        if not settings.get("stats_overlay"):
            return
        try:
            from .riot import discover_tracker
            path = settings.get("tracker_path", "") or discover_tracker()
            if not path:
                raise UserError("The stats overlay is on, but Overwolf wasn't found. "
                                "Use ··· → Stats overlay setup to install it.")
            self.riot.start_tracker(path)
        except UserError as exc:
            self.notify("warning", str(exc))
        except Exception as exc:
            log(f"couldn't start the stats overlay: {exc}")

    def launch(self, account, label, kicked=False):
        self.step(3, "Starting VALORANT… If Riot shows an update or asks to restart for Vanguard, follow its prompt.")
        start = self.clock()
        last_sent = start - RESEND_LAUNCH_EVERY + (FIRST_RESEND if not kicked else RESEND_LAUNCH_EVERY)
        while self.clock() - start < LAUNCH_WAIT:
            self.check()
            if self.riot.valorant_running():
                self.step(4, f"VALORANT is running on {label}. Have fun!")
                return
            current, _ = self.riot.whoami()
            if current and current != account:
                raise UserError("The Riot account changed during launch. Launch was stopped.")
            if current and self.clock() - last_sent >= RESEND_LAUNCH_EVERY:
                self.riot.launch_valorant()
                last_sent = self.clock()
            self.sleep(1)
        raise UserError(f"Signed in to {label}, but VALORANT didn't start within 5 minutes. "
                        "Riot may be updating or need a Vanguard restart — check the Riot window and press Play.")

    def already_playing(self, profile_id) -> bool:
        """True when the game is open on exactly the account the user clicked: nothing to switch."""
        saved = self.vault.identity(profile_id) if profile_id else None
        if not saved or not self.riot.client_running():
            return False
        return self.riot.whoami()[0] == saved

    def confirm_close_game(self, label, switching=True):
        """Ask (inside the app) before closing a running game. Declining leaves everything as it was."""
        games = self.riot.running_games() or ["a Riot game"]
        many = len(games) > 1
        names = " and ".join(games)
        short = "the Game" if many else games[0]
        answer = self.ask("confirm", {
            "title": f"{'Switch to' if switching else 'Add'} {label}?",
            "message": f"{names} {'are' if many else 'is'} open. Close "
                       f"{'them' if many else 'it'} and {'switch to' if switching else 'continue with'} {label}?",
            "detail": "If you're in a match, closing the game counts as leaving it.",
            "yes": f"Close {short} & {'Switch' if switching else 'Continue'}",
            "no": "Cancel",
        })
        self.check()
        if answer is False:
            raise Cancelled("Cancelled. Your game was left running.")
        if answer is not True:  # nobody to ask (no window)
            raise UserError("Close VALORANT (or any Riot game) before switching. Your game was left running.")
        self.step(0, f"Closing {names}…")
        self.riot.close_game()
        self.check()

    def save_current(self, label):
        """Save whichever account Riot is signed into right now, without signing in again."""
        log(f"=== save signed-in account as: {label}")
        self.step(0, "Checking which account Riot is signed into…")
        account, riot_id = self.riot.whoami() if self.riot.client_running() else (None, "")
        if not account:
            raise UserError("Riot isn't signed in right now. Open Riot and sign in with 'Stay signed in' ticked, "
                            "then try again. Or add the account with its username and password instead.")
        other = self.vault.find(account, self.profile_ids())
        if other:
            raise UserError(f"That account ({riot_id or 'signed in now'}) is already saved as "
                            f"'{self.store.get(other)['label']}'.")
        self.step(2, "Saving the login…")
        if not self.wait_for_token():
            raise UserError("Riot is signed in, but 'Stay signed in' wasn't ticked, so there's no login to save. "
                            "Add this account with its username and password instead (the app ticks it for you).")
        pid = self.store.add(label, riot_id)
        try:
            for attempt in range(3):
                try:
                    self.vault.capture(pid, account)
                    break
                except OSError:
                    if attempt == 2:
                        raise
                    self.sleep(1)
        except (UserError, OSError):
            self.store.remove(pid)
            raise UserError("Couldn't save the login files. Close Riot and add the account with its username "
                            "and password instead.") from None
        self.store.set_active(pid)
        self.step(4, f"Saved {label}{' (' + riot_id + ')' if riot_id else ''}. Click PLAY any time.")
        return pid

    # ---------- entry point ----------
    def run(self, profile_id=None, new_label=None, relogin=False, new_login=None):
        """Switch to profile_id, or add a new account called new_label. Returns the profile id.

        new_login = (username, password) to sign a new account in automatically and remember it.
        """
        self.check()
        if profile_id:
            profile = self.store.get(profile_id)
            if not profile:
                raise UserError("That account no longer exists.")
            label = profile["label"]
        else:
            label = new_label
        log(f"=== {'add' if not profile_id else ('sign in again' if relogin else 'switch')}: {label}")

        self.step(0, "Checking Riot Client…")
        if self.riot.game_running():
            if self.already_playing(profile_id):
                self.store.set_active(profile_id)
                self.step(4, f"{label} is already signed in and VALORANT is open.")
                return profile_id
            self.confirm_close_game(label, switching=bool(profile_id))

        if self.vault.needs_recovery():
            # A previous switch was interrupted mid-copy. Current files may be half-written.
            self.riot.close()
            self.vault.recover()
        else:
            outgoing = self.riot.whoami()[0] if self.riot.client_running() else None
            self.riot.close()
            self.save_outgoing(outgoing)
        self.check()

        saved = self.vault.load(profile_id) if profile_id else None
        expected = saved.get("identity") if saved else None
        fresh = relogin or saved is None

        self.step(1, f"Switching to {label}…")
        self.vault.restore(self.vault.blank() if fresh else saved["files"])
        log(f"restored files: {self.vault.files.describe()}")
        self.check()
        self.start_tracker()
        self.riot.open(self.deceive_for(profile_id))

        login = new_login or (self.creds.load(profile_id) if profile_id else None)
        account, riot_id, manual = self.wait_for_login(expected, label, fresh, login)
        self.check()

        if not profile_id:
            other = self.vault.find(account, self.profile_ids())
            if other:
                # Added before: don't make a second copy. Refresh the existing one and play it.
                profile_id, label = other, self.store.get(other)["label"]
                manual = True
                log("account already saved; refreshing the existing entry")
        kicked = False
        if manual and not self.riot.valorant_running():
            # Riot read its start-up command before this sign-in, so it may not start the game on its own.
            # Ask it right now; saving the login below happens while the game is already starting.
            self.step(2, "Signed in. Starting VALORANT and saving your login…")
            self.riot.launch_valorant()
            kicked = True
        if manual:
            profile_id = self.save_new_login(profile_id, label, account, riot_id)
        if new_login:
            try:
                self.creds.save(profile_id, *new_login)
            except UserError:
                self.notify("warning", "Signed in, but Windows Credential Manager couldn't store the password. "
                                       "Switching still works with the saved login.")

        if riot_id:
            self.store.update(profile_id, riot_id=riot_id)
        self.store.set_active(profile_id)
        self.step(2, f"Signed in as {riot_id or label}.")
        self.launch(account, label, kicked)
        return profile_id
