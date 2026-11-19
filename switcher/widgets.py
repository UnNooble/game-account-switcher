"""Custom widgets for the tactical HUD look (Tkinter has none of these built in).

Shapes are panels with two cut corners (top-left and bottom-right), drawn as smooth supersampled images with
Pillow; without Pillow they fall back to plain canvas polygons, so the app still works.

Motion: buttons fade between colors, shrink a little and flash where you click; cards fade on hover and sweep
in once when the window opens; the progress bar has a moving shine while working; dialogs and menus fade in.
All of it can be turned off in the app (··· > Animations). The app has its own switch instead of
following Windows' "Animation effects", which many gamers turn off for performance, not by choice.
"""
from __future__ import annotations

import time
import tkinter as tk

from . import theme as T
from .errors import UserError

try:
    from PIL import Image, ImageDraw, ImageTk
    HAVE_PIL = True
except Exception:  # pragma: no cover - Pillow is a bundled dependency
    HAVE_PIL = False


MOTION = True   # the app sets this from its own "Animations" setting (··· menu); on by default


def animate(widget, name, duration_ms, step, done=None):
    """Call step(t) with t going 0 -> 1 over duration_ms (about 60 times a second). A newer animation
    with the same name on the same widget replaces the running one."""
    jobs = widget.__dict__.setdefault("_anims", {})
    if name in jobs:
        try:
            widget.after_cancel(jobs.pop(name))
        except (tk.TclError, ValueError):
            pass
    if not MOTION or duration_ms <= 0:
        try:
            step(1.0)
        except tk.TclError:
            return
        if done:
            done()
        return
    start = time.perf_counter()

    def tick():
        t = min(1.0, (time.perf_counter() - start) * 1000.0 / duration_ms)
        try:
            step(t)
        except tk.TclError:   # the widget was destroyed mid-animation
            jobs.pop(name, None)
            return
        if t < 1.0:
            jobs[name] = widget.after(16, tick)
        else:
            jobs.pop(name, None)
            if done:
                done()

    tick()


def _steps(t, n):
    """Round an eased 0..1 value to n steps, so in-between frames repeat and come from the image cache."""
    return round(T.ease_out(t) * n) / n


def _rgb(color):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


# ---------------------------------------------------------------- shapes

class Shape:
    """A cut-corner panel living on a canvas. Rendered images are cached, so fades between a few colors are
    cheap after the first pass."""
    SS = 3          # supersampling factor for smooth edges
    CACHE = 24

    def __init__(self, canvas, back=True):
        self.c, self.back = canvas, back
        self.item = None
        self.img = None
        self.key = None
        self._cache = {}

    def hide(self):
        if self.item is not None:
            self.c.itemconfigure(self.item, state="hidden")

    def draw(self, w, h, cut, fill, outline=None, ow=0, stripe=None, inset=0, flash=None):
        """stripe = (color, width) band on the left edge;
        inset = draw smaller by this many pixels on each side (pressed look);
        flash = (x, y, radius, strength 0..1) a light burst clipped to the shape."""
        w, h = max(int(w), 2), max(int(h), 2)
        iw, ih = max(2, w - 2 * inset), max(2, h - 2 * inset)
        cut = max(0, min(int(cut), iw // 2, ih // 2))
        if self.item is not None:
            self.c.itemconfigure(self.item, state="normal")
        key = (iw, ih, cut, fill, outline, ow, stripe, inset, flash)
        if key == self.key:
            return
        self.key = key
        if HAVE_PIL:
            img = self._cache.get(key) if flash is None else None
            if img is None:
                img = ImageTk.PhotoImage(self._render(iw, ih, cut, fill, outline, ow, stripe, flash),
                                         master=self.c)
                if flash is None:
                    if len(self._cache) >= self.CACHE:
                        self._cache.pop(next(iter(self._cache)))
                    self._cache[key] = img
            self.img = img
            if self.item is None:
                self.item = self.c.create_image(inset, inset, anchor="nw", image=img)
                self._layer()
            else:
                self.c.coords(self.item, inset, inset)
                self.c.itemconfigure(self.item, image=img)
        else:
            x2, y2 = inset + iw - 1, inset + ih - 1
            x1, y1 = inset, inset
            pts = [x1 + cut, y1, x2, y1, x2, y2 - cut, x2 - cut, y2, x1, y2, x1, y1 + cut]
            if self.item is None:
                self.item = self.c.create_polygon(pts, fill=fill, outline=outline or fill)
                self._layer()
            else:
                self.c.coords(self.item, *pts)
                self.c.itemconfigure(self.item, fill=fill, outline=outline or fill)

    def _render(self, w, h, cut, fill, outline, ow, stripe, flash):
        ss = self.SS
        W, H, c = w * ss, h * ss, cut * ss
        pts = [(c, 0), (W - 1, 0), (W - 1, H - 1 - c), (W - 1 - c, H - 1), (0, H - 1), (0, c)]
        im = Image.new("RGBA", (W, H), _rgb(fill) + (255,))
        if flash:
            fx, fy, fr, strength = flash
            layer = Image.new("RGBA", (W, H), (255, 255, 255, 0))
            ImageDraw.Draw(layer).ellipse([(fx - fr) * ss, (fy - fr) * ss, (fx + fr) * ss, (fy + fr) * ss],
                                          fill=(255, 255, 255, int(150 * strength)))
            im = Image.alpha_composite(im, layer)
        draw = ImageDraw.Draw(im)
        if stripe:
            draw.rectangle([0, 0, stripe[1] * ss, H], fill=stripe[0])
        if outline and ow:
            draw.polygon(pts, outline=outline, width=ow * ss * 2)   # half of it falls outside and is cut off
        mask = Image.new("L", (W, H), 0)
        ImageDraw.Draw(mask).polygon(pts, fill=255)
        im.putalpha(mask)
        return im.resize((w, h), Image.BOX)

    def _layer(self):
        if self.back:
            self.c.tag_lower(self.item)
        else:
            self.c.tag_raise(self.item)


def style_titlebar(win):
    """Dark, flat title bar that blends into the window (Windows 10 2004+/11). Ignored elsewhere."""
    try:
        import ctypes
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())

        def bgr(hex_color):
            r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
            return (b << 16) | (g << 8) | r

        for attr, value in ((20, 1), (19, 1), (35, bgr(T.BG)), (36, bgr(T.FG))):
            v = ctypes.c_int(value)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))
    except Exception:
        pass


