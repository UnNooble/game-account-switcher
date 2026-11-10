import sys
from pathlib import Path

VERSION = "3.9.0"
APP_NAME = "Game Account Switcher"


def resource(*parts) -> Path:
    """Path to a bundled file, both when run from source and from the installed EXE."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base.joinpath(*parts)


def launch_command(*args):
    """(target, arguments) that start this app, for shortcuts."""
    if getattr(sys, "frozen", False):
        return sys.executable, " ".join(args)
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe") if exe.name.lower() == "python.exe" else exe
    main = Path(__file__).resolve().parent.parent / "main.py"
    return str(pythonw), " ".join([f'"{main}"', *args])
