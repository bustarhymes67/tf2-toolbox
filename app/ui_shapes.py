"""Smooth rounded shapes for Tkinter, which only draws square boxes: rounded rectangles drawn
as images with anti-aliased edges (blended with the colour behind them), pills that keep their
text on such a shape, rounded cards, and Windows 11's own rounded window corners."""

import ctypes
import tkinter as tk
import tkinter.font as tkfont

SAMPLES = 4         # samples per pixel side for the anti-aliased corners
_images = {}        # (Tk window, w, h, radius, fill, under) -> PhotoImage, kept so Tk doesn't lose them
_IMAGE_LIMIT = 400  # card sizes change while resizing: the oldest are dropped past this


def _rgb(color):
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def square_image(widget, w, h, fill, outline=None, brackets=None):
    """A w x h PhotoImage of a square box in fill with a 1px outline, and short corner brackets in
    another colour on its four corners (the Tactical HUD look)."""
    key = (id(widget.tk), "square", w, h, fill, outline, brackets)
    if key in _images:
        return _images[key]
    edge = outline or fill
    arm = min(8, w // 3, h // 3)  # how long each bracket arm is

    def pixel(x, y):
        border = x in (0, w - 1) or y in (0, h - 1)
        if brackets and border and ((x < arm or x >= w - arm) and y in (0, h - 1)
                                    or (y < arm or y >= h - arm) and x in (0, w - 1)):
            return brackets
        return edge if border else fill

    rows = []
    for y in range(h):
        if 0 < y < h - 1 and (not brackets or arm <= y < h - arm):
            rows.append("{" + " ".join([edge] + [fill] * (w - 2) + [edge]) + "}")
        else:
            rows.append("{" + " ".join(pixel(x, y) for x in range(w)) + "}")
    image = tk.PhotoImage(master=widget, width=w, height=h)
    image.put(" ".join(rows))
    if len(_images) >= _IMAGE_LIMIT:
        _images.pop(next(iter(_images)))
    _images[key] = image
    return image


def rounded_image(widget, w, h, radius, fill, under):
    """A w x h PhotoImage of a rounded rectangle in fill, its corners blended into under."""
    key = (id(widget.tk), w, h, radius, fill, under)  # images belong to one Tk window and die with it
    if key in _images:
        return _images[key]
    radius = max(0, min(radius, w // 2, h // 2))
    f, u = _rgb(fill), _rgb(under)
    solid = "#%02x%02x%02x" % f

    def coverage(x, y):
        """How much of pixel (x, y) the shape covers, 0 to 1, from SAMPLES x SAMPLES points."""
        inside = 0
        for i in range(SAMPLES):
            px = x + (i + 0.5) / SAMPLES
            cx = min(max(px, radius), w - radius)
            for j in range(SAMPLES):
                py = y + (j + 0.5) / SAMPLES
                cy = min(max(py, radius), h - radius)
                inside += (px - cx) ** 2 + (py - cy) ** 2 <= radius * radius
        return inside / SAMPLES ** 2

    def corner_row(y):
        cells = []
        for x in range(w):
            if radius <= x < w - radius:
                cells.append(solid)
                continue
            c = coverage(x, y)
            cells.append("#%02x%02x%02x" % tuple(round(a * c + b * (1 - c)) for a, b in zip(f, u)))
        return "{" + " ".join(cells) + "}"

    middle = "{" + " ".join([solid] * w) + "}"
    rows = [corner_row(y) if y < radius or y >= h - radius else middle for y in range(h)]
    image = tk.PhotoImage(master=widget, width=w, height=h)
    image.put(" ".join(rows))
    if len(_images) >= _IMAGE_LIMIT:
        _images.pop(next(iter(_images)))
    _images[key] = image
    return image


class Pill(tk.Label):
    """Text on a square box with a 1px outline that fits the text (radius is kept for callers
    from the rounded design, and ignored)."""

    def __init__(self, parent, text, font, fg, fill, under=None, padx=12, pady=5, radius=0, outline=None, **kw):
        self._font = tkfont.Font(root=parent, font=font)
        self._fill, self._under = fill, under or parent.cget("bg")
        self._padx, self._pady, self._radius = padx, pady, radius
        self._outline = outline
        super().__init__(parent, text=text, font=font, fg=fg, bg=self._under, compound="center", bd=0,
                         padx=0, pady=0, highlightthickness=0, **kw)
        self._redraw()

    def _redraw(self):
        text = self.cget("text")
        w = max(self._font.measure(text) + 2 * self._padx, 2 * self._radius)
        h = self._font.metrics("linespace") + 2 * self._pady
        tk.Label.configure(self, image=square_image(self, w, h, self._fill, self._outline))

    def configure(self, cnf=None, **kw):
        result = tk.Label.configure(self, cnf, **kw)
        if "text" in kw or (cnf and "text" in cnf):
            self._redraw()
        return result

    config = configure

    def set_fill(self, fill, outline=None):
        if fill != self._fill or outline != self._outline:
            self._fill, self._outline = fill, outline
            self._redraw()

    def set_under(self, under):
        """The colour behind the pill changed (a card lighting up under the mouse)."""
        if under != self._under:
            self._under = under
            tk.Label.configure(self, bg=under)
            self._redraw()


def round_card(frame, fill, under, radius=0, outline=None, brackets=None):
    """Gives frame its card look: a background image of a square box with a 1px outline and
    corner brackets under its contents, redrawn when its size changes. Its contents should use
    fill as their bg. frame.set_card_fill(colour) changes the fill (for hover)."""
    from settings import ACCENT, LINE  # here: settings imports nothing from this file
    outline, brackets = outline or LINE, brackets or ACCENT
    frame.configure(bg=under)  # the corners show what's under the card
    back = tk.Label(frame, bd=0, bg=under, highlightthickness=0)
    back.place(x=0, y=0, relwidth=1, relheight=1)
    back.lower()
    state = {"fill": fill, "drawn": None}

    def redraw(e=None):
        w, h = frame.winfo_width(), frame.winfo_height()
        if w < 4 or h < 4 or state["drawn"] == (w, h, state["fill"]):
            return
        state["drawn"] = (w, h, state["fill"])
        back.configure(image=square_image(frame, w, h, state["fill"], outline, brackets))

    def set_card_fill(new):
        state["fill"] = new
        redraw()

    frame.bind("<Configure>", redraw, add="+")
    frame.set_card_fill = set_card_fill
    for event in ("<Button-1>", "<Enter>", "<Leave>"):  # the background passes these on to the card
        back.bind(event, lambda e, event=event: frame.event_generate(event, x=e.x, y=e.y))
    return frame


def round_window_corners(window):
    """Square window corners (Windows 11 would round them). Nothing happens on older Windows,
    which doesn't round them anyway."""
    try:
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()
        DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND = 33, ctypes.c_int(1)  # 1: do not round
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
                                                   ctypes.byref(DWMWCP_ROUND), ctypes.sizeof(DWMWCP_ROUND))
    except (AttributeError, OSError):
        pass
