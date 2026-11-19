"""Account icons: a letter, one of the app's own emblems, or a picture the user picks.

The emblems are original shapes drawn here in code (no game artwork), in the HUD style of the rest of the app.
Uploaded pictures are cropped to a square, shrunk and saved as PNG in the data folder (icons/<profile id>.png);
the original file is never kept or changed.
"""
from __future__ import annotations

import math
from pathlib import Path

from . import theme as T
from .errors import UserError

try:
    from PIL import Image, ImageDraw, ImageOps
    HAVE_PIL = True
except Exception:  # pragma: no cover
    HAVE_PIL = False

# Badge colors people can choose. "" means the default look (neutral badge, red for the last-used account).
PALETTE = ["#ff4655", "#ff8a3d", "#f5c84b", "#3ddc97", "#2fc7d6", "#4d8dff", "#9b6bff", "#ef5da8"]

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
STORED_SIZE = 256


def _poly(d, pts, s, fill):
    d.polygon([(x * s / 100, y * s / 100) for x, y in pts], fill=fill)


def _line(d, pts, s, fill, w):
    d.line([(x * s / 100, y * s / 100) for x, y in pts], fill=fill, width=max(1, int(w * s / 100)), joint="curve")


def _ell(d, box, s, fill=None, outline=None, w=0):
    d.ellipse([v * s / 100 for v in box], fill=fill, outline=outline, width=max(0, int(w * s / 100)))


def _crosshair(d, s, c):
    _ell(d, (22, 22, 78, 78), s, outline=c, w=7)
    for a, b in (((50, 6), (50, 30)), ((50, 70), (50, 94)), ((6, 50), (30, 50)), ((70, 50), (94, 50))):
        _line(d, (a, b), s, c, 7)
    _ell(d, (44, 44, 56, 56), s, fill=c)


def _bolt(d, s, c):
    _poly(d, [(58, 6), (22, 56), (46, 56), (38, 94), (78, 40), (54, 40), (66, 6)], s, c)


def _flame(d, s, c):
    pts = []
    for i in range(41):                          # a teardrop leaning right, with a notch on the left
        t = i / 40 * 2 * math.pi
        r = 30 * (1 - 0.55 * math.sin(t / 2) ** 6)
        pts.append((50 + r * math.sin(t) * 0.9, 60 - 34 * math.cos(t) * (0.55 if math.cos(t) < 0 else 1.0)))
    _poly(d, pts, s, c)
    _poly(d, [(50, 4), (64, 34), (40, 30)], s, c)


def _star(d, s, c):
    pts = []
    for i in range(10):
        r = 44 if i % 2 == 0 else 18
        a = math.pi / 2 + i * math.pi / 5
        pts.append((50 + r * math.cos(a), 54 - r * math.sin(a)))
    _poly(d, pts, s, c)


def _crown(d, s, c):
    _poly(d, [(10, 76), (10, 30), (30, 52), (50, 18), (70, 52), (90, 30), (90, 76)], s, c)
    _poly(d, [(10, 82), (90, 82), (90, 90), (10, 90)], s, c)


def _shield(d, s, c):
    _poly(d, [(50, 6), (88, 18), (84, 56), (50, 94), (16, 56), (12, 18)], s, c)


def _diamond(d, s, c):
    _poly(d, [(50, 4), (92, 50), (50, 96), (8, 50)], s, c)
    _poly(d, [(50, 26), (72, 50), (50, 74), (28, 50)], s, (0, 0, 0, 0))


def _eye(d, s, c):
    top = [(8 + 84 * i / 20, 50 - 30 * math.sin(math.pi * i / 20)) for i in range(21)]
    bottom = [(92 - 84 * i / 20, 50 + 30 * math.sin(math.pi * i / 20)) for i in range(21)]
    _poly(d, top + bottom, s, c)
    _ell(d, (34, 34, 66, 66), s, fill=(0, 0, 0, 0))
    _ell(d, (42, 42, 58, 58), s, fill=c)


def _chevron(d, s, c):
    for y in (14, 44):
        _poly(d, [(10, y + 14), (50, y), (90, y + 14), (90, y + 30), (50, y + 16), (10, y + 30)], s, c)
    _poly(d, [(26, 84), (74, 84), (74, 92), (26, 92)], s, c)


