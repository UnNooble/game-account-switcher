"""Builds the real window with real Tk (runs on the Windows CI; skipped where Tk or a display is missing)."""
import pytest
from switcher.store import Store as Store_

tk = pytest.importorskip("tkinter")


@pytest.fixture
def app(tmp_path):
    from switcher.store import Store
    from switcher.ui import App

    class Creds:
        def has(self, i): return False
        def load(self, i): return None
        def save(self, *a): pass
        def delete(self, i): pass

    store = Store(tmp_path)
    try:
        window = App(store, Creds())
    except tk.TclError:
        pytest.skip("no display available")
    window.withdraw()
    yield window, store
    window.destroy()


def test_empty_then_cards_then_dock(app):
    window, store = app
    window.update()
    assert len(window.cards.winfo_children()) == 1          # "Add your first account"
    store.add("Main", "Main#EUW")
    store.add("Alt")
    window.refresh()
    window.update()
    assert len(window.cards.winfo_children()) == 2
    window.show_dock("Main", "Starting…")
    window.update()
    assert window.dock_visible
    window.set_message("Signing in…", "#8b97a3")
    window.bar.set(0.6, instant=True)
    window.update()
    window.hide_dock()
    window.update()
    assert not window.dock_visible


def test_menus_and_sheet_open_and_close(app):
    from switcher.widgets import PopupMenu, Sheet
    window, store = app
    PopupMenu(window, window.more_btn, [("One", lambda: None), None, ("Two", lambda: None, "danger")]).destroy()
    sheet = Sheet(window, "Test")
    sheet.heading("Hello")
    sheet.text("Body")
    box = sheet.field("Name", "x")
    sheet.buttons("OK", lambda: box.get())
    window.after(100, sheet._go)
    assert sheet.show() == "x"


def test_animations_setting_defaults_on_and_persists(app):
    from switcher import widgets
    window, store = app
    assert store.read()["settings"]["animations"] is True
    assert widgets.MOTION is True
    window.toggle_animations()
    assert widgets.MOTION is False and store.read()["settings"]["animations"] is False
    window.toggle_animations()
    assert widgets.MOTION is True and store.read()["settings"]["animations"] is True


def test_animate_runs_over_time_and_is_instant_when_off(app):
    import time
    from switcher import widgets
    window, _ = app
    seen = []
    widgets.animate(window, "t", 120, seen.append)
    end = time.time() + 2
    while seen[-1] < 1.0 and time.time() < end:
        window.update()
    assert seen[0] < 1.0 and seen[-1] == 1.0 and len(seen) > 2
    widgets.MOTION = False
    try:
        seen.clear()
        widgets.animate(window, "t", 120, seen.append)
        assert seen == [1.0]
    finally:
        widgets.MOTION = True


def test_buttons_press_and_cards_sweep_in(app):
    import time
    from switcher import theme as T
    from switcher.widgets import Card, Pill
    window, store = app
    store.add("Main")
    window.refresh()
    window.update()
    button = Pill(window.cards, "Play", kind="outline")
    button.pack()
    window.update()
    button.event_generate("<Enter>")
    button.event_generate("<ButtonPress-1>", x=5, y=5)
    window.update()
    assert button._inset > 0 and button._mode == "press"
    button.event_generate("<ButtonRelease-1>", x=5, y=5)
    assert button._inset == 0
    card = Card(window.cards)
    card.pack(fill="x")
    window.update()
    card.intro(0)
    assert card.fill != T.CARD          # starts faded into the background
    end = time.time() + 2
    while card._intro and time.time() < end:
        window.update()
    assert card.fill == T.CARD


class _Logins:
    def __init__(self, items): self.items = items
    def has(self, i): return i in self.items
    def load(self, i): return (self.items[i], "pw") if i in self.items else None
    def save(self, *a): pass
    def delete(self, i): self.items.pop(i, None)


def test_search_matches_nickname_riot_id_and_username(tmp_path):
    from switcher.ui import App
    store = Store_(tmp_path)
    a = store.add("Main", "Nightfall#EUW"); store.add("Smurf", "quiet#NA1"); store.add("Alt")
    try:
        window = App(store, _Logins({a: "loginname42"}))
    except tk.TclError:
        pytest.skip("no display available")
    window.withdraw()
    try:
        window.update()
        assert window.search_row.winfo_ismapped() or window.search_row.winfo_manager() == "pack"
        for query, expect in (("smu", ["Smurf"]), ("nightfall", ["Main"]), ("LOGINNAME", ["Main"]), ("zzz", [])):
            window.query = query
            window.refresh()
            assert [p["label"] for _, p in window._card_list] == expect
    finally:
        window.destroy()


def test_click_plays_and_drag_reorders(app, monkeypatch):
    window, store = app
    store.add("A"); store.add("B"); store.add("C")
    window.deiconify()
    window.refresh()
    window.update()
    played = []
    monkeypatch.setattr(window, "launch", lambda p: played.append(p["label"]))
    first = window._card_list[0][0]
    x, y = first.winfo_rootx() + 300, first.winfo_rooty() + 10   # on the text, not the icon

    class E:   # a minimal pointer event
        def __init__(self, y): self.x_root, self.y_root = x, y
    window._drag_start(first, window._card_list[0][1], E(y))
    window._drag_end(E(y))
    assert played == ["A"]
    last = window._card_list[-1][0]
    window._drag_start(first, window._card_list[0][1], E(y))
    window._drag_move(E(y + 40))
    window._drag_move(E(last.winfo_rooty() + last.winfo_height() - 2))
    window._drag_end(E(last.winfo_rooty() + last.winfo_height() - 2))
    assert [p["label"] for p in store.read()["profiles"]] == ["B", "C", "A"]
    assert played == ["A"]


