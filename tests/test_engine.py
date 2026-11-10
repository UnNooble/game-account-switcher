import base64
import json
import threading

import pytest

from switcher.engine import Engine
from switcher.credentials import NoCredentials
from switcher.errors import Cancelled, UserError
from switcher.store import Store
from switcher.vault import SessionFiles, Vault, MAIN_FILE
from switcher.riot import parse_userinfo, jwt_sub, is_authorized, RiotClient

A = "aaaaaaaa-0000-0000-0000-000000000001"
B = "bbbbbbbb-0000-0000-0000-000000000002"


class Plain:
    encrypt = staticmethod(lambda raw: raw[::-1])
    decrypt = staticmethod(lambda raw: raw[::-1])


def yaml_for(account, token="t1"):
    return (f'riot-login:\n  persist:\n    session:\n      cookies:\n        - domain: "auth.riotgames.com"\n'
            f'          name: "ssid"\n          value: "{token}"\n        - domain: "auth.riotgames.com"\n'
            f'          name: "sub"\n          path: "/"\n          value: "{account}"\n')


class FakeRiot:
    """Signs in from whatever login file is on disk, like the real client."""

    def __init__(self, data):
        self.data, self.running, self.game, self.valorant = data, False, False, False
        self.typing = None          # account the "user" will type in on the login screen
        self.typing_delay = 3
        self.launches = self.opens = self.closes = 0
        self.wrong_account = None
        self._ticks = 0

    def file(self):
        return self.data / MAIN_FILE

    def game_running(self): return self.game
    def running_games(self): return ["VALORANT"] if self.game else []

    def close_game(self):
        self.game, self.valorant = False, False
        self.game_closed = getattr(self, "game_closed", 0) + 1
    def valorant_running(self): return self.valorant
    def start_tracker(self, path): self.tracker_started = getattr(self, 'tracker_started', []) + [path]
    def client_running(self): return self.running

    def close(self):
        if self.game:
            raise UserError("game running")
        self.running = False
        self.closes += 1

    def open(self, deceive=""):
        self.opened_with = deceive
        self.running, self._ticks = True, 0
        self.opens += 1

    def whoami(self):
        if not self.running:
            return None, ""
        self._ticks += 1
        if self.wrong_account:
            return self.wrong_account, "Wrong#0000"
        text = self.file().read_text() if self.file().exists() else ""
        for acc in (A, B):
            if acc in text and "expired" not in text:
                return acc, ("Alpha#NA1" if acc == A else "Bravo#EU1")
        if self.typing and self._ticks > self.typing_delay:
            self.file().parent.mkdir(parents=True, exist_ok=True)
            self.file().write_text(yaml_for(self.typing, getattr(self, "typing_token", "fresh")))
            return self.typing, ("Alpha#NA1" if self.typing == A else "Bravo#EU1")
        return None, ""

    def launch_valorant(self):
        self.launches += 1
        self.valorant = True

    def sign_in(self, username, password):
        """Simulates Riot's login service. Accounts: alpha/pw-a -> A, bravo/pw-b -> B."""
        self.sign_ins = getattr(self, "sign_ins", 0) + 1
        if self.sign_ins <= getattr(self, "not_ready_for", 0):
            return {"status": "notready"}
        if getattr(self, "signin_result", None):
            return dict(self.signin_result)
        account = {("alpha", "pw-a"): A, ("bravo", "pw-b"): B}.get((username, password))
        if not account:
            return {"status": "invalid"}
        self._pending = account
        if getattr(self, "mfa", None):
            return {"status": "mfa", "method": self.mfa, "email": "a***@x.com", "length": 6}
        self.typing, self.typing_delay = account, self._ticks  # Riot signs in on the next check
        self.typing_token = "auto"
        return {"status": "submitted"}

    def submit_mfa(self, code):
        self.mfa_codes = getattr(self, "mfa_codes", []) + [code]
        if code == getattr(self, "good_code", "000000"):
            self.typing, self.typing_delay = self._pending, self._ticks
            self.typing_token = "auto"
            return "ok"
        return "bad"

    def nudge_login(self):
        self.nudges = getattr(self, "nudges", 0) + 1


