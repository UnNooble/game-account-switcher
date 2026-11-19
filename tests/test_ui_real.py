"""Builds the real window with real Tk (runs on the Windows CI; skipped where Tk or a display is missing)."""
import pytest

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
