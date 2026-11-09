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