class Clock:
    def __init__(self): self.t = 0.0
    def now(self): return self.t
    def sleep(self, s): self.t += s


@pytest.fixture
def env(tmp_path):
    riot_data = tmp_path / "riot"
    (riot_data / "Data").mkdir(parents=True)
    (riot_data / "Config").mkdir()
    (riot_data / "Config" / "RiotClientSettings.yaml").write_text("keep me")
    store = Store(tmp_path / "app")
    riot = FakeRiot(riot_data)
    vault = Vault(store.root, SessionFiles(riot_data), Plain())
    clock = Clock()
    events = []
    cancel = threading.Event()
    creds = NoCredentials()
    engine = Engine(riot, vault, store, lambda k, d: events.append((k, d)), cancel, clock.now, clock.sleep,
                    creds=creds)
    return type("Env", (), dict(store=store, riot=riot, vault=vault, engine=engine, clock=clock, creds=creds,
                                events=events, cancel=cancel, data=riot_data))


def kill_saved_login(env, pid, account):
    env.riot.running = False
    env.riot.file().unlink()
    saved = env.vault.load(pid)
    saved["files"][MAIN_FILE] = base64.b64encode(b"expired").decode()
    env.vault._write(env.vault.path(pid), dict(saved, identity=account))


def add(env, label, account):
    env.riot.typing = account
    pid = env.engine.run(new_label=label)
    env.riot.typing, env.riot.valorant = None, False
    return pid


def test_add_account_captures_login_and_launches(env):
    pid = add(env, "Main", A)
    p = env.store.get(pid)
    assert p["label"] == "Main" and p["riot_id"] == "Alpha#NA1"
    assert env.vault.identity(pid) == A
    assert env.store.read()["active"] == pid
    assert env.riot.launches >= 1
    assert (env.data / "Config" / "RiotClientSettings.yaml").read_text() == "keep me"


def test_switch_between_accounts_uses_one_restart(env):
    a = add(env, "Main", A)
    b = add(env, "Alt", B)
    env.riot.opens = env.riot.closes = 0
    env.engine.run(a)
    assert A in env.riot.file().read_text()
    assert env.riot.opens == 1  # saved login: no extra close/reopen cycle
    assert env.store.read()["active"] == a
    env.riot.valorant = False
    env.engine.run(b)
    assert B in env.riot.file().read_text()


def test_outgoing_tokens_are_refreshed_before_switching(env):
    a = add(env, "Main", A)
    b = add(env, "Alt", B)
    env.engine.run(a)
    env.riot.valorant = False
    env.riot.file().write_text(yaml_for(A, "rotated-token"))  # Riot rotated tokens while playing
    env.engine.run(b)
    saved = env.vault.load(a)["files"][MAIN_FILE]
    assert "rotated-token" in base64.b64decode(saved).decode()


def test_offline_refresh_when_riot_closed(env):
    a = add(env, "Main", A)
    b = add(env, "Alt", B)
    env.engine.run(a)
    env.riot.valorant = False
    env.riot.running = False
    env.riot.file().write_text(yaml_for(A, "rotated-offline"))
    env.engine.run(b)
    assert "rotated-offline" in base64.b64decode(env.vault.load(a)["files"][MAIN_FILE]).decode()


def test_refuses_while_game_running_when_nobody_can_be_asked(env):
    a = add(env, "Main", A)
    add(env, "Alt", B)          # Riot is now signed into Alt
    env.riot.game = True
    with pytest.raises(UserError, match="Close VALORANT"):
        env.engine.run(a)       # default ask() returns None: there is no window to ask in


def test_game_running_asks_then_closes_and_switches(env):
    a = add(env, "Main", A)
    b = add(env, "Alt", B)
    env.riot.game = env.riot.valorant = True
    asked = []
    env.engine.ask = lambda kind, data: asked.append((kind, data)) or True
    env.engine.run(a)
    kind, data = asked[0]
    assert kind == "confirm" and "Main" in data["title"] and "VALORANT" in data["message"]
    assert "leaving" in data["detail"]
    assert env.riot.game_closed == 1 and env.riot.valorant and A in env.riot.file().read_text()


