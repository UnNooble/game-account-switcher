"""Game Account Switcher - double-click Start.cmd (or the built EXE). No admin rights needed."""
import os
import sys


def main():
    args = sys.argv[1:]
    if os.name != "nt":
        print("This app needs Windows 10/11 with Riot Client installed.")
        return 1
    import ctypes
    from ctypes import wintypes
    import tkinter as tk
    from tkinter import messagebox
    from switcher import APP_NAME
    from switcher.errors import UserError
    from switcher.store import Store, data_directory
    from switcher.ui import App

    if args[:1] == ["--forget-everything"]:  # run by the uninstaller, only if the user agreed
        from switcher.system import forget_everything
        forget_everything(data_directory())
        return 0
    autoplay = args[1] if len(args) >= 2 and args[0] == "--play" else None

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    mutex = kernel.CreateMutexW(None, False, "Local\\ValorantProfiles-1")  # same name as v2: never run both
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        root = tk.Tk(); root.withdraw()
        messagebox.showinfo(APP_NAME, "The app is already open. Use PLAY in its window"
                            + (" (or close it and use the shortcut again)." if autoplay else "."), parent=root)
        return 0
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    try:
        store = Store(data_directory())
        store.read()
        from switcher.credentials import Credentials
        App(store, Credentials(), autoplay).mainloop()
    except UserError as e:
        root = tk.Tk(); root.withdraw()
        messagebox.showerror(APP_NAME, str(e), parent=root)
        return 1
    finally:
        if mutex:
            kernel.CloseHandle(mutex)
    return 0


if __name__ == "__main__":
    sys.exit(main())
