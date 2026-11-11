"""The window: a calm list of accounts, one big action, and a status dock that appears while working.

Design rules (borrowed from Apple's human-interface ideas): one clear focus per screen, generous space,
soft rounded shapes, one accent color used sparingly, secondary actions tucked behind a single menu,
and questions asked in small sheets right where you are instead of system pop-ups.
"""
from __future__ import annotations

from pathlib import Path
import queue
import time
import tkinter as tk
from tkinter import filedialog

from . import APP_NAME, VERSION, resource, updates, worker
from . import theme as T
from .errors import UserError
from .widgets import Avatar, Card, Pill, Progress, PopupMenu, Sheet, style_titlebar

STEPS = 5   # Check Riot, Sign in, Verify account, Start VALORANT, Playing


class App(tk.Tk):
    def __init__(self, store, creds, autoplay=None):
        super().__init__()
        T.init(self)
        self.store, self.creds = store, creds
        try:
            self.iconbitmap(default=str(resource("assets", "icon.ico")))
        except tk.TclError:
            pass
        self.events = queue.Queue()
        self.replies = queue.Queue()
        self.update_events = queue.Queue()
        self.update_settings = updates.Settings(store.root)
        self.update_url = ""
        self.update_manual = False
        self.thread = self.cancel = None
        self.prompt_open = False
        self.closing = False
        self.dock_visible = False
        self.title(APP_NAME)
        self.configure(bg=T.BG)
        self._place_window()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.report_callback_exception = lambda *a: self.error(
            str(a[1]) if isinstance(a[1], UserError) else "That didn't work. Please try again.")
        self.open_menu_ref = None
        self.menu_closed_at = (None, 0.0)
        self.bind("<Escape>", lambda e: self.stop())
        self.bind("<Configure>", lambda e: self.close_menu() if e.widget is self else None, add="+")
        self.bind_all("<ButtonPress>", self._any_click, add="+")
        self.bind_all("<MouseWheel>", self._wheel)
        self.build()
        style_titlebar(self)
        self.refresh()
        self.after(100, self.poll)
        self.after(2500, self.auto_update_check)
        if autoplay:
            profile = self.store.get(autoplay)
            if profile:
                self.after(300, lambda: self.launch(profile))

    # ---------- window ----------
    def _place_window(self):
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w = min(T.px(780), int(sw * 0.92))
        h = min(T.px(880), int(sh * 0.90))
        self.minsize(min(T.px(720), w), min(T.px(640), h))
        self.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 3)}")

    # ---------- popup menus ----------
    def close_menu(self):
        if self.open_menu_ref is not None:
            self.open_menu_ref.dismiss()
            return True
        return False

    def _any_click(self, event):
        """A click anywhere outside an open menu closes it (borderless popups never get reliable focus)."""
        menu = self.open_menu_ref
        if menu is not None and not menu.contains(event.widget):
            menu.dismiss()

    def show_menu(self, anchor, items, width=240):
        """Open a menu under `anchor`. Clicking the same button again closes it instead of reopening."""
        last_anchor, closed_at = self.menu_closed_at
        if last_anchor is anchor and time.monotonic() - closed_at < 0.35:
            self.menu_closed_at = (None, 0.0)
            return
        self.close_menu()
        PopupMenu(self, anchor, items, width=width)

    def _wheel(self, event):
        try:
            if event.widget.winfo_toplevel() is not self:
                return
            if self.canvas.bbox("all") and self.canvas.bbox("all")[3] > self.canvas.winfo_height():
                self.canvas.yview_scroll(-int(event.delta / 120), "units")
        except (tk.TclError, AttributeError):
            pass

    # ---------- layout ----------
    def build(self):
        pad = T.px(36)
        head = tk.Frame(self, bg=T.BG)
        head.pack(fill="x", padx=pad, pady=(T.px(32), 0))
        tk.Label(head, text="Accounts", font=T.font(26, True), fg=T.FG, bg=T.BG).pack(side="left", anchor="n")
        self.more_btn = Pill(head, "···", self.main_menu, kind="plain", height=40, square=True)
        self.more_btn.pack(side="right", anchor="n")
        self.add_btn = Pill(head, "Add Account", self.add, kind="primary", height=40, padx=22)
        self.add_btn.pack(side="right", anchor="n", padx=(0, T.px(12)))

        # Second row: what to do on the left, the Appear offline switch on the right.
        sub = tk.Frame(self, bg=T.BG)
        sub.pack(fill="x", padx=pad, pady=(T.px(10), 0))
        tk.Label(sub, text="Pick an account to play.", font=T.font(10), fg=T.MUTED,
                 bg=T.BG).pack(side="left")
        self.tracker_btn = Pill(sub, "", self.toggle_tracker, kind="plain", height=34, padx=16)
        self.tracker_btn.pack(side="right")
        self.offline_btn = Pill(sub, "", self.toggle_offline, kind="plain", height=34, padx=16)
        self.offline_btn.pack(side="right", padx=(0, T.px(10)))
        self.show_offline_state()
        self.show_tracker_state()

        tk.Label(self, text=f"Unofficial  ·  not endorsed by Riot Games  ·  v{VERSION}", font=T.font(8),
                 fg=T.FAINT, bg=T.BG).pack(side="bottom", pady=(T.px(4), T.px(14)))

        self.body = tk.Frame(self, bg=T.BG)
        self.body.pack(fill="both", expand=True, padx=pad, pady=(T.px(22), T.px(10)))
        self.update_bar = Card(self, fill=T.CARD, radius=18, padx=18, pady=10)
        row = tk.Frame(self.update_bar.inner, bg=T.CARD)
        row.pack(fill="x")
        self.update_label = tk.Label(row, text="", font=T.font(10, True), fg=T.FG, bg=T.CARD, anchor="w")
        self.update_label.pack(side="left")
        Pill(row, "Dismiss", self.hide_update, kind="plain", height=30, padx=14).pack(side="right")
        Pill(row, "Download", self.open_update, kind="primary", height=30, padx=16).pack(side="right", padx=(0, 8))
        self.canvas = tk.Canvas(self.body, bg=T.BG, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.cards = tk.Frame(self.canvas, bg=T.BG)
        win = self.canvas.create_window((0, 0), window=self.cards, anchor="nw")
        self.cards.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(win, width=e.width))

        # status dock: hidden until something is happening
        self.dock = Card(self, fill=T.CARD, radius=22, padx=22, pady=18)
        top = tk.Frame(self.dock.inner, bg=T.CARD)
        top.pack(fill="x")
        self.who = tk.Label(top, text="", font=T.font(13, True), fg=T.FG, bg=T.CARD, anchor="w")
        self.who.pack(side="left")
        self.dock_btn = Pill(top, "Stop", self.stop, kind="plain", height=30, padx=16)
        self.dock_btn.pack(side="right")
        self.msg = tk.Label(self.dock.inner, text="", font=T.font(10), fg=T.MUTED, bg=T.CARD,
                            anchor="w", justify="left")
        self.msg.pack(fill="x", pady=(8, 12))
        self.bar = Progress(self.dock.inner)
        self.bar.pack(fill="x")
        self.dock.inner.bind("<Configure>", self._wrap_message, add="+")

    def _wrap_message(self, event):
        wrap = max(T.px(120), event.width - T.px(6))
        if int(self.msg.cget("wraplength")) != wrap:
            self.msg.configure(wraplength=wrap)

    # ---------- the list ----------
    def refresh(self):
        for w in self.cards.winfo_children():
            w.destroy()
        data = self.store.read()
        if not data["profiles"]:
            self.empty_state()
            return
        for p in data["profiles"]:
            self.card(p, p["id"] == data["active"])
        self.canvas.yview_moveto(0)

    def empty_state(self):
        box = Card(self.cards, radius=24, padx=30, pady=34)
        box.pack(fill="x", pady=(T.px(40), 0))
        inner = box.inner
        tk.Label(inner, text="Add your first account", font=T.font(17, True), fg=T.FG, bg=T.CARD).pack()
        tk.Label(inner, text="Enter your Riot username and password once. After that, one click\n"
                             "switches to it and starts VALORANT.",
                 font=T.font(10), fg=T.MUTED, bg=T.CARD, justify="center").pack(pady=(8, 20))
        Pill(inner, "Add Account", self.add, kind="primary", height=40, padx=26).pack()

    def card(self, p, active):
        card = Card(self.cards, radius=20, padx=18, pady=14)
        card.pack(fill="x", pady=(0, T.px(12)))
        inner = card.inner
        letter = (p["label"][:1] or "?").upper()
        avatar = Avatar(inner, letter, T.RED_TINT if active else T.AVATAR, size=46, fg=T.RED if active else T.FG)
        avatar.pack(side="left")
        text = tk.Frame(inner, bg=T.CARD)
        text.pack(side="left", fill="x", expand=True, padx=(T.px(14), T.px(8)))
        line = tk.Frame(text, bg=T.CARD)
        line.pack(anchor="w")
        tk.Label(line, text=p["label"], font=T.font(13, True), fg=T.FG, bg=T.CARD).pack(side="left")
        if active:
            tk.Label(line, text="●  Last used", font=T.font(8), fg=T.GREEN, bg=T.CARD).pack(
                side="left", padx=(T.px(10), 0))
        sub = p["riot_id"] or "Not signed in yet"
        if self.creds.has(p["id"]):
            sub += "   ·   Auto sign-in"
        tk.Label(text, text=sub, font=T.font(9), fg=T.MUTED, bg=T.CARD, anchor="w").pack(anchor="w", pady=(2, 0))
        more = Pill(inner, "···", None, kind="ghost", height=34, square=True)
        more.command = lambda b=more: self.menu(p, b)
        more.pack(side="right")
        play = Pill(inner, "Play", lambda: self.launch(p), kind="tint", height=34, padx=22)
        play.pack(side="right", padx=(T.px(8), T.px(12)))
        card.update_idletasks()
        card.track_hover()
        card.bind_click(lambda: self.launch(p), skip={more, play})
        card.configure(cursor="hand2")

    def menu(self, p, anchor):
        if self.guard_busy():
            return
        items = [("Rename", lambda: self.rename(p)),
                 ("Username & password…", lambda: self.edit_login(p)),
                 ("Sign in again", lambda: self.begin(p["id"], None, True, p["label"])),
                 ("Add desktop shortcut", lambda: self.shortcut(p))]
        if self.creds.has(p["id"]):
            items.append(("Forget saved password", lambda: (self.creds.delete(p["id"]), self.refresh())))
        items += [None,
                  ("Move up", lambda: (self.store.move(p["id"], -1), self.refresh())),
                  ("Move down", lambda: (self.store.move(p["id"], 1), self.refresh())),
                  None,
                  ("Remove account…", lambda: self.delete(p), "danger")]
        self.show_menu(anchor, items)

    def main_menu(self):
        if self.guard_busy():
            return
        self.show_menu(self.more_btn, [
            ("Check logins", self.check_status),
            None,
            ("Back up accounts…", self.backup),
            ("Restore from backup…", self.restore),
            None,
            ("Riot Client location…", self.settings),
            ("Appear offline setup…", self.deceive_setup),
            ("Stats overlay setup…", self.tracker_setup),
            ("Open log file", self.open_log),
            None,
            ("Check for updates", self.check_updates_now),
            (("Automatic update check: On" if self.update_settings.read()["auto"]
              else "Automatic update check: Off"), self.toggle_auto_update),
        ], width=270)

    # ---------- small dialogs ----------
    def busy(self):
        return self.thread is not None

    def guard_busy(self):
        if self.busy():
            self.set_message("Finish or stop the current switch first.", T.MUTED)
            return True
        return False

    def notice(self, heading, message, button="OK", on_top=False):
        sheet = Sheet(self, heading, on_top=on_top)
        sheet.heading(heading)
        sheet.text(message)
        sheet.buttons(button, secondary=None)
        sheet.show()

    def error(self, text):
        self.notice("That didn't work", text)

    def ask_yes_no(self, heading, message, yes="Yes", no="Cancel", detail=None, on_top=False):
        sheet = Sheet(self, heading, on_top=on_top)
        sheet.heading(heading)
        sheet.text(message, color=T.FG)
        if detail:
            sheet.text(detail, small=True)
        sheet.buttons(yes, secondary=no)
        return bool(sheet.show())

    def clean_name(self, raw):
        from .store import clean_label
        return clean_label(raw)

    # ---------- actions ----------
    def add(self):
        if self.guard_busy():
            return
        sheet = Sheet(self, "Add account")
        sheet.heading("Add an account")
        sheet.text("Enter the login you use for the Riot client. It's stored encrypted on this PC only. "
                   "That's all you need to do, once.")
        user = sheet.field("Riot username")
        pw = sheet.field("Password", secret=True)
        name = sheet.field("Name in this app  (optional)")
        sheet.text("The app signs in to Riot for you, keeps you signed in, and starts VALORANT. If Riot asks for a "
                   "2FA code you can type it here; a captcha, when Riot shows one, is finished in the Riot window. "
                   "Leave the username and password empty to sign in yourself in the Riot window instead.",
                   small=True)

        def validate():
            u, p = user.get().strip(), pw.get()
            if bool(u) != bool(p):
                raise UserError("Fill in both the username and the password, or leave both empty.")
            label = self.clean_name(name.get().strip() or u)
            return ("new", label, (u, p) if p else None)

        def use_current():
            try:
                label = self.clean_name(name.get().strip() or user.get().strip())
            except UserError as e:
                sheet.show_error("Type a name above first, so this account has a label.")
                return
            sheet.close(("current", label, None))

        sheet.buttons("Add & Sign In", validate, left=("Already signed in to Riot? Save that one", use_current))
        result = sheet.show()
        if not result:
            return
        kind, label, login = result
        if kind == "current":
            self.begin(None, label, False, label, save_current=True)
        else:
            self.begin(None, label, False, label, login)

    def edit_login(self, p):
        if self.guard_busy():
            return
        current = self.creds.load(p["id"])
        sheet = Sheet(self, "Login")
        sheet.heading(f"Login for {p['label']}")
        sheet.text("Saved in Windows Credential Manager, encrypted for your Windows user only. With it, the "
                   "app can sign in again by itself if Riot ever logs you out.")
        user = sheet.field("Riot username", current[0] if current else "")
        pw = sheet.field("Password", secret=True)

        def save():
            self.creds.save(p["id"], user.get().strip(), pw.get())
            return True

        sheet.buttons("Save", save)
        if not sheet.show():
            return
        self.refresh()
        if self.ask_yes_no("Sign in now?", f"Sign in to {p['label']} with this login right now?",
                           yes="Sign In", no="Not Now"):
            self.begin(p["id"], None, True, p["label"])

    def shortcut(self, p):
        try:
            from .system import create_desktop_shortcut
            name = create_desktop_shortcut(p)
        except (UserError, OSError) as e:
            return self.error(str(e) if isinstance(e, UserError) else "Windows couldn't create the desktop shortcut.")
        self.notice("Shortcut added", f"'{name}' is on your desktop. Double-click it to switch to this "
                                      "account and start VALORANT.")

    def rename(self, p):
        sheet = Sheet(self, "Rename")
        sheet.heading("Rename account")
        name = sheet.field("Name", p["label"])

        def save():
            self.store.update(p["id"], label=name.get())
            return True

        sheet.buttons("Save", save)
        if sheet.show():
            self.refresh()

    def delete(self, p):
        if self.ask_yes_no(f"Remove {p['label']}?",
                           "This removes the account and its saved login from this PC.",
                           yes="Remove", no="Keep",
                           detail="Your Riot account itself isn't affected."):
            (self.store.root / "sessions" / (p["id"] + ".bin")).unlink(missing_ok=True)
            self.creds.delete(p["id"])
            self.store.remove(p["id"])
            self.refresh()

    def settings(self):
        current = self.store.read()["settings"]["riot_path"]
        from .riot import discover_client
        found = discover_client()
        sheet = Sheet(self, "Riot Client location", width=520)
        sheet.heading("Riot Client location")
        sheet.text(f"Using: {current or found or 'Not found'}", color=T.FG)
        sheet.text("Set manually." if current else "Found automatically. You only need to change this if "
                   "Riot is installed somewhere unusual.", small=True)

        def choose():
            path = filedialog.askopenfilename(parent=sheet, title="Choose RiotClientServices.exe",
                                              filetypes=[("Riot Client", "RiotClientServices.exe")])
            if not path:
                return Sheet.STAY
            if Path(path).name.lower() != "riotclientservices.exe":
                raise UserError("Please choose RiotClientServices.exe.")
            self.store.set_riot_path(path)
            return True

        def auto():
            self.store.set_riot_path("")
            sheet.close(True)

        sheet.buttons("Choose File…", choose, secondary="Done", left=("Use Auto-Detect", auto))
        sheet.show()

    def _open_backend(self):
        """(vault, creds) for this PC. Windows only."""
        import os
        from .vault import DPAPI, SessionFiles, Vault
        from .credentials import Credentials
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            raise UserError("Backups work on Windows only.")
        riot_data = Path(base) / "Riot Games" / "Riot Client"
        return Vault(self.store.root, SessionFiles(riot_data), DPAPI()), Credentials()

    def check_status(self):
        try:
            vault, creds = self._open_backend()
        except UserError as e:
            return self.error(str(e))
        import time as _t
        profiles = self.store.read()["profiles"]
        if not profiles:
            return self.notice("Check logins", "No accounts yet.")
        rows = []
        for p in profiles:
            try:
                saved = vault.load(p["id"])
            except UserError:
                saved = None
            if not saved:
                rows.append((p["label"], "Not signed in yet", T.MUTED))
                continue
            parts = ["Login saved"]
            if saved.get("saved_at"):
                days = (int(_t.time()) - saved["saved_at"]) // 86400
                parts.append("today" if days <= 0 else f"{days}d ago")
            parts.append("auto sign-in on" if creds.has(p["id"]) else "no password saved")
            rows.append((p["label"], "  ·  ".join(parts), T.GREEN))
        sheet = Sheet(self, "Check logins", width=500)
        sheet.heading("Saved logins")
        sheet.rows(rows)
        sheet.text("Accounts with a saved password sign back in by themselves if a login expires. For the "
                   "others, click the account and sign in if Riot asks.", small=True)
        sheet.buttons("Done", secondary=None)
        sheet.show()

    def backup(self):
        try:
            vault, creds = self._open_backend()
        except UserError as e:
            return self.error(str(e))
        from . import portable
        sheet = Sheet(self, "Back up accounts", width=480)
        sheet.heading("Back up your accounts")
        sheet.text("Protect the backup with a passphrase. You'll need the same one to restore it on another "
                   "PC, and it can't be recovered if forgotten.")
        p1 = sheet.field("Passphrase  (8+ characters)", secret=True)
        p2 = sheet.field("Passphrase again", secret=True)
        include = tk.BooleanVar(value=False)
        sheet.check("Also include saved passwords, so auto sign-in works on the other PC", include)

        def create():
            if p1.get() != p2.get():
                raise UserError("The two passphrases don't match.")
            portable.check_passphrase(p1.get())
            return (p1.get(), include.get())

        sheet.buttons("Create Backup", create)
        choice = sheet.show()
        if not choice:
            return
        passphrase, include_pw = choice
        try:
            profiles = portable.gather(self.store, vault, creds, include_pw)
            blob = portable.export_bundle(profiles, passphrase)
        except UserError as e:
            return self.error(str(e))
        path = filedialog.asksaveasfilename(parent=self, title="Save backup (keep it somewhere safe)",
                                            defaultextension=".vasbak", initialfile="accounts.vasbak",
                                            filetypes=[("Switcher backup", "*.vasbak")])
        if not path:
            return
        try:
            Path(path).write_bytes(blob)
        except OSError:
            return self.error("Couldn't write the backup file there. Try another folder.")
        self.notice("Backup saved", f"Backed up {len(profiles)} account(s). Copy the file to your other PC "
                                    "and choose Restore there.\n\nAnyone with this file and the passphrase can "
                                    "sign into these accounts, so keep it safe.")

    def restore(self):
        try:
            vault, creds = self._open_backend()
        except UserError as e:
            return self.error(str(e))
        path = filedialog.askopenfilename(parent=self, title="Choose a backup file",
                                          filetypes=[("Switcher backup", "*.vasbak"), ("All files", "*.*")])
        if not path:
            return
        sheet = Sheet(self, "Restore")
        sheet.heading("Restore from backup")
        word = sheet.field("Passphrase for this backup", secret=True)

        def check():
            if not word.get():
                raise UserError("Enter the passphrase you chose when you made the backup.")
            return word.get()

        sheet.buttons("Restore", check)
        passphrase = sheet.show()
        if not passphrase:
            return
        from . import portable
        try:
            blob = Path(path).read_bytes()
            profiles = portable.import_bundle(blob, passphrase)
            added, updated = portable.apply(profiles, self.store, vault, creds)
        except (UserError, OSError) as e:
            return self.error(str(e) if isinstance(e, UserError) else "Couldn't read that file.")
        self.refresh()
        self.notice("Restored", f"{added} new, {updated} updated. Click an account to switch and play.")

    def open_log(self):
        path = self.store.root / "log.txt"
        if not path.exists():
            return self.notice("No log yet", "It's created the first time you add or switch an account.")
        import subprocess
        # Notepad explicitly: some PCs have no default app for .txt. No passwords or tokens are in it.
        subprocess.Popen(["notepad.exe", str(path)])

    # ---------- appear offline (uses the user's own copy of Deceive) ----------
    def show_offline_state(self):
        on = self.store.read()["settings"].get("appear_offline", False)
        self.offline_btn.set_text("Appear offline: On" if on else "Appear offline: Off")
        self.offline_btn.set_kind("tint" if on else "plain")

    def toggle_offline(self):
        if self.guard_busy():
            return
        settings = self.store.read()["settings"]
        turning_on = not settings.get("appear_offline", False)
        if turning_on and not (settings.get("deceive_path") or self.deceive_available()):
            return self.deceive_setup(turn_on_after=True)
        self.store.set_appear_offline(turning_on)
        self.show_offline_state()
        self.notice("Appear offline " + ("on" if turning_on else "off"),
                    ("Friends will see you as offline" if turning_on else "Friends will see you as normal")
                    + " the next time you start VALORANT from here. If it's open now, close it and "
                    "click your account again.")

    def deceive_available(self):
        from .riot import discover_deceive
        found = discover_deceive()
        if found:
            self.store.set_deceive_path(found)
        return bool(found)

    def deceive_setup(self, turn_on_after=False):
        import webbrowser
        current = self.store.read()["settings"].get("deceive_path", "")
        sheet = Sheet(self, "Appear offline setup", width=580)
        sheet.heading("Appear offline setup")
        sheet.text("Appear offline uses Deceive, a free program made by someone else that hides your chat "
                   "status from friends. It isn't included here, so you download it once:", small=True)
        sheet.text("1.  Click Download Deceive. A page opens in your browser: download Deceive.exe.\n"
                   "2.  Come back here and click \"I've downloaded it\".", color=T.FG)
        sheet.text("Only use that link: the website deceive.app is NOT the real one.", small=True)
        if current:
            sheet.text(f"Using: {current}", small=True)

        def download():
            webbrowser.open("https://github.com/molenzwiebel/Deceive/releases")
            return Sheet.STAY

        def find():
            from .riot import discover_deceive, valid_deceive
            path = discover_deceive()
            if not path:
                path = filedialog.askopenfilename(parent=sheet, title="Choose Deceive.exe",
                                                  filetypes=[("Deceive", "Deceive*.exe")])
                if not path:
                    return
            valid_deceive(path)
            self.store.set_deceive_path(str(path))
            if turn_on_after:
                self.store.set_appear_offline(True)
                self.show_offline_state()
            sheet.close(True)

        sheet.buttons("Download Deceive", download, secondary="Close",
                      left=("I've downloaded it: find Deceive.exe", find))
        sheet.show()

    # ---------- stats overlay (the user's own Overwolf + Tracker app) ----------
    def show_tracker_state(self):
        on = self.store.read()["settings"].get("stats_overlay", False)
        self.tracker_btn.set_text("Stats overlay: On" if on else "Stats overlay: Off")
        self.tracker_btn.set_kind("tint" if on else "plain")

    def toggle_tracker(self):
        from .riot import tracker_app_installed
        if self.guard_busy():
            return
        settings = self.store.read()["settings"]
        turning_on = not settings.get("stats_overlay", False)
        if turning_on:
            have_overwolf = bool(settings.get("tracker_path")) or self.tracker_available()
            if not (have_overwolf and tracker_app_installed()):   # scan first; if missing, offer the install link
                return self.tracker_setup(turn_on_after=True)
        self.store.set_stats_overlay(turning_on)
        self.show_tracker_state()
        self.notice("Stats overlay " + ("on" if turning_on else "off"),
                    "Tracker will open when you start the game from here, and its overlay shows in-game."
                    if turning_on else "Tracker won't be opened by this app anymore.")

    def tracker_available(self):
        from .riot import discover_tracker
        found = discover_tracker()
        if found:
            self.store.set_tracker_path(found)
        return bool(found)

    def tracker_setup(self, turn_on_after=False):
        import webbrowser
        current = self.store.read()["settings"].get("tracker_path", "")
        sheet = Sheet(self, "Stats overlay setup", width=580)
        sheet.heading("Stats overlay setup")
        from .riot import discover_tracker, tracker_app_installed as app_installed
        if not discover_tracker() and not current:
            sheet.text("Not found on this PC: Overwolf and the Tracker app.", color=T.FG)
        elif not app_installed():
            sheet.text("Overwolf is installed, but the Tracker app isn't. Install it with the button below.",
                       color=T.FG)
        sheet.text("The stats overlay is the Tracker app from Tracker Network. It runs inside Overwolf, a free "
                   "program made by someone else. They aren't included here, so you install them once:", small=True)
        sheet.text("1.  Click Download Tracker. A page opens in your browser: install the app (it installs "
                   "Overwolf too).\n"
                   "2.  Come back here and click \"I've installed it\".", color=T.FG)
        if current:
            sheet.text(f"Using: {current}", small=True)

        def download():
            webbrowser.open("https://www.overwolf.com/app/Tracker_Network-Valorant_Tracker")
            return Sheet.STAY

        def find():
            from .riot import discover_tracker, valid_tracker
            path = discover_tracker()
            if not path:
                path = filedialog.askopenfilename(parent=sheet, title="Choose OverwolfLauncher.exe",
                                                  filetypes=[("Overwolf", "Overwolf*.exe")])
                if not path:
                    return
            valid_tracker(path)
            self.store.set_tracker_path(str(path))
            if not app_installed():
                raise UserError("Overwolf was found, but the Tracker app isn't installed in it yet. "
                                "Click Download Tracker, install it, then try again.")
            if turn_on_after:
                self.store.set_stats_overlay(True)
                self.show_tracker_state()
            sheet.close(True)

        sheet.buttons("Download Tracker", download, secondary="Close",
                      left=("I've installed it: find Overwolf", find))
        sheet.show()

    # ---------- updates ----------
    def auto_update_check(self):
        if self.update_settings.due() and not self.closing:
            self.update_manual = False
            updates.check_in_background(lambda r: self.update_events.put(r))

    def check_updates_now(self):
        self.update_manual = True
        updates.check_in_background(lambda r: self.update_events.put(r))

    def toggle_auto_update(self):
        self.update_settings.write(auto=not self.update_settings.read()["auto"])

    def handle_update(self, result):
        manual, self.update_manual = self.update_manual, False
        if result.status != "unavailable":
            self.update_settings.write(last_check=time.time())
        if result.status == "newer":
            self.update_url = result.url
            self.update_label.configure(text=f"Version {result.version} is available")
            if not self.update_bar.winfo_ismapped():
                self.update_bar.pack(fill="x", padx=T.px(36), pady=(T.px(4), 0), before=self.body)
        elif manual and result.status == "current":
            self.notice("You're up to date", f"Version {VERSION} is the newest one.")
        elif manual:
            self.notice("Couldn't check for updates",
                        "Make sure you're online. If it keeps failing, the project's download page may "
                        "not be public yet.")

    def hide_update(self):
        self.update_bar.pack_forget()

    def open_update(self):
        import webbrowser
        webbrowser.open(updates.safe_url(self.update_url))

    # ---------- running a switch ----------
    def launch(self, p):
        if self.busy():
            self.guard_busy()
            return
        self.begin(p["id"], None, False, p["label"])

    def begin(self, profile_id, new_label, relogin, title, new_login=None, save_current=False):
        self.show_dock(title, "Starting…")
        self.add_btn.set_enabled(False)
        self.more_btn.set_enabled(False)
        self.events = queue.Queue()
        self.replies = queue.Queue()
        self.thread, self.cancel = worker.start(self.store, self.events, self.replies, profile_id=profile_id,
                                                new_label=new_label, relogin=relogin, new_login=new_login,
                                                save_current=save_current)

    def stop(self):
        if self.close_menu():
            return
        if self.cancel:
            self.cancel.set()
            self.set_message("Stopping safely…", T.MUTED)
        elif self.dock_visible:
            self.hide_dock()

    # ---------- status dock ----------
    def show_dock(self, title, message):
        self.who.configure(text=title)
        self.set_message(message, T.MUTED)
        self.bar.set(0, T.RED, instant=True)
        self.dock_btn.set_text("Stop")
        self.dock_btn.set_enabled(True)
        if not self.dock_visible:
            self.dock.pack(side="bottom", fill="x", padx=T.px(36), pady=(0, T.px(10)), before=self.body)
            self.dock_visible = True

    def hide_dock(self):
        self.dock.pack_forget()
        self.dock_visible = False

    def set_message(self, text, color):
        if self.dock_visible:
            self.msg.configure(text=text, fg=color)

    def prompt(self, payload):
        """Questions from the background job, asked in a sheet. Reply: a value or None."""
        kind, data = payload.get("kind"), payload.get("data", {})
        if kind == "confirm":
            return self.ask_yes_no(data.get("title", "Continue?"), data.get("message", ""),
                                   yes=data.get("yes", "Yes"), no=data.get("no", "Cancel"),
                                   detail=data.get("detail"), on_top=True)
        if kind == "mfa_code":
            return self.mfa_sheet(data)
        return None

    def handle_prompt(self, payload):
        if self.prompt_open:
            return
        self.prompt_open = True
        try:
            answer = self.prompt(payload)
            self.replies.put(answer)
        finally:
            self.prompt_open = False

    def mfa_sheet(self, data):
        """Asks for a 2FA code (or a Riot Mobile approval). Returns a code, "" = approved on the phone,
        "__email__" = send me an email code instead, or None = I'll finish it in the Riot window."""
        mobile = bool(data.get("mobile"))
        method = data.get("method") or ""
        title = {"email": "Check your email", "sms": "Check your texts", "authenticator": "Authenticator code",
                 "mobile": "Approve on Riot Mobile"}.get(method, "Approve on Riot Mobile" if mobile else "Verification code")
        sheet = Sheet(self, "Verification", width=520, on_top=True)
        sheet.heading(title)
        if data.get("destination"):
            sheet.text(data["destination"], color=T.FG)      # e.g. j***@gmail.com: which inbox to look in
        sheet.text(data.get("message", "Enter the code Riot just sent you."))
        code = sheet.field("Or type a code" if mobile else "Code", size=20, center=True)
        sheet.text("Typed here, sent straight to Riot. Closing this box lets you finish in the Riot window instead.",
                   small=True)

        def submit():
            value = "".join(ch for ch in code.get() if ch.isalnum())
            if not value:
                raise UserError("Type the code Riot gave you." if not mobile else "Type the code, or tap \u2018I approved it\u2019.")
            return value

        if mobile:
            # Two buttons in the row, the email option as a small link underneath, so nothing gets squeezed.
            sheet.buttons("Submit Code", submit, secondary="I approved it", secondary_value="",
                          left=("Email me a code instead", lambda: sheet.close("__email__")))
        else:
            sheet.buttons("Submit Code", submit, secondary=None)
        return sheet.show()

    def poll(self):
        try:
            while True:
                self.handle_update(self.update_events.get_nowait())
        except queue.Empty:
            pass
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == "status":
                    self.set_message(data["message"], T.MUTED)
                    self.bar.set((data["step"] + 1) / STEPS, T.RED)
                elif kind == "done":
                    self.bar.set(1.0, T.GREEN)
                    self.msg.configure(fg=T.GREEN)
                elif kind == "error":
                    self.set_message(data, T.RED)
                elif kind == "prompt":
                    self.handle_prompt(data)
                elif kind == "warning":
                    self.notice("Heads up", data)
                elif kind == "cancelled":
                    self.set_message(data, T.MUTED)
                elif kind == "finished":
                    self.thread = self.cancel = None
                    self.add_btn.set_enabled(True)
                    self.more_btn.set_enabled(True)
                    self.dock_btn.set_text("Dismiss")
                    self.refresh()
        except queue.Empty:
            pass
        if self.closing and not self.busy():
            self.destroy()
            return
        self.after(100, self.poll)

    def on_close(self):
        if self.busy():
            self.closing = True
            self.stop()  # let the switch finish or roll back before exiting
        else:
            self.destroy()