def test_declining_the_prompt_leaves_the_game_alone(env):
    a = add(env, "Main", A)
    add(env, "Alt", B)
    env.riot.game = True
    env.engine.ask = lambda kind, data: False
    with pytest.raises(Cancelled, match="left running"):
        env.engine.run(a)
    assert env.riot.game and getattr(env.riot, "game_closed", 0) == 0
    assert B in env.riot.file().read_text()   # nothing was swapped


def test_clicking_the_account_already_playing_does_not_prompt(env):
    a = add(env, "Main", A)
    env.riot.game = True
    env.engine.ask = lambda kind, data: pytest.fail("should not ask")
    opens = env.riot.opens
    assert env.engine.run(a) == a
    assert env.riot.opens == opens and env.riot.game


def test_wrong_account_blocks_launch(env):
    a = add(env, "Main", A)
    env.riot.launches = 0
    env.riot.wrong_account = B
    with pytest.raises(UserError, match="different account"):
        env.engine.run(a)
    assert env.riot.launches == 0


def test_adding_an_existing_account_refreshes_and_plays_it(env):
    pid = add(env, "Main", A)
    env.riot.typing = A
    again = env.engine.run(new_label="Again")
    assert again == pid and env.riot.valorant
    profiles = env.store.read()["profiles"]
    assert len(profiles) == 1 and profiles[0]["label"] == "Main"


def test_stay_signed_in_missing_warns_but_lets_you_play(env, monkeypatch):
    env.riot.typing = A
    monkeypatch.setattr(env.vault.files, "has_remembered_login", lambda: False)
    pid = env.engine.run(new_label="Main")
    assert env.store.get(pid) and env.riot.valorant
    assert any(k == "warning" and "Stay signed in" in d for k, d in env.events)


def test_add_keeps_riot_client_settings(env):
    add(env, "Main", A)
    assert (env.data / "Config" / "RiotClientSettings.yaml").read_text() == "keep me"


def test_slow_saved_login_gets_nudged(env):
    a = add(env, "Main", A)
    kill_saved_login(env, a, A)
    env.riot.typing, env.riot.typing_delay = A, 12
    env.engine.run(a)
    assert env.riot.nudges == 1


def test_expired_login_is_recaptured(env):
    a = add(env, "Main", A)
    b = add(env, "Alt", B)
    # Make A's saved login dead: Riot will show the login screen.
    kill_saved_login(env, a, A)
    env.riot.typing, env.riot.typing_delay = A, 40
    env.riot.typing_token = "relogin"
    env.engine.run(a)
    assert "relogin" in base64.b64decode(env.vault.load(a)["files"][MAIN_FILE]).decode()


def test_interrupted_switch_is_recovered(env):
    a = add(env, "Main", A)
    before = env.riot.file().read_text()
    env.vault._write(env.vault.journal, {"files": env.vault.files.snapshot()})
    env.riot.file().write_text("half written")
    env.riot.valorant = False
    env.engine.run(a)
    assert not env.vault.needs_recovery()
    assert env.riot.file().read_text() == before


def test_stop_cancels(env):
    a = add(env, "Main", A)
    env.cancel.set()
    with pytest.raises(Cancelled):
        env.engine.run(a)


def test_store_reads_v2_profiles(tmp_path):
    root = tmp_path / "app"
    root.mkdir()
    pid = "12345678-1234-4234-8234-123456789abc"
    (root / "profiles.json").write_text(json.dumps(
        {"version": 1, "profiles": [{"id": pid, "label": "Old"}], "settings": {"riot_path": "", "selectors": {}}}))
    data = Store(root).read()
    assert data["profiles"][0]["label"] == "Old" and data["active"] is None


def test_allowlist_rejects_unsafe_paths():
    ok = SessionFiles.allowed
    assert ok("Data/RiotGamesPrivateSettings.yaml") and ok("Data/Cookies/x")
    assert ok("Config/RiotClientSettings.yaml")
    for bad in ("../x", "Data/Cookies/../../evil", "C:/x", "Data\\Cookies\\x", "Config/lockfile",
                "Data/Cookies/CON", "/abs"):
        assert not ok(bad), bad


def test_old_snapshot_extra_files_are_ignored():
    files = {"Data/RiotGamesPrivateSettings.yaml": base64.b64encode(b"x").decode(),
             "Config/lockfile": base64.b64encode(b"y").decode()}
    assert list(SessionFiles.clean(files)) == ["Data/RiotGamesPrivateSettings.yaml"]


