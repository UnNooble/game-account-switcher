"""The icon next to the clock (system tray): open the window, play an account, or quit.

pystray runs the icon on its own thread. Nothing here touches Tk directly: clicks are put on a queue that the
window reads in App.poll(), which keeps all window work on the Tk thread.
"""
from __future__ import annotations

import queue

from . import APP_NAME, resource


class Tray:
    def __init__(self, store):
        self.store = store
        self.events = queue.Queue()          # ("open",) | ("play", profile_id) | ("quit",)
        self.icon = None

    def start(self) -> bool:
        """Show the tray icon. Returns False (and the app simply has no tray) if it can't be created."""
        try:
            import pystray
            from PIL import Image
            image = Image.open(resource("assets", "icon.png"))
            self.icon = pystray.Icon("GameAccountSwitcher", image, APP_NAME, menu=pystray.Menu(self._items))
            self.icon.run_detached()
            return True
        except Exception:
            self.icon = None
            return False

    def _items(self):
        """Built fresh each time the menu opens, so it always lists the current accounts."""
        import pystray
        item, sep = pystray.MenuItem, pystray.Menu.SEPARATOR
        try:
            data = self.store.read()
        except Exception:
            data = {"profiles": [], "active": None}
        accounts = [item(p["label"], self._play(p["id"]), radio=True,
                         checked=lambda _i, pid=p["id"], active=data["active"]: pid == active)
                    for p in data["profiles"][:15]]
        return (item("Open " + APP_NAME, lambda: self.events.put(("open",)), default=True),
                sep, *accounts, *( [sep] if accounts else [] ),
                item("Quit", lambda: self.events.put(("quit",))))

    def _play(self, profile_id):
        return lambda: self.events.put(("play", profile_id))

    def notify(self, title, message) -> None:
        try:
            if self.icon is not None:
                self.icon.notify(message, title)
        except Exception:
            pass

    def stop(self) -> None:
        try:
            if self.icon is not None:
                self.icon.stop()
        except Exception:
            pass
        self.icon = None