# ---------------------------------------------------------------- buttons

class Pill(tk.Canvas):
    """Cut-corner button. kind: primary | outline | tint | plain | ghost.
    (The name is historical: it used to be a rounded pill.)"""

    def __init__(self, parent, text, command=None, kind="plain", height=34, padx=18, square=False,
                 width=None, align="center", radius=None, fg=None, bg=None, display=True):
        self.kind, self.command, self.align = kind, command, align
        self._cut_override, self._fg_override = radius, fg
        self._label, self._enabled, self._mode, self._text_item = text, True, "normal", None
        self._font = T.font(10, display=display) if display else T.font(10)
        self._pad = T.px(padx)
        self._height_px = T.px(height)
        self._square = square
        self._fixed_width = T.px(width) if width else None
        self._width_px = self._measure()
        self._inset, self._flash, self.fade = 0, None, 1.0
        super().__init__(parent, width=self._width_px, height=self._height_px,
                         bg=bg or parent.cget("bg"), highlightthickness=0, bd=0, cursor="hand2")
        self._shape = Shape(self)
        self._cur = self._target()            # (fill, text, outline) currently shown
        self.bind("<Enter>", lambda e: self._set_mode("hover"))
        self.bind("<Leave>", lambda e: self._set_mode("normal"))
        self.bind("<ButtonPress-1>", self._pressed)
        self.bind("<ButtonRelease-1>", self._released)
        self._redraw()

    def _measure(self):
        if self._square:
            return self._height_px
        if self._fixed_width:
            return self._fixed_width
        return self._font.measure(self._label) + 2 * self._pad

    def _palette(self):
        """{mode: (fill, text, outline)}"""
        back = self.cget("bg")
        fg = self._fg_override
        if self.kind == "primary":
            return {"normal": (T.RED, "#ffffff", None), "hover": (T.RED_HOVER, "#ffffff", None),
                    "press": (T.RED_PRESS, "#ffffff", None)}
        if self.kind == "outline":
            return {"normal": (back, T.RED, T.RED), "hover": (T.RED, "#ffffff", T.RED),
                    "press": (T.RED_PRESS, "#ffffff", T.RED_PRESS)}
        if self.kind == "tint":
            return {"normal": (T.RED_TINT, T.RED, None), "hover": (T.RED, "#ffffff", None),
                    "press": (T.RED_PRESS, "#ffffff", None)}
        if self.kind == "ghost":
            return {"normal": (back, fg or T.MUTED, None), "hover": (T.CHIP, fg or T.FG, None),
                    "press": (T.CHIP_PRESS, fg or T.FG, None)}
        return {"normal": (T.CHIP, fg or T.FG, None), "hover": (T.CHIP_HOVER, fg or T.FG, None),
                "press": (T.CHIP_PRESS, fg or T.FG, None)}

    def _target(self):
        if not self._enabled:
            return (self.cget("bg") if self.kind == "ghost" else T.CHIP_OFF, T.FAINT, None)
        return self._palette()[self._mode]

    def _cut(self):
        if self._cut_override is not None:
            return min(T.px(self._cut_override) // 2, self._height_px // 3)
        return min(T.px(T.CUT_BUTTON), self._height_px // 3)

    def _redraw(self):
        fill, text_color, outline = self._cur
        back = self.cget("bg")
        if self.fade < 1.0:                     # intro: everything rises out of the backdrop color
            fill = T.blend(back, fill, self.fade)
            text_color = T.blend(back, text_color, self.fade)
            outline = outline and T.blend(back, outline, self.fade)
        w, h = self._width_px, self._height_px
        self._shape.draw(w, h, self._cut(), fill, outline, max(1, T.px(1)) if outline else 0,
                         inset=self._inset, flash=self._flash)
        x, anchor = (self._pad, "w") if self.align == "w" else (w // 2, "center")
        if self._text_item is None:
            self._text_item = self.create_text(x, h // 2, text=self._label, fill=text_color,
                                               font=self._font, anchor=anchor)
        else:
            self.coords(self._text_item, x, h // 2)
            self.itemconfigure(self._text_item, text=self._label, fill=text_color, anchor=anchor)
        self.tag_raise(self._text_item)

    def _go_to(self, duration=140):
        """Fade from the colors on screen to the ones for the current mode."""
        start, end = self._cur, self._target()

        def step(t):
            q = _steps(t, 5)
            self._cur = tuple(None if b is None else (b if a is None else T.blend(a, b, q))
                              for a, b in zip(start, end))
            if t >= 1.0:
                self._cur = end
            self._redraw()

        animate(self, "color", duration, step)

    def _set_mode(self, mode):
        if self._enabled and mode != self._mode:
            self._mode = mode
            self._go_to(70 if mode == "press" else 140)

    def _pressed(self, event):
        if not self._enabled:
            return
        self._inset = max(1, T.px(2))
        self._set_mode("press")
        if self.kind != "ghost":
            self._ripple(event.x, event.y)

    def _ripple(self, x, y):
        """A burst of light that spreads from the click point and fades."""
        reach = max(self._width_px, self._height_px) * 1.1

        def step(t):
            e = T.ease_out(t)
            self._flash = None if t >= 1.0 else (int(x), int(y), max(2, int(reach * e)), 1 - e)
            self._redraw()

        animate(self, "ripple", 420, step)

    def _released(self, event):
        if not self._enabled:
            return
        self._inset = 0
        inside = 0 <= event.x < self._width_px and 0 <= event.y < self._height_px
        self._set_mode("hover" if inside else "normal")
        self._redraw()
        if inside and self.command:
            self.command()

    # -- public helpers
    def set_enabled(self, enabled):
        self._enabled = bool(enabled)
        self._mode, self._inset = "normal", 0
        self.configure(cursor="hand2" if enabled else "arrow")
        self._cur = self._target()
        self._redraw()

    def set_kind(self, kind):
        self.kind = kind
        self._cur = self._target()
        self._redraw()

    def set_text(self, text):
        self._label = text
        self._width_px = self._measure()
        self.configure(width=self._width_px)
        self._redraw()

    def set_backdrop(self, color):
        """The color behind the cut corners (the parent's background) changed."""
        self.configure(bg=color)
        self._cur = self._target() if self._mode == "normal" else self._cur
        self._redraw()

    def set_fade(self, value):
        self.fade = value
        self._redraw()


class Avatar(tk.Canvas):
    """Cut-corner badge showing an initial, an emblem (glyph name from icons.GLYPHS) or a picture (PIL image)."""

    def __init__(self, parent, letter, fill, size=44, fg=None, glyph=None, picture=None):
        s = T.px(size)
        super().__init__(parent, width=s, height=s, bg=parent.cget("bg"), highlightthickness=0, bd=0)
        self._size, self._fill, self._fg, self.fade = s, fill, fg or T.FG, 1.0
        self._glyph, self._picture, self._images = glyph, picture, {}
        self._shape = Shape(self)          # kept on self: Tk drops images nothing in Python refers to
        self._mark = None
        if picture is None and glyph is None:
            self._mark = self.create_text(s // 2, s // 2, text=letter, font=T.font(15, display=True))
        else:
            self._mark = self.create_image(s // 2, s // 2, anchor="center")
        self._redraw()

    def _mark_image(self, back, step):
        """PhotoImage of the emblem or picture at this fade step (cached; there are only a few steps)."""
        key = (back, step)
        if key not in self._images:
            from . import icons
            f = step / 8
            s = self._size
            if self._picture is not None:
                mask = Image.new("L", (s * 3, s * 3), 0)
                c = T.px(T.CUT_SMALL + 2) * 3
                W = s * 3 - 1
                ImageDraw.Draw(mask).polygon([(c, 0), (W, 0), (W, W - c), (W - c, W), (0, W), (0, c)], fill=255)
                im = self._picture.resize((s, s), Image.LANCZOS)
                if f < 1.0:
                    im = Image.blend(Image.new("RGBA", (s, s), _rgb(back) + (255,)), im, f)
                im.putalpha(Image.composite(im.getchannel("A"), Image.new("L", (s, s), 0),
                                            mask.resize((s, s), Image.LANCZOS)))
            else:
                inner = int(s * 0.62)
                im = icons.glyph_image(self._glyph, inner, T.blend(back, self._fg, f))
            self._images[key] = ImageTk.PhotoImage(im, master=self)
        return self._images[key]

    def _redraw(self):
        back = self.cget("bg")
        if self._picture is not None:          # the picture fills the badge; no colored plate behind it
            self._shape.hide()
        else:
            self._shape.draw(self._size, self._size, T.px(T.CUT_SMALL + 2), T.blend(back, self._fill, self.fade))
        if self._glyph is None and self._picture is None:
            self.itemconfigure(self._mark, fill=T.blend(back, self._fg, self.fade))
        elif HAVE_PIL:
            self.itemconfigure(self._mark, image=self._mark_image(back, round(self.fade * 8)))
        self.tag_raise(self._mark)

    def set_backdrop(self, color):
        self.configure(bg=color)
        self._redraw()

    def set_fade(self, value):
        self.fade = value
        self._redraw()


class Progress(tk.Canvas):
    """Slim progress bar that glides to its new value, with a shine sweeping along it while working."""

    def __init__(self, parent, height=6):
        super().__init__(parent, height=T.px(height), bg=parent.cget("bg"), highlightthickness=0, bd=0)
        self._track = self.create_rectangle(0, 0, 0, 0, width=0, fill=T.CHIP)
        self._bar = self.create_rectangle(0, 0, 0, 0, width=0, fill=T.RED)
        self._shine = self.create_rectangle(0, 0, 0, 0, width=0, fill=T.RED, state="hidden")
        self.value, self._target, self.color, self._job = 0.0, 0.0, T.RED, None
        self._phase, self._shimmer_job = 0.0, None
        self.bind("<Configure>", lambda e: self._draw())

    def set(self, fraction, color=None, instant=False):
        self._target = max(0.0, min(1.0, float(fraction)))
        if color:
            self.color = color
        if instant:
            self.value = self._target
            self._draw()
        elif self._job is None:
            self._step()

    def _step(self):
        self._job = None
        delta = self._target - self.value
        self.value = self._target if abs(delta) < 0.004 else self.value + delta * 0.25
        self._draw()
        if self.value != self._target:
            self._job = self.after(16, self._step)

    def shimmer(self, on):
        """Start or stop the moving shine (only drawn while there is a filled part to sweep over)."""
        if on and MOTION and self._shimmer_job is None:
            self._shimmer_tick()
        elif not on and self._shimmer_job is not None:
            self.after_cancel(self._shimmer_job)
            self._shimmer_job = None
            self.itemconfigure(self._shine, state="hidden")

    def _shimmer_tick(self):
        self._phase = (self._phase + 0.018) % 1.0
        self._draw()
        self._shimmer_job = self.after(16, self._shimmer_tick)

    def _draw(self):
        try:
            w, h = self.winfo_width(), self.winfo_height()
            if w < 4 or h < 2:
                return
            self.coords(self._track, 0, 0, w, h)
            filled = int(w * self.value)
            self.coords(self._bar, 0, 0, filled, h)
            self.itemconfigure(self._bar, fill=self.color, state="normal" if filled > 0 else "hidden")
            if self._shimmer_job is not None and filled > 8:
                size = max(T.px(40), filled // 4)
                x = -size + (filled + size) * self._phase
                self.coords(self._shine, max(0, x), 0, min(filled, x + size), h)
                self.itemconfigure(self._shine, fill=T.blend(self.color, "#ffffff", 0.45),
                                   state="normal" if x + size > 0 and x < filled else "hidden")
            else:
                self.itemconfigure(self._shine, state="hidden")
        except tk.TclError:
            pass

    def set_backdrop(self, color):
        self.configure(bg=color)


# ---------------------------------------------------------------- containers

class Card(tk.Canvas):
    """Cut-corner surface that wraps a normal frame (`card.inner`) and grows with its contents.
    stripe: a colored band on the left edge (the 'last used' and status look)."""

    def __init__(self, parent, fill=T.CARD, radius=None, padx=20, pady=16, stripe=None, cut=None):
        super().__init__(parent, bg=parent.cget("bg"), highlightthickness=0, bd=0, height=T.px(60))
        self.fill = fill.lower()
        self.cut = T.px(cut if cut is not None else T.CUT_CARD)
        self.padx, self.pady = T.px(padx), T.px(pady)
        self.stripe = (stripe, T.px(3)) if stripe else None
        self._shape = Shape(self)
        self.inner = tk.Frame(self, bg=fill)
        self._win = self.create_window(self.padx, self.pady, window=self.inner, anchor="nw")
        self._job = None
        self._hover_on = False
        self._intro = False
        self.outline = None
        self.bind("<Configure>", self._on_resize)
        self.inner.bind("<Configure>", self._on_inner)

    def _on_resize(self, event):
        self.itemconfigure(self._win, width=max(10, event.width - 2 * self.padx))
        self._schedule()

    def _on_inner(self, event):
        height = event.height + 2 * self.pady
        if int(float(self.cget("height"))) != height:
            self.configure(height=height)
        self._schedule()

    def _schedule(self):
        if self._job is not None:
            self.after_cancel(self._job)
        self._job = self.after(16, self._draw)

    def _draw(self, fade=1.0):
        self._job = None
        try:
            w, h = self.winfo_width(), self.winfo_height()
            if w > 4 and h > 4:
                back = self.cget("bg")
                stripe = self.stripe and (T.blend(back, self.stripe[0], fade), self.stripe[1])
                self._shape.draw(w, h, self.cut, self.fill, self.outline, max(1, T.px(2)) if self.outline else 0,
                                 stripe=stripe)
        except tk.TclError:
            pass

    # -- while a card is being dragged, no card reacts to hover (the pointer crosses all of them)
    frozen = False

    def set_held(self, held):
        """The look of a card you're dragging: lighter, with a red outline."""
        self.outline = T.RED if held else None
        self.set_fill(self._hover_color if held else self._base)

    # -- color changes (hover highlight, intro): the card and its children's backgrounds move together
    def set_fill(self, color, fade=1.0):
        color = color.lower()
        old, self.fill = self.fill, color
        self.inner.configure(bg=color)
        self._recolor(self.inner, old, color)
        self._draw(fade)

    def _recolor(self, widget, old, new):
        for child in widget.winfo_children():
            if hasattr(child, "set_backdrop"):
                child.set_backdrop(new)
            else:
                try:
                    if str(child.cget("bg")).lower() == old:
                        child.configure(bg=new)
                except tk.TclError:
                    pass
            self._recolor(child, old, new)

    def _fade_fill(self, color, duration=160):
        start = self.fill

        def step(t):
            self.set_fill(color if t >= 1.0 else T.blend(start, color, _steps(t, 5)))

        animate(self, "fill", duration, step)

    def track_hover(self, base=T.CARD, hover=T.CARD_HOVER):
        self._base, self._hover_color = base, hover

        def enter(_e=None):
            if not self._hover_on and not self._intro and not Card.frozen:
                self._hover_on = True
                self._fade_fill(self._hover_color)

        def leave(_e=None):
            self.after(30, check)

        def check():
            try:
                if not self.winfo_exists():
                    return
                x, y = self.winfo_pointerxy()
                under = self.winfo_containing(x, y)
                name = str(under) if under is not None else ""
                inside = name == str(self) or name.startswith(str(self) + ".")
                if not inside and self._hover_on and not Card.frozen:
                    self._hover_on = False
                    self._fade_fill(self._base, 220)
            except (tk.TclError, KeyError):
                return

        def bind_all(widget):
            widget.bind("<Enter>", enter, add="+")
            widget.bind("<Leave>", leave, add="+")
            for child in widget.winfo_children():
                bind_all(child)

        bind_all(self)

    def bind_click(self, command, skip=()):
        """Make the card and everything in it (except `skip` widgets) clickable."""
        def bind_all(widget):
            if widget not in skip:
                try:
                    widget.configure(cursor="hand2")
                except tk.TclError:
                    pass
                widget.bind("<Button-1>", lambda e: command(), add="+")
                for child in widget.winfo_children():
                    bind_all(child)
        bind_all(self)

    def intro(self, delay_ms=0, rise=18, duration=420):
        """Sweep in once: the card rises a few pixels while it and everything on it fade up from the backdrop."""
        if not MOTION:
            return
        back, final_fill = self.cget("bg").lower(), self.fill
        labels, fading = [], []

        def collect(widget):
            for child in widget.winfo_children():
                if hasattr(child, "set_fade"):
                    fading.append(child)
                elif isinstance(child, tk.Label):
                    labels.append((child, child.cget("fg")))
                collect(child)

        collect(self.inner)
        info = self.pack_info()
        pady = info.get("pady", 0)
        top, bottom = (pady if isinstance(pady, (tuple, list)) else (pady, pady))
        top, bottom = int(top), int(bottom)
        lift = T.px(rise)
        self._intro = True

        def show(f):
            self.set_fill(T.blend(back, final_fill, f) if f < 1.0 else final_fill, fade=f)
            for label, fg in labels:
                label.configure(fg=T.blend(self.fill, fg, f) if f < 1.0 else fg)
            for widget in fading:
                widget.set_fade(f)

        def step(t):
            e = T.ease_out(t)
            self.pack_configure(pady=(top + int(lift * (1 - e)), bottom))
            show(1.0 if t >= 1.0 else round(e * 8) / 8)

        def done():
            self._intro = False

        show(0.0)
        self.pack_configure(pady=(top + lift, bottom))
        self.after(delay_ms, lambda: animate(self, "intro", duration, step, done))


class Field(tk.Canvas):
    """Cut-corner text box. Use .get() / .focus_set(); the real Entry is .entry."""

    def __init__(self, parent, value="", secret=False, size=11, center=False, placeholder=""):
        h = max(T.px(42), T.font(size).metrics("linespace") + T.px(18))
        self._placeholder, self._showing_hint = ("" if secret else placeholder), False
        super().__init__(parent, height=h, bg=parent.cget("bg"), highlightthickness=0, bd=0)
        self._shape, self._focus, self._height_px = Shape(self), False, h
        self.entry = tk.Entry(self, bd=0, relief="flat", bg=T.FIELD, fg=T.FG, insertbackground=T.RED,
                              font=T.font(size), show="●" if secret else "", highlightthickness=0,
                              justify="center" if center else "left")
        self.entry.insert(0, value)
        self._pad = T.px(14)
        self._win = self.create_window(self._pad, h // 2, window=self.entry, anchor="w")
        self.bind("<Configure>", self._on_resize)
        self.bind("<Button-1>", lambda e: self.entry.focus_set())
        self.entry.bind("<FocusIn>", lambda e: self._set_focus(True))
        self.entry.bind("<FocusOut>", lambda e: self._set_focus(False))
        self._hint()

    def _hint(self):
        """Grey hint text while the box is empty and not being typed in."""
        if self._placeholder and not self._focus and not self.entry.get():
            self._showing_hint = True
            self.entry.configure(fg=T.FAINT)
            self.entry.insert(0, self._placeholder)

    def _on_resize(self, event):
        self.itemconfigure(self._win, width=max(10, event.width - 2 * self._pad))
        self._draw()

    def _set_focus(self, focused):
        self._focus = focused
        if focused and self._showing_hint:
            self._showing_hint = False
            self.entry.delete(0, "end")
            self.entry.configure(fg=T.FG)
        elif not focused:
            self._hint()
        self._draw()

    def _draw(self):
        w = self.winfo_width()
        if w > 4:
            self._shape.draw(w, self._height_px, T.px(T.CUT_BUTTON), T.FIELD,
                             T.RED if self._focus else T.LINE, max(1, T.px(1)),
                             stripe=(T.RED, T.px(3)) if self._focus else None)

    def get(self):
        return "" if self._showing_hint else self.entry.get()

    def clear(self):
        self._showing_hint = False
        self.entry.delete(0, "end")
        self.entry.configure(fg=T.FG)
        self._hint()

    def focus_set(self):
        self.entry.focus_set()

    def set_backdrop(self, color):
        self.configure(bg=color)


# ---------------------------------------------------------------- sheets (dialogs)

class Sheet(tk.Toplevel):
    """A modal dialog in the app's style: title, short text, fields, and a row of buttons."""
    STAY = object()   # return from a primary-button callback to keep the sheet open

    def __init__(self, app, title, width=460, on_top=False):
        super().__init__(app)
        self.withdraw()
        self.app = app
        self.title(title)
        self.configure(bg=T.SHEET)
        self.resizable(False, False)
        self.transient(app)
        if on_top:
            self.attributes("-topmost", True)
        self.result = None
        self._width = T.px(width)
        self._pad = T.px(28)
        self._wrap = self._width - 2 * self._pad
        self._on_primary, self._primary, self._err, self._row, self._first = None, None, None, None, None
        tk.Frame(self, bg=T.RED, height=max(2, T.px(2))).pack(fill="x", side="top")   # HUD edge
        self.body = tk.Frame(self, bg=T.SHEET)
        self.body.pack(fill="both", expand=True, padx=self._pad, pady=(T.px(24), T.px(24)))
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda e: self.close())
        self.bind("<Return>", lambda e: self._go())

    # -- content
    def heading(self, text):
        tk.Label(self.body, text=text, font=T.font(17, display=True), fg=T.FG, bg=T.SHEET, anchor="w",
                 justify="left", wraplength=self._wrap).pack(anchor="w", pady=(0, T.px(6)))

    def text(self, text, small=False, color=None):
        label = tk.Label(self.body, text=text, font=T.font(9 if small else 10), fg=color or T.MUTED, bg=T.SHEET,
                         anchor="w", justify="left", wraplength=self._wrap)
        label.pack(anchor="w", pady=(0, T.px(8)))
        return label

    def field(self, caption, value="", secret=False, size=11, center=False):
        tk.Label(self.body, text=caption, font=T.font(9), fg=T.MUTED, bg=T.SHEET, anchor="w").pack(
            anchor="w", pady=(T.px(8), T.px(4)))
        f = Field(self.body, value, secret, size, center)
        f.pack(fill="x")
        self._first = self._first or f
        return f

    def check(self, text, variable):
        box = tk.Checkbutton(self.body, text=text, variable=variable, bg=T.SHEET, fg=T.FG, selectcolor=T.FIELD,
                             activebackground=T.SHEET, activeforeground=T.FG, bd=0, highlightthickness=0,
                             font=T.font(10), anchor="w", justify="left", wraplength=self._wrap)
        box.pack(anchor="w", pady=(T.px(12), 0))
        return box

    def rows(self, items):
        """Simple two-column list: [(left text, right text, right color)]."""
        for left, right, color in items:
            row = tk.Frame(self.body, bg=T.SHEET)
            row.pack(fill="x", pady=T.px(4))
            tk.Label(row, text=left, font=T.font(11, display=True), fg=T.FG, bg=T.SHEET, anchor="w").pack(side="left")
            tk.Label(row, text=right, font=T.font(10), fg=color or T.MUTED, bg=T.SHEET, anchor="e").pack(side="right")

    def buttons(self, primary, on_primary=None, secondary="Cancel", left=None, danger=False, secondary_value=None):
        """Right-aligned button row. `left` = (text, callback) for an optional extra action."""
        self._err = tk.Label(self.body, text="", font=T.font(10), fg=T.RED, bg=T.SHEET, anchor="w",
                             justify="left", wraplength=self._wrap)
        self._row = tk.Frame(self.body, bg=T.SHEET)
        self._row.pack(fill="x", pady=(T.px(20), 0))
        self._on_primary = on_primary
        self._primary = Pill(self._row, primary, self._go, kind="primary", height=36, padx=22)
        self._primary.pack(side="right")
        if secondary:
            Pill(self._row, secondary, lambda: self.close(secondary_value), kind="plain", height=36, padx=20).pack(
                side="right", padx=(0, T.px(10)))
        if left:
            if len(left[0]) > 18:   # long label: its own row underneath, so nothing gets squeezed
                extra = tk.Frame(self.body, bg=T.SHEET)
                extra.pack(fill="x", pady=(T.px(10), 0))
                Pill(extra, left[0], left[1], kind="ghost", height=32, padx=4, fg=T.MUTED, display=False).pack(
                    side="left")
            else:
                Pill(self._row, left[0], left[1], kind="ghost", height=36, padx=14).pack(side="left")

    # -- behavior
    def show_error(self, message):
        self._err.configure(text=message)
        if not self._err.winfo_ismapped():
            self._err.pack(anchor="w", pady=(T.px(10), 0), before=self._row)
        self._fit()

    def _go(self):
        if self._primary is None:
            return
        try:
            value = self._on_primary() if self._on_primary else True
        except UserError as e:
            self.show_error(str(e))
            return
        if value is Sheet.STAY:
            return
        self.close(True if value is None else value)

    def close(self, value=None):
        self.result = value
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()

    def _fit(self):
        self.update_idletasks()
        self.geometry(f"{self._width}x{self.winfo_reqheight()}")

    def show(self):
        self.update_idletasks()
        w, h = self._width, self.winfo_reqheight()
        x = self.app.winfo_rootx() + (self.app.winfo_width() - w) // 2
        y = self.app.winfo_rooty() + max(T.px(40), (self.app.winfo_height() - h) // 3)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        x, y = max(0, min(x, sw - w)), max(0, min(y, sh - h - T.px(40)))
        self.geometry(f"{w}x{h}+{x}+{y + T.px(12)}")
        style_titlebar(self)
        try:
            self.attributes("-alpha", 0.0 if MOTION else 1.0)
        except tk.TclError:
            pass
        self.deiconify()

        def step(t):   # fade in while settling 12px upward
            e = T.ease_out(t)
            self.attributes("-alpha", e)
            self.geometry(f"+{x}+{y + int(T.px(12) * (1 - e))}")

        animate(self, "open", 180, step)
        try:
            self.grab_set()
        except tk.TclError:
            pass
        self.focus_force()
        if self._first is not None:
            self._first.focus_set()
        self.wait_window(self)
        return self.result


# ---------------------------------------------------------------- popup menu

class PopupMenu(tk.Toplevel):
    """Cut-corner menu that opens under a button. items: (label, callback[, 'danger']) or None for a divider."""
    KEY = "#010203"  # this color is made see-through so the cut corners are truly cut

    def __init__(self, app, anchor, items, width=240):
        super().__init__(app)
        self.withdraw()
        self.app = app
        self.overrideredirect(True)
        self.configure(bg=self.KEY)
        try:
            self.attributes("-topmost", True)
            self.attributes("-transparentcolor", self.KEY)
        except tk.TclError:
            pass
        w, row_h, sep_h, pad = T.px(width), T.px(34), T.px(11), T.px(8)
        h = 2 * pad + sum(sep_h if item is None else row_h for item in items)
        canvas = tk.Canvas(self, width=w, height=h, bg=self.KEY, highlightthickness=0, bd=0)
        canvas.pack()
        self._shape = Shape(canvas)
        self._shape.draw(w, h, T.px(T.CUT_CARD), T.MENU, T.LINE, 1, stripe=(T.RED, T.px(2)))
        y = pad
        for item in items:
            if item is None:
                line = tk.Frame(canvas, bg=T.LINE)
                canvas.create_window(T.px(16), y + sep_h // 2, window=line, anchor="w",
                                     width=w - T.px(32), height=1)
                y += sep_h
                continue
            label, callback = item[0], item[1]
            danger = len(item) > 2 and item[2] == "danger"
            row = Pill(canvas, label, lambda cb=callback: self._pick(cb), kind="ghost", height=34,
                       width=width - 16, align="w", radius=9, fg=T.RED if danger else T.FG, bg=T.MENU,
                       display=False)
            canvas.create_window(pad, y, window=row, anchor="nw")
            y += row_h
        self.update_idletasks()
        x = anchor.winfo_rootx() + anchor.winfo_width() - w
        top = anchor.winfo_rooty() + anchor.winfo_height() + T.px(6)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        x = max(8, min(x, sw - w - 8))
        if top + h > sh - 8:
            top = max(8, anchor.winfo_rooty() - h - T.px(6))
        self.geometry(f"{w}x{h}+{x}+{top}")
        self.anchor = anchor
        self._armed = False
        try:
            self.attributes("-alpha", 0.0 if MOTION else 1.0)
        except tk.TclError:
            pass
        self.deiconify()
        self.lift()
        animate(self, "open", 120, lambda t: self.attributes("-alpha", T.ease_out(t)))
        self.after(40, self._take_focus)
        self.after(250, self._arm)
        self.bind("<Escape>", lambda e: self.dismiss())
        self.bind("<FocusOut>", self._lost_focus)
        app.open_menu_ref = self           # the app closes us on any click outside, or when the window moves

    def _take_focus(self):
        try:
            self.focus_force()
        except tk.TclError:
            pass

    def _arm(self):
        self._armed = True

    def _lost_focus(self, _event):
        if self._armed:
            self.after_idle(self.dismiss)

    def contains(self, widget):
        name = str(widget)
        return name == str(self) or name.startswith(str(self) + ".")

    def dismiss(self):
        try:
            if getattr(self.app, "open_menu_ref", None) is self:
                self.app.open_menu_ref = None
                self.app.menu_closed_at = (self.anchor, time.monotonic())
            self.destroy()
        except tk.TclError:
            pass

    _safe_destroy = dismiss

    def _pick(self, callback):
        self._safe_destroy()
        self.app.after(10, callback)