def test_offline_identity_parses_sub_cookie(tmp_path):
    f = SessionFiles(tmp_path)
    (tmp_path / "Data").mkdir()
    (tmp_path / MAIN_FILE).write_text(yaml_for(A))
    assert f.offline_identity() == A and f.has_remembered_login()


def jwt(payload):
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return "eyJhbGciOiJSUzI1NiJ9." + body + ".sig"


def test_parse_userinfo_and_jwt():
    info = {"userInfo": json.dumps({"sub": A.upper(), "acct": {"game_name": "Alpha", "tag_line": "NA1"}})}
    assert parse_userinfo(info) == (A, "Alpha#NA1")
    assert jwt_sub(jwt({"sub": A})) == A and jwt_sub("garbage") is None
    assert is_authorized({"accessToken": {"token": "x"}}, None)
    assert is_authorized(None, {"type": "authenticated"})
    assert not is_authorized({"errorCode": "RESOURCE_NOT_FOUND"}, {"type": "unauthenticated"})


def test_whoami_works_when_only_new_endpoint_answers(tmp_path, monkeypatch):
    """The v3.0 bug: current Riot answers /rso-auth/v1/authorization, not the old session check."""
    client = RiotClient.__new__(RiotClient)
    client.data, client._last_status, client._logged_identity = tmp_path, {}, False
    replies = {"/rso-auth/v1/authorization": {"accessToken": {"token": "enc"}, "idToken": {"token": jwt({"sub": B})}},
               "/player-account/aliases/v1/active": {"game_name": "Bravo", "tag_line": "EU1"}}
    monkeypatch.setattr(client, "_get", lambda path: replies.get(path))
    assert client.whoami() == (B, "Bravo#EU1")
    replies.clear()
    assert client.whoami() == (None, "")


def test_add_with_password_signs_in_by_itself(env):
    pid = env.engine.run(new_label="Main", new_login=("alpha", "pw-a"))
    assert env.vault.identity(pid) == A and env.riot.valorant
    assert env.creds.load(pid) == ("alpha", "pw-a")
    assert "auto" in base64.b64decode(env.vault.load(pid)["files"][MAIN_FILE]).decode()


def test_wrong_password_is_reported_and_not_saved(env):
    with pytest.raises(UserError, match="wrong"):
        env.engine.run(new_label="Main", new_login=("alpha", "nope"))
    assert env.store.read()["profiles"] == [] and env.creds.items == {}


def test_captcha_falls_back_to_riot_window(env):
    env.riot.signin_result = {"status": "captcha"}
    env.riot.typing, env.riot.typing_delay = A, 5   # user finishes in the Riot window
    pid = env.engine.run(new_label="Main", new_login=("alpha", "pw-a"))
    assert env.vault.identity(pid) == A
    assert any(k == "status" and "captcha" in d["message"] for k, d in env.events)


def test_waits_for_riot_login_service(env):
    env.riot.not_ready_for = 6
    pid = env.engine.run(new_label="Main", new_login=("alpha", "pw-a"))
    assert env.vault.identity(pid) == A and env.riot.sign_ins == 7


def test_expired_login_uses_saved_password(env):
    a = env.engine.run(new_label="Main", new_login=("alpha", "pw-a"))
    env.riot.valorant, env.riot.typing = False, None
    kill_saved_login(env, a, A)
    env.riot.sign_ins = 0
    env.engine.run(a)
    assert env.riot.sign_ins == 1 and env.riot.valorant
    assert "auto" in base64.b64decode(env.vault.load(a)["files"][MAIN_FILE]).decode()


def test_saved_login_does_not_send_password(env):
    a = env.engine.run(new_label="Main", new_login=("alpha", "pw-a"))
    b = env.engine.run(new_label="Alt", new_login=("bravo", "pw-b"))
    env.riot.valorant, env.riot.typing, env.riot.sign_ins = False, None, 0
    env.engine.run(a)
    assert env.riot.sign_ins == 0  # remembered login was enough