def _orbit(d, s, c):
    _ell(d, (32, 32, 68, 68), s, fill=c)
    _ell(d, (6, 34, 94, 66), s, outline=c, w=6)
    _ell(d, (78, 14, 90, 26), s, fill=c)


def _skull(d, s, c):
    _ell(d, (16, 8, 84, 72), s, fill=c)
    _poly(d, [(28, 60), (72, 60), (72, 90), (28, 90)], s, c)
    _ell(d, (28, 34, 46, 52), s, fill=(0, 0, 0, 0))
    _ell(d, (54, 34, 72, 52), s, fill=(0, 0, 0, 0))
    _poly(d, [(50, 56), (45, 66), (55, 66)], s, (0, 0, 0, 0))
    for x in (38, 50, 62):
        _poly(d, [(x - 2, 78), (x + 2, 78), (x + 2, 90), (x - 2, 90)], s, (0, 0, 0, 0))


def _blade(d, s, c):
    _poly(d, [(90, 6), (94, 10), (36, 72), (28, 64)], s, c)
    _poly(d, [(16, 60), (40, 84), (34, 90), (10, 66)], s, c)
    _poly(d, [(24, 76), (30, 82), (14, 96), (8, 90)], s, c)


GLYPHS = {"crosshair": _crosshair, "bolt": _bolt, "flame": _flame, "star": _star, "crown": _crown,
          "shield": _shield, "diamond": _diamond, "eye": _eye, "chevron": _chevron, "orbit": _orbit,
          "skull": _skull, "blade": _blade}


def badge_colors(profile, active):
    """(badge fill, mark color) for an account."""
    color = profile.get("color") or ""
    if color:
        return T.blend(T.CARD, color, 0.22), color
    if active:
        return T.RED_TINT, T.RED
    return T.AVATAR, T.FG


def glyph_image(name, size, color):
    """The emblem as a transparent RGBA image, size x size pixels."""
    ss = 4
    im = Image.new("RGBA", (size * ss, size * ss), (0, 0, 0, 0))
    GLYPHS.get(name, _crosshair)(ImageDraw.Draw(im), size * ss, color or T.FG)
    return im.resize((size, size), Image.LANCZOS)


def custom_path(root, profile_id) -> Path:
    from .store import valid_id
    if not valid_id(profile_id):
        raise UserError("Invalid profile.")
    return Path(root) / "icons" / (profile_id + ".png")


def read_picture(source):
    """Open a picture the user picked: checked, turned upright, square-cropped and shrunk. Nothing is saved."""
    src = Path(source)
    try:
        if src.stat().st_size > MAX_UPLOAD_BYTES:
            raise UserError("That picture is too large. Pick one under 20 MB.")
        with Image.open(src) as im:
            im.verify()                                   # rejects broken or disguised files
        with Image.open(src) as im:
            if im.width * im.height > 50_000_000:
                raise UserError("That picture is too large. Pick a smaller one.")
            im = ImageOps.exif_transpose(im).convert("RGBA")
            im = ImageOps.fit(im, (STORED_SIZE, STORED_SIZE), Image.LANCZOS)
    except UserError:
        raise
    except Exception:
        raise UserError("That file couldn't be opened as a picture. Try a PNG or JPG.") from None
    return im


def save_picture(image, root, profile_id) -> Path:
    dest = custom_path(root, profile_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    image.save(dest, "PNG")
    return dest


def import_picture(source, root, profile_id) -> Path:
    """read_picture + save_picture in one step."""
    return save_picture(read_picture(source), root, profile_id)


def remove_picture(root, profile_id) -> None:
    try:
        custom_path(root, profile_id).unlink(missing_ok=True)
    except (OSError, UserError):
        pass


def load_picture(root, profile_id, size):
    """The saved picture at size x size, or None if it's missing or unreadable."""
    try:
        with Image.open(custom_path(root, profile_id)) as im:
            return im.convert("RGBA").resize((size, size), Image.LANCZOS)
    except Exception:
        return None
