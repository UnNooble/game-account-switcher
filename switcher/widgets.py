"""Custom widgets for the rounded, Apple-like look (Tkinter has none of these built in).

Shapes are drawn as smooth, supersampled images with Pillow; if Pillow is missing they fall back to
plain canvas polygons, so the app still works (just with rougher corners).
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


# ---------------------------------------------------------------- shapes

class Shape:
    """A rounded rectangle living on a canvas. Re-drawn only when something about it changes."""
    SS = 4  # supersampling factor for smooth edges

    def __init__(self, canvas, back=True):
        self.c, self.back = canvas, back
        self.item = None
        self.img = None
        self.key = None

    def hide(self):
        if self.item is not None:
            self.c.itemconfigure(self.item, state="hidden")

    def draw(self, w, h, r, fill, outline=None, ow=0):
        w, h = max(int(w), 2), max(int(h), 2)
        r = max(0, min(int(r), w // 2, h // 2))
        if self.item is not None:
            self.c.itemconfigure(self.item, state="normal")
        key = (w, h, r, fill, outline, ow)
        if key == self.key:
            return
        self.key = key
        if HAVE_PIL:
            ss = self.SS
            im = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
            ImageDraw.Draw(im).rounded_rectangle(
                [0, 0, w * ss - 1, h * ss - 1], radius=r * ss, fill=fill,
                outline=outline if ow else None, width=ow * ss if ow else 0)
            self.img = ImageTk.PhotoImage(im.resize((w, h), Image.LANCZOS), master=self.c)
            if self.item is None:
                self.item = self.c.create_image(0, 0, anchor="nw", image=self.img)
                self._layer()
            else:
                self.c.itemconfigure(self.item, image=self.img)
        else:
            x2, y2 = w - 1, h - 1
            pts = [r, 0, x2 - r, 0, x2, 0, x2, r, x2, y2 - r, x2, y2, x2 - r, y2,
                   r, y2, 0, y2, 0, y2 - r, 0, r, 0, 0]
            if self.item is None:
                self.item = self.c.create_polygon(pts, smooth=True, fill=fill, outline=outline or fill)
                self._layer()
            else:
                self.c.coords(self.item, *pts)
                self.c.itemconfigure(self.item, fill=fill, outline=outline or fill)

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
    """Fully rounded button. kind: primary | tint | plain | ghost."""

    def __init__(self, parent, text, command=None, kind="plain", height=34, padx=18, square=False,
                 width=None, align="center", radius=None, fg=None, bg=None):
        self.kind, self.command, self.align = kind, command, align
        self._radius, self._fg_override = radius, fg
        self._label, self._enabled, self._mode, self._text_item = text, True, "normal", None
        self._font = T.font(10, True)
        self._pad = T.px(padx)
        self._height_px = T.px(height)
        self._square = square
        self._fixed_width = T.px(width) if width else None
        self._width_px = self._measure()
        super().__init__(parent, width=self._width_px, height=self._height_px,
                         bg=bg or parent.cget("bg"), highlightthickness=0, bd=0, cursor="hand2")
        self._shape = Shape(self)
        self.bind("<Enter>", lambda e: self._set_mode("hover"))
        self.bind("<Leave>", lambda e: self._set_mode("normal"))
        self.bind("<ButtonPress-1>", lambda e: self._set_mode("press"))
        self.bind("<ButtonRelease-1>", self._released)
        self._redraw()

    def _measure(self):
        if self._square:
            return self._height_px
        if self._fixed_width:
            return self._fixed_width
        return self._font.measure(self._label) + 2 * self._pad

    def _palette(self):
        """fill, hover fill, pressed fill, text, hover text"""
        if self.kind == "primary":
            return T.RED, T.RED_HOVER, T.RED_PRESS, "#ffffff", "#ffffff"
        if self.kind == "tint":
            return T.RED_TINT, T.RED, T.RED_PRESS, T.RED, "#ffffff"
        if self.kind == "ghost":
            return self.cget("bg"), T.CHIP, T.CHIP_PRESS, self._fg_override or T.MUTED, self._fg_override or T.FG
        return T.CHIP, T.CHIP_HOVER, T.CHIP_PRESS, self._fg_override or T.FG, self._fg_override or T.FG

    def _redraw(self):
        fill, hover, press, fg, hover_fg = self._palette()
        if not self._enabled:
            color = self.cget("bg") if self.kind == "ghost" else T.CHIP_OFF
            text_color = T.FAINT
        elif self._mode == "press":
            color, text_color = press, hover_fg
        elif self._mode == "hover":
            color, text_color = hover, hover_fg
        else:
            color, text_color = fill, fg
        w, h = self._width_px, self._height_px
        self._shape.draw(w, h, self._radius and T.px(self._radius) or h // 2, color)
        x, anchor = (self._pad, "w") if self.align == "w" else (w // 2, "center")
        if self._text_item is None:
            self._text_item = self.create_text(x, h // 2, text=self._label, fill=text_color,
                                               font=self._font, anchor=anchor)
        else:
            self.coords(self._text_item, x, h // 2)
            self.itemconfigure(self._text_item, text=self._label, fill=text_color, anchor=anchor)

    def _set_mode(self, mode):
        if self._enabled and mode != self._mode:
            self._mode = mode
            self._redraw()

    def _released(self, event):
        if not self._enabled:
            return
        inside = 0 <= event.x < self._width_px and 0 <= event.y < self._height_px
        self._set_mode("hover" if inside else "normal")
        if inside and self.command:
            self.command()

    # -- public helpers
    def set_enabled(self, enabled):
        self._enabled = bool(enabled)
        self._mode = "normal"
        self.configure(cursor="hand2" if enabled else "arrow")
        self._redraw()

    def set_kind(self, kind):
        self.kind = kind
        self._redraw()

    def set_text(self, text):
        self._label = text
        self._width_px = self._measure()
        self.configure(width=self._width_px)
        self._redraw()

    def set_backdrop(self, color):
        """The color behind the rounded corners (the parent's background) changed."""
        self.configure(bg=color)
        self._redraw()


class Avatar(tk.Canvas):
    """Round badge with an initial, like a contact photo."""

    def __init__(self, parent, letter, fill, size=44, fg=None):
        s = T.px(size)
        super().__init__(parent, width=s, height=s, bg=parent.cget("bg"), highlightthickness=0, bd=0)
        Shape(self).draw(s, s, s // 2, fill)
        self.create_text(s // 2, s // 2, text=letter, fill=fg or T.FG, font=T.font(14, True))

    def set_backdrop(self, color):
        self.configure(bg=color)


class Progress(tk.Canvas):
    """Slim rounded progress bar that glides to its new value."""

    def __init__(self, parent, height=6):
        super().__init__(parent, height=T.px(height), bg=parent.cget("bg"), highlightthickness=0, bd=0)
        self._track, self._bar = Shape(self), Shape(self, back=False)
        self.value, self._target, self.color, self._job = 0.0, 0.0, T.RED, None
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
        self.value = self._target if abs(delta) < 0.004 else self.value + delta * 0.3
        self._draw()
        if self.value != self._target:
            self._job = self.after(30, self._step)

    def _draw(self):
        try:
            w, h = self.winfo_width(), self.winfo_height()
            if w < 4 or h < 2:
                return
            self._track.draw(w, h, h // 2, T.CHIP)
            if self.value <= 0.001:
                self._bar.hide()
            else:
                self._bar.draw(max(h, int(w * self.value)), h, h // 2, self.color)
        except tk.TclError:
            pass

    def set_backdrop(self, color):
        self.configure(bg=color)


# ---------------------------------------------------------------- containers

class Card(tk.Canvas):
    """Rounded surface that wraps a normal frame (`card.inner`) and grows with its contents."""

    def __init__(self, parent, fill=T.CARD, radius=20, padx=20, pady=16):
        super().__init__(parent, bg=parent.cget("bg"), highlightthickness=0, bd=0, height=T.px(60))
        self.fill, self.radius = fill.lower(), T.px(radius)
        self.padx, self.pady = T.px(padx), T.px(pady)
        self._shape = Shape(self)
        self.inner = tk.Frame(self, bg=fill)
        self._win = self.create_window(self.padx, self.pady, window=self.inner, anchor="nw")
        self._job = None
        self._hover_on = False
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

    def _draw(self):
        self._job = None
        try:
            w, h = self.winfo_width(), self.winfo_height()
            if w > 4 and h > 4:
                self._shape.draw(w, h, self.radius, self.fill)
        except tk.TclError:
            pass

    # -- hover highlight: the whole card changes shade while the pointer is anywhere inside it
    def set_fill(self, color):
        color = color.lower()
        old, self.fill = self.fill, color
        self.inner.configure(bg=color)
        self._recolor(self.inner, old, color)
        self._draw()

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

    def track_hover(self, base=T.CARD, hover=T.CARD_HOVER):
        self._base, self._hover_color = base, hover

        def enter(_e=None):
            if not self._hover_on:
                self._hover_on = True
                self.set_fill(self._hover_color)

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
                if not inside and self._hover_on:
                    self._hover_on = False
                    self.set_fill(self._base)
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


class Field(tk.Canvas):
    """Rounded text box. Use .get() / .focus_set(); the real Entry is .entry."""

    def __init__(self, parent, value="", secret=False, size=11, center=False):
        h = max(T.px(42), T.font(size).metrics("linespace") + T.px(18))
        super().__init__(parent, height=h, bg=parent.cget("bg"), highlightthickness=0, bd=0)
        self._shape, self._focus, self._height_px = Shape(self), False, h
        self.entry = tk.Entry(self, bd=0, relief="flat", bg=T.FIELD, fg=T.FG, insertbackground=T.FG,
                              font=T.font(size), show="●" if secret else "", highlightthickness=0,
                              justify="center" if center else "left")
        self.entry.insert(0, value)
        self._pad = T.px(14)
        self._win = self.create_window(self._pad, h // 2, window=self.entry, anchor="w")
        self.bind("<Configure>", self._on_resize)
        self.bind("<Button-1>", lambda e: self.entry.focus_set())
        self.entry.bind("<FocusIn>", lambda e: self._set_focus(True))
        self.entry.bind("<FocusOut>", lambda e: self._set_focus(False))

    def _on_resize(self, event):
        self.itemconfigure(self._win, width=max(10, event.width - 2 * self._pad))
        self._draw()

    def _set_focus(self, focused):
        self._focus = focused
        self._draw()

    def _draw(self):
        w = self.winfo_width()
        if w > 4:
            self._shape.draw(w, self._height_px, T.px(12), T.FIELD,
                             T.RED if self._focus else T.LINE, max(1, T.px(1)) + (1 if self._focus else 0))

    def get(self):
        return self.entry.get()

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
        self.body = tk.Frame(self, bg=T.SHEET)
        self.body.pack(fill="both", expand=True, padx=self._pad, pady=(T.px(26), T.px(24)))
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda e: self.close())
        self.bind("<Return>", lambda e: self._go())

    # -- content
    def heading(self, text):
        tk.Label(self.body, text=text, font=T.font(17, True), fg=T.FG, bg=T.SHEET, anchor="w",
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
            tk.Label(row, text=left, font=T.font(11, True), fg=T.FG, bg=T.SHEET, anchor="w").pack(side="left")
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
                Pill(extra, left[0], left[1], kind="ghost", height=32, padx=4, fg=T.MUTED).pack(side="left")
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
        self.geometry(f"{w}x{h}+{x}+{y}")
        style_titlebar(self)
        self.deiconify()
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
    """Soft rounded menu that opens under a button. items: (label, callback[, 'danger']) or None for a divider."""
    KEY = "#010203"  # this color is made see-through so the corners are truly round

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
        self._shape.draw(w, h, T.px(14), T.MENU, T.LINE, 1)
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
                       width=width - 16, align="w", radius=9, fg=T.RED if danger else T.FG, bg=T.MENU)
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
        self.deiconify()
        self.lift()
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