def test_save_account_already_signed_in(env):
    env.riot.running = True
    env.riot.file().write_text(yaml_for(B, "already"))
    opens = env.riot.opens
    pid = env.engine.save_current("Alt")
    assert env.vault.identity(pid) == B and env.store.get(pid)["riot_id"] == "Bravo#EU1"
    assert env.riot.opens == opens and env.riot.closes == 0  # no restart, nothing launched
    assert env.store.read()["active"] == pid


def test_save_current_needs_riot_signed_in(env):
    with pytest.raises(UserError, match="isn't signed in"):
        env.engine.save_current("Alt")


def test_save_current_rejects_duplicate(env):
    add(env, "Main", A)
    env.riot.running = True
    with pytest.raises(UserError, match="already saved as 'Main'"):
        env.engine.save_current("Again")


def test_resource_and_launch_command():
    from switcher import resource, launch_command
    assert resource("assets", "icon.ico").is_file()
    target, args = launch_command("--play", "x")
    assert args.endswith("--play x") and "main.py" in args


# ---- portable backup / restore ----
from switcher import portable


def test_backup_roundtrip_real_crypto():
    profiles = [{"label": "Main", "riot_id": "Alpha#NA1", "identity": A,
                 "files": {MAIN_FILE: base64.b64encode(b"tok").decode()}}]
    blob = portable.export_bundle(profiles, "correct horse battery")
    assert blob.startswith(portable.MAGIC)
    out = portable.import_bundle(blob, "correct horse battery")
    assert out[0]["identity"] == A and out[0]["label"] == "Main"


def test_backup_wrong_passphrase_rejected():
    blob = portable.export_bundle([{"label": "x", "identity": A, "files": {}}], "right-passphrase")
    with pytest.raises(UserError, match="[Ww]rong passphrase"):
        portable.import_bundle(blob, "wrong-passphrase")


def test_backup_tamper_detected():
    blob = bytearray(portable.export_bundle([{"label": "x", "identity": A, "files": {}}], "passphrase1"))
    blob[-1] ^= 0x01
    with pytest.raises(UserError):
        portable.import_bundle(bytes(blob), "passphrase1")


def test_backup_rejects_short_passphrase():
    with pytest.raises(UserError, match="at least 8"):
        portable.export_bundle([{"label": "x", "identity": A, "files": {}}], "short")


def test_backup_rejects_foreign_file():
    with pytest.raises(UserError, match="isn't a"):
        portable.import_bundle(b"not a backup", "whatever12")


def test_gather_and_apply_moves_accounts_to_new_pc(env):
    add(env, "Main", A)
    env.engine.run(new_label="Alt", new_login=("bravo", "pw-b"))
    env.creds.save(env.store.read()["profiles"][1]["id"], "bravo", "pw-b")
    bundle = portable.gather(env.store, env.vault, env.creds, include_passwords=True)
    assert len(bundle) == 2

    # Fresh "PC": new store, same Plain crypto, empty creds.
    from switcher.store import Store
    from switcher.vault import Vault, SessionFiles
    new_store = Store(env.store.root.parent / "pc2")
    new_store.root.mkdir()
    new_vault = Vault(new_store.root, env.vault.files, Plain())
    new_creds = NoCredentials()
    added, updated = portable.apply(bundle, new_store, new_vault, new_creds)
    assert (added, updated) == (2, 0)
    labels = {p["label"] for p in new_store.read()["profiles"]}
    assert labels == {"Main", "Alt"}
    # Re-importing the same bundle updates, never duplicates.
    added2, updated2 = portable.apply(bundle, new_store, new_vault, new_creds)
    assert added2 == 0 and updated2 == 2
    assert len(new_store.read()["profiles"]) == 2
    # The moved login is usable: decrypts and carries the token.
    pid = next(p["id"] for p in new_store.read()["profiles"] if p["label"] == "Alt")
    assert "auto" in base64.b64decode(new_vault.load(pid)["files"][MAIN_FILE]).decode()


def test_gather_needs_something_to_back_up(env):
    with pytest.raises(UserError, match="no saved logins"):
        portable.gather(env.store, env.vault, env.creds, include_passwords=False)