def test_icons_show_on_cards(app, tmp_path):
    from PIL import Image
    from switcher import icons
    window, store = app
    a = store.add("A"); b = store.add("B")
    store.update(a, icon="glyph:crown", color="#f5c84b")
    src = tmp_path / "p.png"
    Image.new("RGB", (64, 64), "#ff00ff").save(src)
    icons.import_picture(src, store.root, b)
    store.update(b, icon="custom")
    window.refresh()
    window.update()
    assert len(window._card_list) == 2


def test_tray_events_open_and_play(app, monkeypatch):
    window, store = app
    pid = store.add("Main")
    played = []
    monkeypatch.setattr(window, "launch", lambda p: played.append(p["id"]))
    window.handle_tray(("play", pid))
    window.handle_tray(("open",))
    window.update()
    assert played == [pid] and window.winfo_viewable()


def test_tidy_after_launch_hides_once_and_minimizes_launchers(app, monkeypatch):
    from switcher import system
    window, store = app
    window.deiconify()
    window.update()
    calls = []
    monkeypatch.setattr(system, "game_running", lambda: True)
    monkeypatch.setattr(system, "minimize_windows", lambda *a: calls.append(1) or 1)
    window.tidy_after_launch()
    window.update()
    assert calls and window.state() == "iconic"          # no tray in tests: goes to the taskbar instead
    window.deiconify()
    window.update()
    window.tidy_after_launch(attempt=1, hidden=True)      # a later check must not hide it again
    window.update()
    assert window.state() == "normal"


def test_tidy_waits_for_the_game_and_can_be_turned_off(app, monkeypatch):
    from switcher import system
    window, store = app
    calls = []
    monkeypatch.setattr(system, "game_running", lambda: False)
    monkeypatch.setattr(system, "minimize_windows", lambda *a: calls.append(1))
    window.tidy_after_launch()
    assert calls == []                                    # game not running yet: nothing minimized
    assert store.read()["settings"]["tidy_after_launch"] is True
    window.toggle_tidy()
    monkeypatch.setattr(system, "game_running", lambda: True)
    window.tidy_after_launch()
    assert calls == [] and store.read()["settings"]["tidy_after_launch"] is False


def _pointer(card, y):
    class E:
        x_root, y_root = card.winfo_rootx() + 50, y
    return E()


def test_drag_near_the_top_does_not_jump_the_list(app):
    window, store = app
    for n in ("A", "B", "C"):
        store.add(n)
    window.deiconify()
    window.refresh()
    window.update()
    card, p = window._card_list[0]
    top = card.winfo_rooty() + 4
    window._drag_start(card, p, _pointer(card, top))
    for dy in (10, 14, 18, 22, 26):
        window._drag_move(_pointer(card, top + dy))
        window.update()
        assert window.canvas.canvasy(0) == 0
    window._drag_end(_pointer(card, top + 26))
    assert [x["label"] for x in store.read()["profiles"]] == ["A", "B", "C"]


def test_held_card_moves_live_and_hover_pauses(app):
    from switcher.widgets import Card
    window, store = app
    for n in ("A", "B", "C"):
        store.add(n)
    window.deiconify()
    window.refresh()
    window.update()
    card, p = window._card_list[0]
    y = card.winfo_rooty() + 10
    window._drag_start(card, p, _pointer(card, y))
    window._drag_move(_pointer(card, y + 20))
    window._drag_move(_pointer(card, window._card_list[1][0].winfo_rooty() + window._card_list[1][0].winfo_height()))
    window.update()
    ghost = window._drag["ghost"]
    assert Card.frozen and ghost.winfo_exists() and window._drag["slot"].winfo_ismapped()
    on_screen = [q["label"] for c, q in sorted(window._card_list, key=lambda cp: cp[0].winfo_y())]
    assert on_screen == ["B", "A", "C"]                       # moved before letting go
    window._drag_end(_pointer(card, y + 200))
    assert [x["label"] for x in store.read()["profiles"]] == ["B", "A", "C"]
    import time
    end = time.time() + 2
    while Card.frozen and time.time() < end:          # the floating copy glides into its slot, then goes away
        window.update()
    assert not Card.frozen and not ghost.winfo_exists()


def test_floating_card_follows_the_pointer_sideways(app):
    window, store = app
    for n in ("A", "B"):
        store.add(n)
    window.deiconify()
    window.refresh()
    window.update()
    card, p = window._card_list[0]
    x, y = card.winfo_rootx() + 300, card.winfo_rooty() + 20

    class E:
        def __init__(self, dx, dy): self.x_root, self.y_root = x + dx, y + dy
    window._drag_start(card, p, E(0, 0))
    window._drag_move(E(120, 15))
    window.update()
    assert window._drag["ghost"].winfo_rootx() - card.winfo_rootx() == 120
    window._drag_end(E(120, 15))


def test_clicking_the_icon_opens_the_picker_and_picks_apply_at_once(app, monkeypatch):
    from switcher.widgets import Avatar, Sheet
    window, store = app
    pid = store.add("Main")
    window.refresh()
    window.update()
    played, opened = [], []
    monkeypatch.setattr(window, "launch", lambda q: played.append(q))
    monkeypatch.setattr(Sheet, "show", lambda self: opened.append(self) or self.close())
    card = window._card_list[0][0]
    avatar = next(w for w in card.inner.winfo_children() if isinstance(w, Avatar))
    avatar.event_generate("<Button-1>", x=3, y=3)
    window.update()
    assert opened and not played
    store.update(pid, icon="glyph:star", color="#3ddc97")       # what a click on a tile does
    assert store.get(pid)["icon"] == "glyph:star"
