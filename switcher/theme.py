"""Colors, fonts and sizing.

The palette is the app's original navy + red. The layout follows Apple's design ideas: one clear
focus, generous space, soft rounded shapes, one accent color used sparingly, quiet secondary text.
"""
from tkinter import font as tkfont

# surfaces (darkest to lightest)
BG = "#0f1923"
CARD = "#17222e"
CARD_HOVER = "#1c2a39"
SHEET = "#17222e"
MENU = "#1c2937"
FIELD = "#0f1923"
CHIP = "#243342"
CHIP_HOVER = "#2c3d4f"
CHIP_PRESS = "#1f2d3b"
CHIP_OFF = "#1a2531"
AVATAR = "#26374a"
LINE = "#2a3a4b"

# text
FG = "#ece8e1"
MUTED = "#8b97a3"
FAINT = "#5d6b79"

# accent
RED = "#ff4655"
RED_HOVER = "#ff5d6a"
RED_PRESS = "#e63b49"
RED_TINT = "#3a2531"       # red at ~15% on a card: calm "tinted" buttons
GREEN = "#3ddc97"

SCALE = 1.0
_family = "Segoe UI"
_fonts: dict = {}


def init(root):
    """Call once after the Tk root exists: detects screen scaling and the best system font."""
    global SCALE, _family
    try:
        SCALE = max(1.0, float(root.winfo_fpixels("1i")) / 96.0)
    except Exception:
        SCALE = 1.0
    try:
        available = set(tkfont.families(root))
    except Exception:
        available = set()
    for name in ("Segoe UI Variable Display", "Segoe UI Variable Text", "Segoe UI"):
        if name in available:
            _family = name
            break


def px(n):
    """Design pixels -> real pixels for this screen's scaling."""
    return int(round(n * SCALE))


def font(size=11, bold=False):
    key = (size, bold)
    if key not in _fonts:
        _fonts[key] = tkfont.Font(family=_family, size=size, weight="bold" if bold else "normal")
    return _fonts[key]