def test_mfa_prompts_in_app_and_submits_code(env):
    env.riot.mfa, env.riot.good_code = "email", "123456"
    codes = iter(["000000", "123456"])  # first wrong, then right
    env.engine.ask = lambda kind, data: next(codes)
    pid = env.engine.run(new_label="Main", new_login=("alpha", "pw-a"))
    assert env.vault.identity(pid) == A and env.riot.valorant
    assert env.riot.mfa_codes == ["000000", "123456"]


def test_mfa_cancel_falls_back_to_riot_window(env):
    env.riot.mfa = "authenticator"
    # User closes the code box (None), then finishes in the Riot window.
    env.engine.ask = lambda kind, data: (setattr(env.riot, "typing", A) or
                                         setattr(env.riot, "typing_delay", env.riot._ticks) or None)
    pid = env.engine.run(new_label="Main", new_login=("alpha", "pw-a"))
    assert env.vault.identity(pid) == A


def test_mfa_push_waits_without_prompting(env):
    env.riot.mfa = "push"
    asked = []
    env.engine.ask = lambda kind, data: asked.append(kind)
    # Approve on "Riot Mobile": the account signs in shortly after.
    env.riot.typing, env.riot.typing_delay = A, env.riot._ticks + 3
    pid = env.engine.run(new_label="Main", new_login=("alpha", "pw-a"))
    assert env.vault.identity(pid) == A and asked == []  # no code box for push


def test_mfa_details_parsed():
    from switcher.riot import RiotClient
    d = RiotClient._mfa_details({"multifactor": {"method": "email", "email": "a***@x.com",
                                                 "multiFactorCodeLength": 6}})
    assert d == {"method": "email", "email": "a***@x.com", "length": 6}


def test_new_login_starts_the_game_before_saving_it(env):
    """The game shouldn't wait for the login to be written to disk (that wait is several seconds)."""
    seen = []
    real = env.vault.capture
    def spy(*a, **k):
        seen.append(env.riot.launches)
        return real(*a, **k)
    env.vault.capture = spy
    env.engine.run(new_label="Main", new_login=("alpha", "pw-a"))
    assert seen and seen[0] >= 1


def test_riot_reply_summary_is_short_and_safe():
    from switcher.riot import _reason
    raw = b'{"type":"error","error":"rate_limited","message":"slow down","secret":"nope"}'
    assert _reason(raw) == "type=error error=rate_limited message=slow down"
    assert _reason(b"not json") == "" and _reason(b"[1]") == ""


# ---- signing in by operating Riot's own window (Riot removed the background login service) ----

class FakeUI:
    def __init__(self, riot, pages=None, good_code="123456"):
        self.riot, self.pages, self.good = riot, pages or [], good_code
        self.filled, self.codes, self.clicks = [], [], []
        self.fill_ok, self.signs_in_on_fill = True, True

    def fill_login(self, username, password, stay=True, wait=25):
        self.filled.append((username, password))
        if not self.fill_ok:
            return {"ok": False, "error": "no sign-in form found"}
        if self.signs_in_on_fill:
            self.riot.typing, self.riot.typing_delay = A, self.riot._ticks
        return {"ok": True, "stay": True}

    def inventory(self, wait=0):
        page = self.pages.pop(0) if len(self.pages) > 1 else (self.pages[0] if self.pages else {"found": False})
        return page

    def fill_code(self, code, wait=6):
        self.codes.append(code)
        if code == self.good:
            self.riot.typing, self.riot.typing_delay = A, self.riot._ticks
            return {"ok": True}
        return {"ok": True}

    def click(self, pattern, wait=4):
        self.clicks.append(pattern)
        return {"ok": True}


FORM = {"found": True, "edits": [{"name": "USERNAME", "password": False}, {"name": "PASSWORD", "password": True}],
        "texts": ["Sign in", "Stay signed in"]}
WRONG = dict(FORM, texts=["Your username or password may be incorrect."])
CODE_PAGE = {"found": True, "edits": [{"name": "Code", "password": False}], "texts": ["Enter your verification code"]}
MOBILE_PAGE = {"found": True, "edits": [], "texts": ["Approve the sign-in in Riot Mobile"]}


def window_mode(env, pages=None, **kw):
    env.riot.signin_result = {"status": "unavailable", "http": 404, "detail": "HTTP 404 errorCode=RESOURCE_NOT_FOUND"}
    env.riot.ui = FakeUI(env.riot, pages or [FORM], **kw)
    return env.riot.ui


