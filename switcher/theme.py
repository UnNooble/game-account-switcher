"""Colors, fonts, sizing and motion.

Look: a tactical HUD. Deep slate panels with cut corners, one signal red used sparingly, and an angular
display face (Chakra Petch, bundled in assets/fonts) for titles, names and buttons. The boldest element is
the last-used account (red edge stripe on a red-tinted panel); everything else stays quiet.
"""
from tkinter import font as tkfont

# surfaces (darkest to lightest)
BG = "#0d151e"
CARD = "#141f2b"
CARD_HOVER = "#1a2838"
CARD_ACTIVE = "#2a2230"        # panel tinted ~10% toward the signal red
CARD_ACTIVE_HOVER = "#352533"
SHEET = "#141f2b"
MENU = "#1a2735"
FIELD = "#0d151e"
CHIP = "#1f2d3c"
CHIP_HOVER = "#283a4d"
CHIP_PRESS = "#1a2633"
CHIP_OFF = "#18222d"
AVATAR = "#223142"
LINE = "#27384b"

# text
FG = "#ece8e1"
MUTED = "#8b97a3"
FAINT = "#5a6977"

# accent
RED = "#ff4655"
RED_HOVER = "#ff6472"
RED_PRESS = "#e03a48"
RED_TINT = "#3a1f2a"       # red at ~15% on a panel
GREEN = "#3ddc97"

# shape: corner cuts (design pixels) by hierarchy, so not everything shares one radius
CUT_CARD = 14
CUT_BUTTON = 9
CUT_SMALL = 6

SCALE = 1.0
_family = "Segoe UI"
_display = None            # Chakra Petch once loaded; None falls back to the body font
_fonts: dict = {}


def blend(a, b, t):
    """Mix two #rrggbb colors: t=0 gives a, t=1 gives b."""
    t = max(0.0, min(1.0, t))
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(ca, cb))


def ease_out(t):
    return 1 - (1 - t) ** 3


def _load_bundled_fonts():
    """Make assets/fonts/*.ttf usable by this process only (nothing is installed on the PC)."""
    try:
        import ctypes
        from . import resource
        for path in sorted(resource("assets", "fonts").glob("*.ttf")):
            ctypes.windll.gdi32.AddFontResourceExW(str(path), 0x10, 0)   # 0x10 = FR_PRIVATE
    except Exception:
        pass


def init(root):
    """Call once after the Tk root exists: detects screen scaling and the best fonts."""
    global SCALE, _family, _display
    _fonts.clear()             # fonts belong to one Tk root; a new root needs new ones
    try:
        SCALE = max(1.0, float(root.winfo_fpixels("1i")) / 96.0)
    except Exception:
        SCALE = 1.0
    _load_bundled_fonts()
    try:
        available = set(tkfont.families(root))
    except Exception:
        available = set()
    for name in ("Segoe UI Variable Text", "Segoe UI Variable Display", "Segoe UI"):
        if name in available:
            _family = name
            break
    _display = "Chakra Petch" if "Chakra Petch" in available else None


def px(n):
    """Design pixels -> real pixels for this screen's scaling."""
    return int(round(n * SCALE))


def font(size=11, bold=False, display=False):
    """display=True: the angular HUD face (always bold), for titles, names and buttons."""
    family = (_display or _family) if display else _family
    weight = "bold" if (bold or display) else "normal"
    key = (family, size, weight)
    if key not in _fonts:
        _fonts[key] = tkfont.Font(family=family, size=size, weight=weight)
    return _fonts[key]
