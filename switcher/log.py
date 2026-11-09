"""Plain-text diagnostics log. Never write tokens, passwords, cookies or file contents here."""
import time
from pathlib import Path

_path = None


def setup(data_root):
    global _path
    _path = Path(data_root) / "log.txt"
    try:
        if _path.exists() and _path.stat().st_size > 300_000:
            _path.replace(_path.with_suffix(".old.txt"))
    except OSError:
        pass


def path():
    return _path


def log(message):
    if _path is None:
        return
    try:
        _path.parent.mkdir(parents=True, exist_ok=True)
        with open(_path, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + str(message) + "\n")
    except OSError:
        pass