def test_riot_window_is_filled_in_when_the_background_login_is_gone(env):
    ui = window_mode(env)
    pid = env.engine.run(new_label="Main", new_login=("alpha", "pw-a"))
    assert ui.filled == [("alpha", "pw-a")]
    assert env.vault.identity(pid) == A and env.riot.valorant
    assert env.creds.load(pid) == ("alpha", "pw-a")


def test_riot_window_asks_for_the_2fa_code_here_and_types_it_there(env):
    ui = window_mode(env, [CODE_PAGE])
    ui.signs_in_on_fill = False
    asked = []
    env.engine.ask = lambda kind, data: (asked.append((kind, data["mobile"])) or "123456")
    pid = env.engine.run(new_label="Main", new_login=("alpha", "pw-a"))
    assert asked == [("mfa_code", False)] and ui.codes == ["123456"]
    assert env.vault.identity(pid) == A


def test_riot_mobile_page_can_switch_to_an_email_code(env):
    ui = window_mode(env, [MOBILE_PAGE, CODE_PAGE])
    ui.signs_in_on_fill = False
    answers = iter(["__email__", "123456"])
    asked = []
    env.engine.ask = lambda kind, data: (asked.append(data["mobile"]) or next(answers))
    env.engine.run(new_label="Main", new_login=("alpha", "pw-a"))
    assert asked == [True, False] and len(ui.clicks) == 1 and ui.codes == ["123456"]


def test_riot_mobile_approval_needs_no_typing(env):
    window_mode(env, [MOBILE_PAGE]).signs_in_on_fill = False

    def ask(kind, data):          # "I approved it", and Riot signs in a moment later
        env.riot.typing, env.riot.typing_delay = A, env.riot._ticks + 2
        return ""
    env.engine.ask = ask
    pid = env.engine.run(new_label="Main", new_login=("alpha", "pw-a"))
    assert env.vault.identity(pid) == A


def test_wrong_password_in_the_riot_window_is_reported(env):
    window_mode(env, [WRONG]).signs_in_on_fill = False
    with pytest.raises(UserError, match="wrong"):
        env.engine.run(new_label="Main", new_login=("alpha", "pw-a"))
    assert env.store.read()["profiles"] == []


def test_if_the_window_cannot_be_filled_the_user_is_told_to_do_it_there(env):
    ui = window_mode(env)
    ui.fill_ok = False
    env.riot.typing, env.riot.typing_delay = A, 6      # user signs in themselves
    pid = env.engine.run(new_label="Main", new_login=("alpha", "pw-a"))
    assert env.vault.identity(pid) == A
    assert any(k == "status" and "Couldn't fill in the Riot window" in d["message"] for k, d in env.events)


def test_classify_riot_window_pages():
    from switcher.riotui import classify
    assert classify({"found": False}) == "none"
    assert classify(FORM) == "login" and classify(WRONG) == "invalid"
    assert classify(CODE_PAGE) == "mfa_code" and classify(MOBILE_PAGE) == "mfa_mobile"


def test_code_prompt_says_where_riot_sent_it(env):
    page = {"found": True, "edits": [{"name": "c", "password": False}] * 6,
            "texts": ["Verification code", "We sent a code to j***@example.com"]}
    ui = window_mode(env, [page])
    ui.signs_in_on_fill = False
    seen = []
    env.engine.ask = lambda kind, data: (seen.append(data) or "123456")
    env.engine.run(new_label="Main", new_login=("alpha", "pw-a"))
    assert seen[0]["method"] == "email" and seen[0]["destination"] == "j***@example.com"
    assert "j***@example.com" in seen[0]["message"]


def test_mfa_details_variants():
    from switcher.riotui import mfa_details
    assert mfa_details({"texts": ["Open Riot Mobile"]})["method"] == "mobile"
    assert mfa_details({"texts": ["authenticator app"]})["method"] == "authenticator"
    assert mfa_details({"texts": ["hello"]})["method"] == "unknown"


def test_appear_offline_starts_riot_through_deceive(env, tmp_path):
    a = add(env, "Main", A)
    b = add(env, "Alt", B)
    deceive = tmp_path / "Deceive.exe"
    deceive.write_bytes(b"x")
    env.store.set_deceive_path(str(deceive))
    env.store.set_appear_offline(True)
    env.engine.run(a)
    assert env.riot.opened_with == str(deceive)           # switch on: starts through Deceive
    env.riot.valorant = False
    env.store.set_appear_offline(False)
    env.engine.run(b)
    assert env.riot.opened_with == ""                      # switch off: plays normally


def test_appear_offline_without_deceive_explains_itself(env):
    a = add(env, "Main", A)
    env.store.set_appear_offline(True)
    with pytest.raises(UserError, match="Deceive"):
        env.engine.run(a)


def test_offline_flag_and_path_survive_save_and_load(env, tmp_path):
    env.store.set_appear_offline(True)
    env.store.set_deceive_path("C:/x/Deceive.exe")
    data = env.store.read()
    assert data["settings"]["appear_offline"] is True and data["settings"]["deceive_path"] == "C:/x/Deceive.exe"


def test_deceive_path_must_look_like_deceive(tmp_path):
    from switcher.riot import valid_deceive
    good = tmp_path / "Deceive.exe"
    good.write_bytes(b"x")
    assert valid_deceive(good) == good.resolve()
    evil = tmp_path / "notepad.exe"
    evil.write_bytes(b"x")
    for bad in (evil, tmp_path / "Deceive.exe.bak", tmp_path / "missing" / "Deceive.exe"):
        with pytest.raises(UserError):
            valid_deceive(bad)


def test_stats_overlay_starts_overwolf_only_when_on(env, monkeypatch):
    monkeypatch.setattr("switcher.riot.tracker_app_installed", lambda: True)
    a = add(env, "Main", A)
    env.engine.run(a)
    assert getattr(env.riot, "tracker_started", []) == []          # off by default
    env.riot.valorant = False
    env.store.set_tracker_path("C:/x/OverwolfLauncher.exe")
    env.store.set_stats_overlay(True)
    env.engine.run(a)
    assert env.riot.tracker_started == ["C:/x/OverwolfLauncher.exe"]


def test_stats_overlay_problem_warns_but_game_still_starts(env, monkeypatch):
    monkeypatch.setattr("switcher.riot.discover_tracker", lambda: "")
    a = add(env, "Main", A)
    env.store.set_stats_overlay(True)
    env.engine.run(a)
    assert env.riot.valorant
    assert any(k == "warning" and "Overwolf" in d for k, d in env.events)


def test_valid_tracker_needs_overwolf(tmp_path):
    from switcher.riot import valid_tracker
    good = tmp_path / "OverwolfLauncher.exe"
    good.write_bytes(b"x")
    assert valid_tracker(good) == good.resolve()
    bad = tmp_path / "other.exe"
    bad.write_bytes(b"x")
    with pytest.raises(UserError):
        valid_tracker(bad)


def test_tracker_is_opened_by_its_app_id(tmp_path, monkeypatch):
    import subprocess
    from switcher import riot as riot_mod
    exe = tmp_path / "OverwolfLauncher.exe"
    exe.write_bytes(b"x")
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: calls.append(cmd))
    riot_mod.RiotClient.start_tracker(object(), str(exe))
    assert calls == [[str(exe.resolve()), "-launchapp", riot_mod.TRACKER_APP_ID]]


def test_stats_overlay_warns_when_tracker_app_missing(env, monkeypatch):
    monkeypatch.setattr("switcher.riot.tracker_app_installed", lambda: False)
    a = add(env, "Main", A)
    env.store.set_tracker_path("C:/x/OverwolfLauncher.exe")
    env.store.set_stats_overlay(True)
    env.engine.run(a)
    assert env.riot.valorant and getattr(env.riot, "tracker_started", []) == []
    assert any(k == "warning" and "Tracker app" in d for k, d in env.events)


def test_tracker_app_detection_looks_for_its_folder(tmp_path, monkeypatch):
    from switcher.riot import tracker_app_installed, TRACKER_APP_ID
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert tracker_app_installed() is False
    (tmp_path / "Overwolf" / "Extensions" / TRACKER_APP_ID).mkdir(parents=True)
    assert tracker_app_installed() is True
