"""What you see: the colours, the player table, the buttons, the alerts at the top of the screen and
the tokens window. ScreensMixin is the part of the App that draws them and handles clicks and dragging."""

import ctypes
import time
from collections import Counter
import re
import tkinter as tk
import webbrowser
from tf2_translator import set_click_through, translator_health

from settings import (ACCENT, BAD, BAR_BG, BG, BORDER, BUTTON_BG, BUTTON_HOVER_BG, CARD_BG, CARD_HOVER_BG, DANGER_BG,
                      DANGER_FG, DANGER_HOVER_BG, FAINT, FONT_LABEL, GOOD, KEY_COLOR, LINE, LINK_BG, LINK_FG,
                      LINK_HOVER_BG, MUTED, ON_BG, ON_FG, ROW_ALT_BG, ROW_HOVER_BG, SELECTED_BG, SEVERITY_FG,
                      TEAM_ACCENT, TEAM_FG, TEXT, TEXT2, WAITING, mono_family, save_config)
from demo_check import meaning_text
from game_log import CLASS_MAX_HEALTH, weapon_name
from player_flags import explain_flags, profile_flags, crit_flag, fmt_age, fmt_hours, headshot_flag, lobby_friends, profile_text
from ai import token_table
from ui_shapes import Pill, round_card
from info_commands import INFO_COMMANDS
from demo_check import copy_lines, count_checks, detection_details

def on_a_screen(x, y):
    """True if a monitor that's connected now shows the point x, y (a window's
    top-left corner): one saved on an unplugged monitor isn't anywhere to be seen."""
    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    MONITOR_DEFAULTTONULL = 0
    return bool(ctypes.windll.user32.MonitorFromPoint(POINT(x, y), MONITOR_DEFAULTTONULL))
# "Mark" is a thin stripe in the colour of a player's worst flag; teams are the groups' headers.
COLUMNS = ("Mark", "Ctry", "Class", "Player", "HP", "K/D", "Streak", "Duel", "HS",
           "Crit", "TF2", "Age", "Flags", "Profile")
HEADERS = {"Mark": "", "Ctry": "", "TF2": "Hours", "HS": "HS %", "Crit": "Crit %"}  # the flag column needs no title
# Columns left out while nobody shown has anything in them (no Steam key, no duels yet...).
HIDEABLE_COLUMNS = {"Ctry", "Class", "HP", "K/D", "Streak", "Duel", "HS", "Crit", "TF2", "Age",
                    "Flags", "Profile"}
BLANK_CELLS = {"", "…", "?"}
PAGES = ("Players", "Cheat check", "Duels", "Chat", "Status", "Help")
# What anyone can type in chat while duels are on, for the Duels page.
DUEL_COMMANDS = (("!duel <name>", "Challenge a player on the other team. Part of a name works."),
                 ("!duel all", "You against their whole team."),
                 ("!duel <name>, <name>", "Make two other players duel each other."),
                 ("!duel all, all", "Everyone against everyone."),
                 ("!duel scores", "The score of every running duel."),
                 ("!duel stop", "End your own duels. !duel stopall ends everyone's."),
                 ("!duel reset", "Scores back to 0-0."))
# The Help page: what anyone can type in chat, besides the info commands and the duel commands.
SPEAK_COMMANDS = (("!speak <language> <message>", "Says the message in that language in chat. Example: !speak russian hello"),
                  ("", "The language can be its name (russian), its first 3 letters (rus) or its code (ru)."))
HEAVY_COMMANDS = (("(any chat line)", "While HoovyGPT is on, it answers other players as the Heavy."),
                  ("!badbot", "Mutes HoovyGPT. Who can do this: the Duels page."),
                  ("!goodbot", "Unmutes HoovyGPT."))
# What each Chat page card posts, played in a small TF2-style chat box after hovering it for
# PREVIEW_DELAY ms, until the mouse leaves it: (who says it, colour key, text). Same formats as chat.py, made-up players.
PREVIEW_DELAY = 1000
PREVIEW_STEP = 400  # ms between the example's lines
CHAT_EXAMPLES = {
    "announcer": (("You", "you", "FIRST BLOOD: 'Klaus' killed 'Ivan'"),
                  ("You", "you", "'Klaus' GARDENED 'Ivan'!"),
                  ("You", "you", "*CLANG* 'Sergei' got PAN'D by 'Mira'"),
                  ("You", "you", "'Ivan' ragequit after dying to 'Klaus'")),
    "ez": (("", "feed", "You killed Ivan"),
           ("You", "you", "ez ivan")),
    "translate": (("Ivan", "red", "кто читер?"),
                  ("You", "you", "Ivan said: who is cheating?")),
    "beef": (("You", "you", "'Ivan' (RU) killed 'Taras' (UA) | Russia 1 - 0 Ukraine. Za pobedu!"),
             ("You", "you", "'Taras' (UA) killed 'Ivan' (RU) | Ukraine 1 - 1 Russia. Slava Ukraini!")),
    "idle": (("", "feed", "Idle for almost 3 minutes: typed retry before the kick"),
             ("console", "console", "] retry")),
}
# The sidebar's icons, from the Segoe Fluent Icons font that comes with Windows 11.
ICON_FONT = ("Segoe Fluent Icons", 15)
PAGE_ICONS = {"Players": "", "Cheat check": "", "Duels": "", "Chat": "",
              "Status": "", "Help": ""}
# Each team gets its own half of the window, so by default it shows fewer columns (the "columns"
# setting). The Columns button, or a right-click on a column title, switches each of these on or
# off; the flag stripe and the name always show.
PICKABLE_COLUMNS = tuple(c for c in COLUMNS if c not in ("Mark", "Player"))
COLUMN_NAMES = {"Ctry": "Country", "TF2": "Hours", "HS": "Headshot %", "Crit": "Crit %"}
SIDES = ("mine", "enemy")
# The chips above the list: (the "player_filter" setting, what the chip says).
HEALTH_ROWS = ("Duels", "!speak", "!who", "Info commands", "Translator", "Cheat check")  # the Status page's check
FILTERS = (("all", "Everyone"), ("flagged", "Flagged"), ("cheaters", "Cheaters"), ("new", "New accounts"))
PANEL_WRAP = 230  # px: the selected player's panel, right of the list
# The selected player's buttons: (group, ((key, text, App method), ...)).
PLAYER_ACTIONS = (
    ("Act on them", (("kick", "Votekick", "votekick"), ("mark", "Mark cheater", "toggle_mark"),
                     ("history", "SteamHistory", "open_steamhistory"), ("mute", "Mute !speak", "toggle_speak_mute"))),
    ("Say in chat", (("say", "Summary", "say_in_chat"), ("stats", "Stats", "say_stats"),
                     ("friends", "Friends", "say_friends"), ("ip", "Send fake IP", "say_ip"))),
)


FLAGS_CELL_CHARS = 42  # a longer flag is cut short in the list; the panel shows all of it


# The stamps' own colours (rubber-stamp red, orange and yellow, a touch warmer than the flags).
TAG_FG = {"cheat": "#e5533f", "sus": "#ec8d33", "weak": "#e6c84f"}


def flag_tag(text, severity):
    """The stamp in front of a player's worst flag: (word, colour), or None."""
    if re.search(r"\bbot\b", text, re.I):
        return "BOT", TAG_FG["sus"]
    if severity >= 3:
        return ("BANNED" if "ban" in text.lower() else "CHEATER"), TAG_FG["cheat"]
    if text.startswith("new account"):
        return "NEW", TAG_FG["weak"]
    if severity == 2:
        return "SUS", TAG_FG["sus"]
    return None


def tag_image(root, word, colour, height):
    """A rubber stamp: bold condensed capitals with wide letter spacing, a 2px border in the
    stamp's colour with 4px rounded corners and a thin dark line inside it, a dark see-through
    fill, tilted 3 degrees. Sizes are those of the design (an 11px font, padding 4/6/3) scaled
    to height, drawn 4x larger and scaled down for smooth edges. None without Pillow (the flag
    text still shows)."""
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageTk
    except ImportError:
        return None
    S = 4
    k = height / 19 * S  # the design's px -> pixels here, 4x
    try:
        font = ImageFont.truetype("bahnschrift.ttf", round(13.5 * k))
        try:
            font.set_variation_by_name("Bold Condensed")
        except (OSError, ValueError):
            pass
    except OSError:
        font = ImageFont.load_default()
    spacing = 0.2 * 11 * k  # letter-spacing (.14em in the design; Bahnschrift needs a bit more)
    advances = [font.getlength(ch) for ch in word]
    text_w = sum(advances) + spacing * (len(word) - 1)
    cap_top, cap_bottom = font.getbbox("H")[1], font.getbbox("H")[3]
    border, radius = 2 * k, 4 * k
    w = round(text_w + 2 * 6 * k + 2 * border)
    h = round((cap_bottom - cap_top) + (4 + 3) * k + 2 * border + 2 * k)
    rgb = tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5))
    image = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=(0, 0, 0, 64),
                           outline=rgb + (255,), width=round(border))
    inset = round(border)
    draw.rounded_rectangle((inset, inset, w - 1 - inset, h - 1 - inset), radius=max(1, radius - border),
                           outline=(0, 0, 0, 90), width=max(1, round(k)))
    x = (w - text_w) / 2
    y = (h - (cap_bottom - cap_top)) / 2 - cap_top + 0.5 * k  # a little low, like padding 4 over 3
    for ch, adv in zip(word, advances):
        draw.text((x, y), ch, font=font, fill=rgb + (255,), stroke_width=round(0.18 * k), stroke_fill=rgb + (255,))
        x += adv + spacing
    image = image.rotate(3, resample=Image.BICUBIC, expand=True)  # -3deg in the design: counter-clockwise
    image = image.resize((max(1, image.width // S), max(1, image.height // S)), Image.LANCZOS)
    return ImageTk.PhotoImage(image, master=root)


def short_cell(column, cell):
    """(text, colour) for the list, with a long Flags cell cut short, keeping its "+2"."""
    text, fg = cell[:2]
    if column != "Flags" or len(text) <= FLAGS_CELL_CHARS:
        return cell
    more = text[text.rfind("  +"):] if "  +" in text else ""
    return (text[:FLAGS_CELL_CHARS - len(more) - 1].rstrip() + "\u2026" + more, fg) + tuple(cell[2:])


def take_keyboard(window, take, back_to=None):
    """The scanner's window never takes the keyboard from TF2 (WS_EX_NOACTIVATE), except while
    you type in its search box. take=True lifts that, gives the window the keyboard and returns
    the window that had it; take=False puts it back and hands the keyboard to back_to again."""
    user32 = ctypes.windll.user32
    hwnd = user32.GetParent(window.winfo_id()) or window.winfo_id()
    GWL_EXSTYLE, WS_EX_NOACTIVATE = -20, 0x08000000
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    if take:
        before = user32.GetForegroundWindow()
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style & ~WS_EX_NOACTIVATE)
        user32.SetForegroundWindow(hwnd)
        return before
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE)
    if back_to:
        user32.SetForegroundWindow(back_to)


def work_area(window):
    """(left, top, width, height) of the screen the window is on, without the taskbar."""
    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", RECT), ("rcWork", RECT), ("dwFlags", ctypes.c_ulong)]
    MONITOR_DEFAULTTONEAREST = 2
    user32 = ctypes.windll.user32
    hwnd = user32.GetParent(window.winfo_id()) or window.winfo_id()
    info = MONITORINFO(ctypes.sizeof(MONITORINFO))
    user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST), ctypes.byref(info))
    r = info.rcWork
    return r.left, r.top, r.right - r.left, r.bottom - r.top


# The "Record only with a flagged player" switch's text, on the Tk and the web Cheat check page.
RECORD_ONLY_FLAGGED_ABOUT = ("TF2 records a demo only while someone flagged is in your match, so clean matches "
                             "never fill your disk.")

class Side:
    """One team's half of the player list: its title, column headers and reusable rows."""

    def __init__(self, frame):
        self.frame = frame
        self.title = None
        self.strip = None     # under the title: the team's classes, average hours, new accounts
        self.accent = None
        self.header_labels = {}
        self.rows = []        # per row: one label per column, reused for whoever sits there
        self.row_state = []   # what each row shows now (None = hidden), to skip no-op updates
        self.row_sids = []
        self.scroll = 0       # rows scrolled out of view above
# Clicking a header sorts by it: these go A to Z (or ALLY first), all others biggest first.
ASCENDING_COLUMNS = {"Ctry", "Class", "Player"}
MONO_COLUMNS = {"HP", "K/D", "Streak", "Duel", "HS", "Crit", "TF2", "Age"}  # numbers line up in mono
CLASS_ORDER = ["Scout", "Soldier", "Pyro", "Demo", "Heavy", "Engineer", "Medic", "Sniper", "Spy"]
WRAP = {"Profile": 220}  # pixels before a cell wraps onto a new line
HP_BAR = (44, 6)         # pixels: the health bar in front of the HP number, in 4px segments
HP_BAR_EMPTY = LINE      # the part of it that's gone


class Toast:
    """Click-through alert lines at the top of the screen."""

    def __init__(self, root, font, label_font=None):
        """A see-through window at the top of the screen that clicks pass through."""
        self.font, self.label_font = font, label_font or font
        self.items = []  # (expires, text, severity)
        self.win = win = tk.Toplevel(root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.attributes("-transparentcolor", KEY_COLOR)
        self.w, self.h = 760, 120
        win.geometry(f"{self.w}x{self.h}+{(root.winfo_screenwidth() - self.w) // 2}+30")
        self.canvas = tk.Canvas(win, bg=KEY_COLOR, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        win.update_idletasks()
        set_click_through(win, True)

    def show(self, text, severity):
        self.items = (self.items + [(time.time() + 8, text, severity)])[-4:]
        self.redraw()

    def tick(self):
        alive = [i for i in self.items if i[0] > time.time()]
        if len(alive) != len(self.items):
            self.items = alive
            self.redraw()

    def redraw(self):
        """Draws the current alerts: each a dark box with a bar in its colour on the left, a small
        ALERT label and the text, so it reads on any map."""
        c = self.canvas
        c.delete("all")
        y = 2
        for _, text, severity in self.items:
            colour = SEVERITY_FG[severity] if severity >= 1 else ACCENT
            label = c.create_text(0, y + 6, text="ALERT" if severity >= 1 else "SCANNER", anchor="nw",
                                  font=self.label_font, fill=colour)
            item = c.create_text(0, y + 20, text=text, anchor="nw", font=self.font, fill=TEXT)
            width = max(c.bbox(label)[2] - c.bbox(label)[0], c.bbox(item)[2] - c.bbox(item)[0]) + 32
            x0 = (self.w - width) // 2
            c.move(label, x0 + 18, 0)
            c.move(item, x0 + 18, 0)
            bottom = c.bbox(item)[3] + 7
            box = c.create_rectangle(x0, y, x0 + width, bottom, fill=BG, outline=colour)
            bar = c.create_rectangle(x0, y, x0 + 4, bottom, fill=colour, outline=colour)
            c.tag_lower(bar)
            c.tag_lower(box)
            y = bottom + 6


class FlatButton(Pill):
    """A square button with a 1px line that lights up in the accent under the mouse, and can be
    grayed out. danger: red (it acts against a player); link: blue (it opens a website)."""

    def __init__(self, parent, text, action, font, danger=False, link=False):
        if danger:
            self.normal_bg, self.hover_bg, self.fg, self.line = DANGER_BG, DANGER_HOVER_BG, DANGER_FG, "#7a2a2a"
        elif link:
            self.normal_bg, self.hover_bg, self.fg, self.line = LINK_BG, LINK_HOVER_BG, LINK_FG, "#24476d"
        else:
            self.normal_bg, self.hover_bg, self.fg, self.line = BUTTON_BG, BUTTON_HOVER_BG, TEXT, BORDER
        self.hover_line = self.fg if danger or link else ACCENT
        super().__init__(parent, text, font, self.fg, self.normal_bg, cursor="hand2", outline=self.line,
                         padx=10, pady=4)
        self.action, self.enabled = action, True
        self.bind("<Button-1>", lambda e: self.enabled and self.action())
        self.bind("<Enter>", lambda e: self.enabled and self._hover(True))
        self.bind("<Leave>", lambda e: self.enabled and self._hover(False))

    def _hover(self, over):
        self.set_fill(self.hover_bg if over else self.normal_bg, self.hover_line if over else self.line)
        tk.Label.configure(self, fg=(ACCENT if self.fg == TEXT else self.fg) if over else self.fg)

    def set_enabled(self, enabled):
        """Grayed out: just the text, without its button shape."""
        self.enabled = enabled
        tk.Label.configure(self, fg=self.fg if enabled else FAINT, cursor="hand2" if enabled else "arrow")
        self.set_fill(self.normal_bg if enabled else self._under, self.line if enabled else None)


class ChatPreview:
    """A small TF2-style chat box next to a card that plays the card's example, line by line."""

    COLOURS = {"you": "#99ccff", "red": "#ff8a83", "feed": TEXT2, "console": ACCENT}

    def __init__(self, card, lines, font, label_font):
        self.card, self.lines, self.font, self.label_font = card, lines, font, label_font
        self.win = None
        self.jobs = []
        self.top_job = None

    def show(self):
        if self.win:
            return
        win = self.win = tk.Toplevel(self.card)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        box = tk.Frame(win, bg=BG, highlightthickness=1, highlightbackground=ACCENT)
        box.pack()
        tk.Label(box, text="EXAMPLE: WHAT IT POSTS IN CHAT", font=self.label_font, fg=ACCENT, bg=BG,
                 anchor="w").pack(fill="x", padx=10, pady=(6, 2))
        rows = []
        for who, colour, text in self.lines:
            row = tk.Frame(box, bg=BG)
            if who:
                tk.Label(row, text=f"{who} :", font=self.font, fg=self.COLOURS["you" if colour == "you" else colour]
                         if colour != "feed" else TEXT2, bg=BG).pack(side="left")
            tk.Label(row, text=text, font=self.font, fg=TEXT if colour in ("you", "red") else self.COLOURS[colour],
                     bg=BG).pack(side="left", padx=(4, 0))
            rows.append(row)
        x = self.card.winfo_rootx()
        y = self.card.winfo_rooty() + self.card.winfo_height() + 4
        win.geometry(f"+{x}+{y}")
        for n, row in enumerate(rows):  # one line at a time, like chat coming in
            self.jobs.append(win.after(n * PREVIEW_STEP, lambda row=row: row.pack(fill="x", padx=10, pady=(0, 2))))
        self.jobs.append(win.after(len(rows) * PREVIEW_STEP, lambda: tk.Frame(box, bg=BG, height=6).pack()))
        self._stay_on_top()

    def _stay_on_top(self):
        """The scanner lifts its own window every 2 s (so the game never covers it): the preview
        lifts itself above that, for as long as it's open."""
        if self.win:
            self.win.lift()
            self.top_job = self.win.after(250, self._stay_on_top)

    def hide(self):
        if self.win:
            for job in self.jobs + [self.top_job]:
                if job:
                    self.win.after_cancel(job)
            self.jobs, self.top_job = [], None
            self.win.destroy()
            self.win = None


class SettingRow(tk.Frame):
    """A card you click: what the setting is, what it does, and its current value on the right.
    With an example, holding the mouse on it for 3 seconds plays what it posts in chat."""

    def __init__(self, parent, title, about, action, bold, small, example=None, mono=None, label_font=None):
        super().__init__(parent, cursor="hand2")
        round_card(self, CARD_BG, parent.cget("bg"))
        self.action = action
        self.columnconfigure(0, weight=1)
        self.title = tk.Label(self, text=title, font=bold, fg=TEXT, bg=CARD_BG, anchor="w")
        self.title.grid(row=0, column=0, sticky="w", padx=(16, 8), pady=(12, 0))
        self.about = tk.Label(self, text=about, font=small, fg=MUTED, bg=CARD_BG, anchor="w", justify="left",
                              wraplength=270)
        self.about.grid(row=1, column=0, sticky="w", padx=(16, 8), pady=(1, 12))
        self.value = Pill(self, "", small, MUTED, BG, under=CARD_BG, padx=12, pady=3, outline=BORDER)
        self.value.grid(row=0, column=1, rowspan=2, padx=(0, 16))
        for w in (self, self.title, self.about, self.value):
            w.bind("<Button-1>", lambda e: self.action())
        self.preview = ChatPreview(self, example, mono or small, label_font or bold) if example else None
        self.preview_job = None
        for w in (self, self.title, self.about, self.value):
            w.bind("<Enter>", lambda e: self._enter(), add="+")
            w.bind("<Leave>", lambda e: self._leave(), add="+")

    def _enter(self):
        self._tint(CARD_HOVER_BG)
        if self.preview and not self.preview_job:
            self.preview_job = self.after(PREVIEW_DELAY, self.preview.show)

    def _leave(self):
        """The mouse left the card (not just moved onto its title or value)."""
        x, y = self.winfo_pointerxy()
        under = self.winfo_containing(x, y)
        while under is not None and under is not self:
            under = under.master
        if under is self:
            return
        self._tint(CARD_BG)
        if self.preview_job:
            self.after_cancel(self.preview_job)
            self.preview_job = None
        if self.preview:
            self.preview.hide()

    def _tint(self, bg):
        self.set_card_fill(bg)
        for w in (self.title, self.about):
            w.config(bg=bg)
        self.value.set_under(bg)

    def set_title(self, title):
        self.title.config(text=title)

    def show(self, value, on=False):
        self.value.configure(text=value, fg=ON_FG if on else TEXT2)
        self.value.set_fill(ON_BG if on else BG, ON_BG if on else BORDER)


class Segmented(tk.Frame):
    """A row of rounded options of which one is chosen."""

    def __init__(self, parent, options, pick, font, under=None):
        under = under or parent.cget("bg")
        super().__init__(parent, bg=under)
        self.labels = {}
        for value, text in options:
            label = Pill(self, text, font, MUTED, BUTTON_BG, under=under, padx=12, pady=4, cursor="hand2",
                         outline=BORDER)
            label.pack(side="left", padx=(0, 0))
            label.bind("<Button-1>", lambda e, value=value: pick(value))
            self.labels[value] = label

    def select(self, chosen):
        for value, label in self.labels.items():
            label.configure(fg=ON_FG if value == chosen else TEXT2)
            label.set_fill(ACCENT if value == chosen else BUTTON_BG, ACCENT if value == chosen else BORDER)

    def rename(self, value, text):
        if self.labels[value].cget("text") != text:
            self.labels[value].config(text=text)


def status_colour(state):
    """The colour of a status light for a state like "connected" or "no key"."""
    if state in ("ok", "connected") or "known" in state:
        return GOOD
    if state in ("starting", "loading", "not connected"):
        return WAITING
    return FAINT if state == "no key" else BAD


class TokenPanel:
    """token_table, live in an ordinary window: not on top of the game, closed with its X."""

    def __init__(self, root, cfg, on_close):
        """Builds the window, at its saved place if that's still on a screen."""
        self.cfg = cfg
        self.win = win = tk.Toplevel(root)
        win.title("HoovyGPT tokens")
        win.configure(bg=BAR_BG)
        win.resizable(False, False)
        win.protocol("WM_DELETE_WINDOW", on_close)
        self.label = tk.Label(win, font=(mono_family(root), 9), fg=TEXT, bg=BAR_BG, justify="left", padx=8, pady=6)
        self.label.pack()
        x, y = cfg["token_panel_x"], cfg["token_panel_y"]
        if x is not None and on_a_screen(x + 40, y + 10):
            win.geometry(f"+{x}+{y}")
        self.update(cfg["token_panel"], token_table(""))

    def update(self, shown, text):
        """Changes the text when it differs, and opens or closes the window."""
        if text != self.label.cget("text"):
            self.label.config(text=text)
        if shown != (self.win.state() != "withdrawn"):
            if shown:
                self.win.deiconify()
            else:
                self.remember_place()
                self.win.withdraw()

    def remember_place(self):
        self.cfg["token_panel_x"], self.cfg["token_panel_y"] = self.win.winfo_x(), self.win.winfo_y()


class ScreensMixin:
    def set_visible(self, visible):
        """Shows or hides the player list (F9). Hidden, clicks pass through it to the game."""
        self.visible = visible
        if getattr(self, "web", None):
            self.web.set_visible(visible)
            if visible:
                self.dirty = True
                self.web_pushed_at = 0.0
            else:
                self.cfg["x"], self.cfg["y"] = self.web.where()[:2]
                save_config(self.cfg)
            return
        self.root.attributes("-alpha", 1.0 if visible else 0.0)  # solid when shown
        set_click_through(self.root, not visible)
        if visible:
            if not on_a_screen(self.root.winfo_x() + 40, self.root.winfo_y() + 10):
                self.root.geometry("+20+20")  # a monitor was unplugged while it was hidden
            self.dirty = True
        else:
            self.cfg["x"], self.cfg["y"] = self.maximized or (self.root.winfo_x(), self.root.winfo_y())
            save_config(self.cfg)

    def _drag_start(self, e):
        if self.maximized:
            self.drag = None  # a maximized window stays put
            return
        self.drag = (e.x_root, e.y_root, self.root.winfo_x(), self.root.winfo_y())

    def _drag_move(self, e):
        if self.drag:
            x0, y0, wx, wy = self.drag
            self.root.geometry(f"+{wx + e.x_root - x0}+{wy + e.y_root - y0}")

    # --- player list ----------------------------------------------------------------

    def set_filter(self, name):
        """A chip above the list: who it shows. Remembered for the next start."""
        self.cfg["player_filter"] = name
        save_config(self.cfg)
        self.render()

    def matches_filter(self, p, name):
        """Does this player belong in the list under that chip?"""
        flags = self.flags.get(p.sid, [])
        if name == "flagged":
            return any(severity >= 1 for severity, _ in flags)
        if name == "cheaters":  # a red flag (a ban, a cheater list, a proven demo check), marked by you,
            # or the cheater score says Likely / Proven: the same rule as the web window's Cheaters chip
            import cheat_score
            return cheat_score.is_cheater(self, p)
        if name == "new":
            return any(text == "new account" for _, text in flags)
        return True

    def update_filter_button(self, counts=None):
        """Lights the chosen chip, and puts how many players each chip would show on it."""
        self.filter_control.select(self.cfg["player_filter"])
        for name, text in FILTERS[1:]:
            count = (counts or {}).get(name)
            self.filter_control.rename(name, f"{text} {count}" if count else text)

    def set_search(self, text):
        """Typing in the search box: only players with that in their name show."""
        text = text.strip().casefold()
        if text != self.search:
            self.search = text
            for side in self.sides.values():
                side.scroll = 0
            self.render()

    def _search_focus(self, e=None):
        """A click in the search box: the window takes the keyboard until you're done typing."""
        if self.search_back_to is None:
            self.search_back_to = take_keyboard(self.root, True) or 0
        self.search_entry.focus_force()

    def _search_done(self, clear=False, back=True):
        """Enter keeps what you typed, Escape or the X clears it; both give TF2 the keyboard back."""
        if clear:
            self.search_entry.delete(0, "end")
            self.set_search("")
        if self.search_back_to is not None:
            take_keyboard(self.root, False, self.search_back_to if back else None)
            self.search_back_to = None
        self.root.focus_set()  # out of the box: no blinking cursor left in it

    def sorted_players(self):
        """Flagged players first (the default), or by the clicked column. Players a
        column knows nothing about go last either way, in the default order."""
        team_order = {"YOU": 0, "ALLY": 1, "?": 2, "ENEMY": 3}
        players = sorted(
            self.players.values(),
            key=lambda p: (-max((s for s, _ in self.flags.get(p.sid, [])), default=-1),
                           team_order[self.team_of(p)], p.name.casefold()),
        )
        if not self.sort_column:
            return players
        values = {p.sid: self.sort_value(p, self.sort_column) for p in players}
        known = [p for p in players if values[p.sid] is not None]
        known.sort(key=lambda p: values[p.sid], reverse=self.sort_descending)  # stable: ties keep default order
        return known + [p for p in players if values[p.sid] is None]

    def sort_value(self, p, column):
        """What a column sorts by for this player, or None when it's blank."""
        if column == "Mark":
            return max((s for s, _ in self.flags.get(p.sid, [])), default=None)
        if column == "Ctry":
            return (p.summary or {}).get("loccountrycode") or None
        if column == "Class":
            cls = self.player_class(p)
            return CLASS_ORDER.index(cls) if cls in CLASS_ORDER else None
        if column == "Player":
            return p.name.casefold()
        if column == "HP":
            fields = self.board.get(p.sid)
            if not fields:
                return None
            return -1 if fields.get("m_bAlive") == "false" else self.board_int(p.sid, "m_iHealth")
        if column == "K/D":
            return self.board_int(p.sid, "m_iScore")
        if column == "Streak":
            current, best = self.player_streak(p)
            return (current, best) if best else None
        if column == "Duel":
            mine, theirs = self.duels.get(p.sid, (0, 0))
            return (mine - theirs, mine) if mine or theirs else None
        if column in ("HS", "Crit"):
            stats = (self.kills if column == "HS" else self.crits).get(p.sid)
            return (stats[1] / stats[0], stats[0]) if stats else None
        if column == "TF2":
            return p.hours if isinstance(p.hours, (int, float)) else None
        if column == "Age":
            return (p.summary or {}).get("timecreated")
        if column == "Flags":
            flags = self.flags.get(p.sid, [])
            return (max(s for s, _ in flags), len(flags)) if flags else None
        if column == "Profile":
            prof = p.profile or {}
            hits = prof.get("comment_hits", 0) + len(prof.get("bio_words", []))
            return hits or None
        return None

    def sort_by(self, column):
        """1st click: the column's natural order, 2nd: reversed, 3rd: back to default."""
        natural = column not in ASCENDING_COLUMNS  # numbers: biggest first; names: A to Z
        if column != self.sort_column:
            self.sort_column, self.sort_descending = column, natural
        elif self.sort_descending == natural:
            self.sort_descending = not natural
        else:
            self.sort_column = None
        for side in self.sides.values():
            for name, label in side.header_labels.items():
                arrow = (" ▼" if self.sort_descending else " ▲") if name == self.sort_column else ""
                label.config(text=HEADERS.get(name, name).upper() + arrow,
                             fg=ACCENT if name == self.sort_column else MUTED)
        self.render()

    def _build_table(self):
        """Your team on the left, the other team on the right, each with its own title and
        column headers: clicking a header sorts both by it."""
        self.sides = {}
        for n, key in enumerate(SIDES):
            frame = tk.Frame(self.table, bg=BG)
            frame.grid(row=0, column=n, sticky="nsew", padx=(0, 6) if n == 0 else 0)
            frame.bind("<MouseWheel>", lambda e, key=key: self._scroll(e, key))
            side = self.sides[key] = Side(frame)
            side.accent = tk.Frame(frame, bg=FAINT, height=3)
            side.accent.grid(row=0, column=0, columnspan=len(COLUMNS), sticky="ew")
            side.title = tk.Label(frame, font=self.label_font, fg=MUTED, bg=BAR_BG, anchor="w", padx=8, pady=5)
            side.title.grid(row=1, column=0, columnspan=len(COLUMNS), sticky="ew", pady=(0, 2))
            side.title.bind("<MouseWheel>", lambda e, key=key: self._scroll(e, key))
            side.title.bind("<Button-3>", self.show_column_menu)
            side.strip = tk.Label(frame, font=self.mono, fg=TEXT2, bg=BG, anchor="w", padx=8, pady=2)
            side.strip.grid(row=2, column=0, columnspan=len(COLUMNS), sticky="ew")
            side.strip.bind("<MouseWheel>", lambda e, key=key: self._scroll(e, key))
            for col, text in enumerate(COLUMNS):
                label = tk.Label(frame, text=HEADERS.get(text, text).upper(), font=self.tiny, fg=MUTED,
                                 bg=BG, anchor="w", cursor="hand2")
                label.grid(row=3, column=col, sticky="w", padx=6)
                label.bind("<Button-1>", lambda e, text=text: self.sort_by(text))
                label.bind("<Button-3>", self.show_column_menu)
                label.bind("<MouseWheel>", lambda e, key=key: self._scroll(e, key))
                side.header_labels[text] = label
            # When a half is too narrow, only the Flags column gives up room (Tk shrinks weighted
            # columns only), so names are never squeezed; the full flags are in the player's panel.
            frame.columnconfigure(COLUMNS.index("Flags"), weight=1)
        self.table.columnconfigure((0, 1), weight=1, uniform="sides")
        self.table.rowconfigure(0, weight=1)
        self.empty_label = tk.Label(self.table, font=self.font, fg=MUTED, bg=BG)
        self.hidden_columns = frozenset()
        self.hp_images = {}       # (pixels filled, colour) -> the health bar's picture
        self.row_height = 0       # a player row's height in pixels, measured once one is drawn
        self.table_height = 0     # the table's height last time it was laid out

    def show_column_menu(self, e=None):
        """The Columns button, or a right-click on a column title: tick the columns to show."""
        menu = self.column_menu = tk.Menu(self.root, tearoff=0, bg=BAR_BG, fg=TEXT, activebackground=SELECTED_BG,
                                          activeforeground=TEXT, selectcolor=TEXT, font=self.small)
        self.column_vars = {}  # kept: a menu's tick disappears with its variable
        for column in PICKABLE_COLUMNS:
            var = self.column_vars[column] = tk.BooleanVar(value=column in self.cfg["columns"])
            menu.add_checkbutton(label=COLUMN_NAMES.get(column, column), variable=var,
                                 command=lambda column=column: self.toggle_column(column))
        button = self.columns_button
        x, y = (e.x_root, e.y_root) if e else (button.winfo_rootx(), button.winfo_rooty() + button.winfo_height())
        menu.tk_popup(x, y)

    def toggle_column(self, column):
        """Shows or hides a column on both halves, and remembers it."""
        shown = self.cfg["columns"]
        self.cfg["columns"] = [c for c in PICKABLE_COLUMNS if (c in shown) != (c == column)]
        save_config(self.cfg)
        self.table_widest = 0  # the list may get narrower
        self.render()

    def redraw_rows(self):
        """Every row draws itself again on the next render (a flag or class icon arrived)."""
        for side in self.sides.values():
            side.row_state = [s if s is None else "new" for s in side.row_state]

    def _row_labels(self, key, i):
        """The labels of row i on one side, created the first time that row is needed."""
        side = self.sides[key]
        while len(side.rows) <= i:
            r = len(side.rows)
            labels = []
            for col, column in enumerate(COLUMNS):
                font = self.bold if column == "Player" else self.mono if column in MONO_COLUMNS else self.font
                lbl = tk.Label(side.frame, font=font, bg=BG, pady=4,
                               anchor="w", wraplength=WRAP.get(column, 0), justify="left",
                               compound="left")  # picture before the text, e.g. class icon + "Pyro"
                lbl.grid(row=r + 4, column=col, sticky="nsew", ipadx=6)
                lbl.bind("<Button-1>", lambda e, r=r: self.select_row(key, r))
                lbl.bind("<Enter>", lambda e, r=r: self._hover_row(key, r, True))
                lbl.bind("<Leave>", lambda e, r=r: self._hover_row(key, r, False))
                lbl.bind("<MouseWheel>", lambda e: self._scroll(e, key))
                labels.append(lbl)
            side.rows.append(labels)
            side.row_state.append("new")
        return side.rows[i]

    def _hover_row(self, key, r, over):
        """Lights up the row under the mouse; a selected row keeps its own colour."""
        side = self.sides[key]
        state = side.row_state[r]
        if isinstance(state, tuple) and state[0] != "team" and state[1] != SELECTED_BG:
            for lbl in side.rows[r]:
                lbl.config(bg=ROW_HOVER_BG if over else state[1])

    def streak_cell(self, p):
        """("5 (best 9)", color): orange from 5 kills in a row, that player is on a rampage."""
        current, best = self.player_streak(p)
        if not best:
            return "", TEXT2
        text = f"best {best}" if not current else f"{current}" if current == best else f"{current} (best {best})"
        return text, SEVERITY_FG[2] if current >= 5 else TEXT2

    def favorite_weapon(self, p, template):
        """The weapon they got most kills with this match, filled into template."""
        counts = self.weapons.get(p.sid)
        if not counts:
            return ""
        weapon, kills = counts.most_common(1)[0]
        return template.format(name=weapon_name(weapon), kills=kills)

    def live_rate(self, stats, judge):
        """("92% 11/12", color) for a [kills, of which special] count from this match;
        orange once judge() flags it."""
        if not stats:
            return "", TEXT2
        kills, special = stats
        flagged = (judge(stats, self.cfg) or (0,))[0] >= 2
        return f"{round(100 * special / kills)}% {special}/{kills}", SEVERITY_FG[2] if flagged else TEXT2

    def row_cells(self, p):
        """What one player's row shows: (text, colour) for each column, or (text, colour,
        picture) where a picture goes in front of the text (their avatar, the health bar)."""
        flags = self.flags.get(p.sid, [])
        severity = max((s for s, _ in flags), default=-1)
        profile, profile_hit = profile_text(p.profile)
        mine, theirs = self.duels.get(p.sid, (0, 0))
        duel = f"{mine}–{theirs}" if mine or theirs else ""
        duel_fg = GOOD if mine > theirs else DANGER_FG if theirs > mine else TEXT2
        hs, hs_fg = self.live_rate(self.kills.get(p.sid), headshot_flag)
        crit, crit_fg = self.live_rate(self.crits.get(p.sid), crit_flag)
        kills, deaths = self.board_text(p, "m_iScore"), self.board_text(p, "m_iDeaths")
        return (
            # Country as set on their public Steam profile: drawn as a flag once downloaded.
            ("▌" if severity >= 1 else "", SEVERITY_FG[severity]),
            ("…" if p.summary is None else p.summary.get("loccountrycode", ""), TEXT2),
            (self.player_class(p), TEXT2),
            ((p.name if len(p.name) <= 26 else p.name[:25] + "…") + ("  (you)" if p.sid == self.me else ""),
             TEAM_FG["YOU"] if p.sid == self.me else SEVERITY_FG[severity], self.avatar_images.get(p.sid)),
            # Only TF2's scoreboard knows these (needs -g15); blank without it.
            self.health_cell(p) + (self.hp_bar(p),),
            (f"{kills or 0}/{deaths or 0}" if kills or deaths else "", TEXT),
            self.streak_cell(p),
            (duel, duel_fg),
            (hs, hs_fg),
            (crit, crit_fg),
            (fmt_hours(p.hours), TEXT2),
            (fmt_age(p.summary), TEXT2),
            # The worst flag and how many more: every flag with its reason shows when you click them.
            ((flags[0][1] + (f"  +{len(flags) - 1}" if len(flags) > 1 else "")) if flags else "", SEVERITY_FG[severity],
             self.flag_tag_image(flags[0][1], flags[0][0]) if flags else None),
            (profile, SEVERITY_FG[2] if profile_hit else MUTED),
        )

    def flag_tag_image(self, text, severity):
        """The stamp picture for a flag, drawn once per word and colour."""
        tag = flag_tag(text, severity)
        if not tag:
            return None
        if not hasattr(self, "tag_images"):
            self.tag_images = {}
        if tag not in self.tag_images:
            import tkinter.font as tkfont
            height = tkfont.Font(root=self.root, font=self.font).metrics("linespace")
            self.tag_images[tag] = tag_image(self.root, tag[0], tag[1], height)
        return self.tag_images[tag]

    def hp_bar(self, p):
        """A small bar of how much of their health is left, in the colour of the number next to
        it. None when they're dead or their health isn't known."""
        text, color = self.health_cell(p)
        if not text.isdigit():
            return None
        full = CLASS_MAX_HEALTH.get(self.player_class(p))
        share = int(text) / full if full else (1 if int(text) > 100 else 0.5 if int(text) > 50 else 0.15)
        filled = max(1, round(min(share, 1) * HP_BAR[0]))  # overheal: a full bar, in its own colour
        if (filled, color) not in self.hp_images:  # drawn once for each length and colour
            width, height = HP_BAR
            picture = tk.PhotoImage(width=width, height=height)
            picture.put(BG, to=(0, 0, width, height))
            for x in range(0, width, 4):  # 3px segments with a 1px gap
                picture.put(color if x < filled else HP_BAR_EMPTY, to=(x, 0, min(x + 3, width), height))
            self.hp_images[filled, color] = picture
        return self.hp_images[filled, color]

    def team_strip(self, group):
        """What a team is made of, for the line under its title: "3 Sniper · 2 Medic · 4 more ·
        average 1,240 hours · 2 new accounts". Each part is left out while nothing is known."""
        classes = Counter(filter(None, map(self.player_class, group))).most_common()
        parts = [f"{count} {cls}" for cls, count in classes[:4]]
        if len(classes) > 4:
            parts.append(f"{sum(count for _, count in classes[4:])} more")
        hours = [p.hours for p in group if isinstance(p.hours, (int, float))]
        if hours:
            parts.append(f"average {round(sum(hours) / len(hours)):,} hours")
        new = sum(1 for p in group if any(text == "new account" for _, text in self.flags.get(p.sid, [])))
        if new:
            parts.append(f"{new} new account{'s' * (new != 1)}")
        return " · ".join(parts)

    def team_sides(self, players):
        """{side: (title, accent colour, entries, strip)} for the two halves of the list. Entries are
        ("player", p), or ("team", text, colour) above players whose team isn't known yet.
        Flagged players stay on top of each half (sorted_players' default order). While only
        your own team is known, everyone is on the left and the right half is empty."""
        groups = {"mine": [], "enemy": [], "?": []}
        for p in players:
            team = self.team_of(p)
            groups["mine" if team in ("YOU", "ALLY") else "enemy" if team == "ENEMY" else "?"].append(p)

        def title(name, group):
            color = next((c for c in map(self.team_color, group) if c), "")
            flagged = sum(1 for p in group if max((s for s, _ in self.flags.get(p.sid, [])), default=-1) >= 1)
            return (f"{name}{f' · {color}' if color else ''}     {len(group)} player{'s' * (len(group) != 1)}"
                    + (f" · {flagged} flagged" if flagged else "")), TEAM_ACCENT.get(color)

        if not groups["enemy"] and all(p.sid == self.me for p in groups["mine"]):
            text, _ = title("PLAYERS", players)
            return {"mine": (text, FAINT, [("player", p) for p in players], self.team_strip(players)),
                    "enemy": ("", FAINT, [], "")}
        text, accent = title("YOUR TEAM", groups["mine"])
        sides = {"mine": (text, accent or TEAM_FG["ALLY"], [("player", p) for p in groups["mine"]],
                          self.team_strip(groups["mine"]))}
        unknown = [("player", p) for p in groups["?"]]
        if groups["enemy"]:
            text, accent = title("ENEMY TEAM", groups["enemy"])
            entries = [("player", p) for p in groups["enemy"]]
            if unknown:
                entries += [("team", "TEAM NOT KNOWN YET", MUTED)] + unknown
            sides["enemy"] = (text, accent or TEAM_FG["ENEMY"], entries, self.team_strip(groups["enemy"]))
        else:
            sides["enemy"] = (title("TEAM NOT KNOWN YET", groups["?"])[0], FAINT, unknown, self.team_strip(groups["?"]))
        return sides

    def render(self):
        """Draws both halves of the player list, touching only the rows that differ from last
        time so it stays fast."""
        self.update_status()
        everyone = self.sorted_players()
        others = [p for p in everyone if p.sid != self.me]
        self.update_filter_button({name: sum(self.matches_filter(p, name) for p in others) for name, _ in FILTERS[1:]})
        # A chip keeps you in the list next to who it picks; the search box shows only names with what you typed.
        players = [p for p in everyone if p.sid == self.me or self.matches_filter(p, self.cfg["player_filter"])]
        if self.search:
            players = [p for p in players if self.search in p.name.casefold()]
        if players:
            self.empty_label.grid_remove()
        else:
            self.empty_label.config(text="Nobody here matches that." if everyone
                                    else "Waiting for TF2…  Start the game and this fills up by itself."
                                    if self.rcon_state != "connected"
                                    else "No players yet (join a server)")
            self.empty_label.grid(row=1, column=0, columnspan=2, sticky="w", padx=6, pady=6)
        cells = {p.sid: tuple(short_cell(c, cell) for c, cell in zip(COLUMNS, self.row_cells(p))) for p in players}
        # Left out, with its header, on both halves: a column you switched off, and one nobody
        # shown has anything in.
        picked = set(self.cfg["columns"]) | {"Mark", "Player"}
        hidden = frozenset(column for i, column in enumerate(COLUMNS) if column not in picked
                           or column in HIDEABLE_COLUMNS and all(row[i][0] in BLANK_CELLS for row in cells.values()))
        if hidden != self.hidden_columns:
            self.hidden_columns = hidden
            for side in self.sides.values():
                for name, label in side.header_labels.items():
                    label.grid_remove() if name in hidden else label.grid()
        sides = self.team_sides(players)
        # The strip takes a line from the list, so how many rows fit is worked out with it there.
        for key, side in sides.items():
            strip = self.sides[key].strip
            if strip.cget("text") != side[3]:
                strip.config(text=side[3])
            if bool(side[3]) != bool(strip.winfo_manager()):
                strip.grid() if side[3] else strip.grid_remove()
        rows = self.visible_rows()
        for key, (title, accent, entries, _) in sides.items():
            self._render_side(key, title, accent, entries, cells, hidden, rows, bool(players))
        self.render_actions()

    def _render_side(self, key, title, accent, entries, cells, hidden, rows, anyone):
        """One half: its title (with how many are scrolled out of view) and its rows."""
        side = self.sides[key]
        if not entries and (key == "enemy" or not anyone):
            if side.frame.winfo_manager():
                side.frame.grid_remove()
        elif not side.frame.winfo_manager():
            side.frame.grid()
        side.scroll = max(0, min(side.scroll, len(entries) - rows)) if rows else 0
        above, below = side.scroll, max(0, len(entries) - side.scroll - rows) if rows else 0
        entries = entries[side.scroll:side.scroll + rows] if rows else entries
        more = " · ".join(filter(None, (f"▲ {above}" if above else "", f"▼ {below} more" if below else "")))
        title = f"{title}     {more}" if more else title
        if side.title.cget("text") != title:
            side.title.config(text=title, fg=accent if accent != FAINT else MUTED)
        if side.accent.cget("bg") != accent:
            side.accent.config(bg=accent)
        side.row_sids = [entry[1].sid if entry[0] == "player" else None for entry in entries]
        stripe = 0  # every other player row is a shade lighter, counting from each header
        for i, entry in enumerate(entries):
            labels = self._row_labels(key, i)
            if entry[0] == "team":
                stripe = 0
                if side.row_state[i] != entry:
                    # A header uses the row's first label, stretched over every column.
                    labels[0].grid(columnspan=len(COLUMNS), pady=(6 if i else 0, 1))
                    labels[0].config(text=entry[1], image="", fg=entry[2], bg=BAR_BG, font=self.label_font)
                    for lbl in labels[1:]:
                        lbl.grid_remove()
                    side.row_state[i] = entry
                continue
            p = entry[1]
            if not self.row_height:
                self.row_height = labels[COLUMNS.index("Player")].winfo_reqheight()  # never hidden
            bg = SELECTED_BG if p.sid == self.selected else ROW_ALT_BG if stripe % 2 else BG
            stripe += 1
            state = (cells[p.sid], bg, hidden)
            if side.row_state[i] == state:
                continue
            labels[0].grid(columnspan=1, pady=0)
            labels[0].config(font=self.font)
            for lbl, column, cell in zip(labels, COLUMNS, cells[p.sid]):
                if column in hidden:
                    lbl.grid_remove()
                    continue
                lbl.grid()  # in case it was hidden
                text, fg = cell[:2]
                images = {"Ctry": self.flag_images, "Class": self.class_images}.get(column, {})
                picture = cell[2] if len(cell) > 2 else images.get(text)
                # A flag replaces the country code and a class icon the class name; avatars and the health bar go
                # in front of their text.
                shown = text if not picture else "" if column in ("Ctry", "Class") else f" {text}"
                lbl.config(text=shown, image=picture or "", fg=fg, bg=bg)
            side.row_state[i] = state
        for i in range(len(entries), len(side.rows)):
            if side.row_state[i] is not None:
                for lbl in side.rows[i]:
                    lbl.grid_remove()
                side.row_state[i] = None

    # --- the window's frame and its pages ------------------------------------------------

    def _build_shell(self):
        """The header with the status lights, the tabs, and the places the pages go."""
        root, cfg = self.root, self.cfg
        self.tiny = (FONT_LABEL, 9)
        header = tk.Frame(root, bg=BAR_BG)
        header.pack(fill="x")
        tk.Frame(root, bg=LINE, height=1).pack(fill="x")  # the 1px line under the header
        logo = tk.Label(header, text="\u25c8", font=(FONT_LABEL, 13), fg=ACCENT, bg=BAR_BG)
        logo.pack(side="left", padx=(12, 6), pady=6)
        title = tk.Label(header, text="TF2 TOOLBOX", font=(FONT_LABEL, 13), fg=TEXT, bg=BAR_BG)
        title.pack(side="left")
        self.info = tk.Label(header, font=self.mono, fg=MUTED, bg=BAR_BG)
        self.info.pack(side="left", padx=(10, 6))
        # A light per connection; clicking one opens the Status page with the details.
        self.lights = {}
        for name in ("TF2", "Steam", "History", "Lists"):
            light = tk.Label(header, text=f"\u25a0 {name.upper()}", font=self.tiny, fg=FAINT, bg=BAR_BG, cursor="hand2")
            light.pack(side="left", padx=4)
            light.bind("<Button-1>", lambda e: self.show_page("Status"))
            self.lights[name] = light
        self.feedback_label = tk.Label(header, font=self.small, fg=GOOD, bg=BAR_BG)
        self.feedback_label.pack(side="left", padx=10)
        # There's no console window to close any more, so quitting happens here.
        FlatButton(header, "\u2715", self.quit, self.small, danger=True).pack(side="right", padx=(2, 8), pady=6)
        self.maximized = None  # while maximized: (x, y) to go back to
        self.maximize_button = FlatButton(header, "\ue922", self.toggle_maximized, ("Segoe Fluent Icons", 9))
        self.maximize_button.pack(side="right", padx=2, pady=6)
        self.minimize_button = FlatButton(header, "", self.toggle_minimized, self.small)
        self.minimize_button.pack(side="right", padx=2, pady=6)
        hint = tk.Label(header, text=f"{cfg['toggle_key']} HIDES THIS", font=self.tiny, fg=MUTED, bg=BAR_BG)
        hint.pack(side="right", padx=8)

        # The pages, as icons with their name under them down the left side.
        self.tab_bar = tk.Frame(root, bg=BAR_BG)
        self.tabs = {}
        for name in PAGES:
            tab = tk.Frame(self.tab_bar, bg=BAR_BG, cursor="hand2")
            tab.pack(fill="x", padx=(4, 0), pady=(6 if name == PAGES[0] else 0, 2))
            line = tk.Frame(tab, bg=BAR_BG, width=3)
            line.pack(side="left", fill="y")
            icon = tk.Label(tab, text=PAGE_ICONS[name], font=ICON_FONT, fg=MUTED, bg=BAR_BG, cursor="hand2")
            icon.pack(padx=(6, 9), pady=(6, 0))
            label = tk.Label(tab, text=name.upper(), font=self.tiny, fg=MUTED, bg=BAR_BG, padx=4, cursor="hand2")
            label.pack(padx=(6, 9), pady=(0, 6))
            for w in (tab, icon, label):
                w.bind("<Button-1>", lambda e, name=name: self.show_page(name))
            self.tabs[name] = label, line, icon
        for w in (header, logo, title, self.info, hint, self.tab_bar):
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
        for w in (header, logo, title, self.info, hint):
            w.bind("<Double-Button-1>", lambda e: self.toggle_maximized())

        self.page_area = tk.Frame(root, bg=BG)
        self.pages = {name: tk.Frame(self.page_area, bg=BG) for name in PAGES}
        page = self.pages["Players"]
        self.toolbar = tk.Frame(page, bg=BG)
        self.table = tk.Frame(page, bg=BG)
        self.actions = tk.Frame(page, bg=BAR_BG)
        self.width_spacer = tk.Frame(root, bg=BG, height=1)  # makes the window as wide as you dragged it
        self.bottom_edge = tk.Frame(root, bg=BG, height=4, cursor="sb_v_double_arrow")

    def show_page(self, name):
        """Opens a tab. It's remembered for the next start."""
        name = "Duels" if name == "HoovyGPT" else name  # that page's name before it became Duels
        name = name if name in self.pages else PAGES[0]
        if name != self.cfg["page"]:
            self.cfg["page"] = name
            save_config(self.cfg)
        for other, (label, line, icon) in self.tabs.items():
            label.config(fg=ACCENT if other == name else MUTED)
            icon.config(fg=ACCENT if other == name else MUTED)
            line.config(bg=ACCENT if other == name else BAR_BG)
        for page in self.pages.values():
            page.pack_forget()
        self.pages[name].pack(fill="both", expand=True)

    def update_status(self):
        """The header's lights and the Status page, from the state of every connection."""
        states = {"TF2": self.rcon_state, "Steam": self.api_state, "History": self.sh_state, "Lists": self.lists_state}
        for name, state in states.items():
            colour = status_colour(state)
            if self.lights[name].cget("fg") != colour:
                self.lights[name].config(fg=colour)
            light, text = self.status_rows[name]
            if text.cget("text") != state:
                light.config(fg=colour)
                text.config(text=state)
        server, slots = self.server_text()
        place = " \u00b7 ".join(filter(None, (self.map_name, server, f"{slots or len(self.players)} players")))
        if self.info.cget("text") != place:
            self.info.config(text=place)
        duels = "\n".join(self.duel_entries()) or "No duels running."
        if self.duels_label.cget("text") != duels:
            self.duels_label.config(text=duels)
        demo = f"Cheat check: {self.demo_state}"
        if self.demo_state_label.cget("text") != demo:
            self.demo_state_label.config(text=demo)
        record = self.record_text()
        if self.demo_record_label.cget("text") != record:
            self.demo_record_label.config(text=record)
        if self.demo_summary != self.demo_summary_shown:
            self.demo_summary_shown = self.demo_summary
            self._set_text(self.demo_summary_box, self.demo_summary or "Nothing found yet.")
            self._set_text(self.demo_meaning_box, getattr(self, "demo_meaning", "") or meaning_text())
        self.refresh_demo_browser()
        log = "\n".join(self.demo_log) or "No checks yet."
        if self.demo_log_label.cget("text") != log:
            self.demo_log_label.config(text=log)
        for name, level, text in self.feature_health():
            light, label = self.health_rows[name]
            colour = {"ok": GOOD, "warn": WAITING, "bad": BAD}.get(level, FAINT)
            if label.cget("text") != text or light.cget("fg") != colour:
                light.config(fg=colour)
                label.config(text=text)
        chat = f"{self.chat_sent_count} sent, {self.chat_refused_count} refused by the server"
        if self.status_chat.cget("text") != chat:
            self.status_chat.config(text=chat)

    def _section_label(self, parent, text):
        return tk.Label(parent, text=text.upper(), font=self.tiny, fg=MUTED, bg=parent.cget("bg"), anchor="w")

    def _build_players_page(self):
        """Above the table the filter and what's about the whole lobby, under it the selected player."""
        bar = self.toolbar
        if self.cfg["player_filter"] not in dict(FILTERS):
            self.cfg["player_filter"] = "all"
        self.filter_control = Segmented(bar, FILTERS, self.set_filter, self.small)
        self.filter_control.pack(side="left", padx=(8, 0), pady=7)
        self.update_filter_button()
        # Search: a magnifying glass, the box, and an X that empties it.
        tk.Label(bar, text="\ue721", font=("Segoe Fluent Icons", 9), fg=MUTED, bg=BG).pack(side="left", padx=(10, 4))
        self.search_back_to = None  # while you type: the window that had the keyboard before (TF2)
        self.search_entry = entry = tk.Entry(bar, width=16, font=self.small, fg=TEXT, bg=BG, relief="flat",
                                             insertbackground=ACCENT, highlightthickness=1,
                                             highlightbackground=BORDER, highlightcolor=ACCENT)
        entry.pack(side="left", ipady=3)
        entry.bind("<Button-1>", self._search_focus)
        entry.bind("<KeyRelease>", lambda e: self.set_search(entry.get()))
        entry.bind("<Return>", lambda e: self._search_done())
        entry.bind("<Escape>", lambda e: self._search_done(clear=True))
        entry.bind("<FocusOut>", lambda e: self._search_done(back=False))
        FlatButton(bar, "\u2715", lambda: self._search_done(clear=True), self.small).pack(side="left", padx=(2, 0))
        self.columns_button = FlatButton(bar, "Columns", lambda: self.show_column_menu(), self.small)
        self.columns_button.pack(side="left", padx=(8, 0), pady=7)
        self.lobby_buttons = []
        for n, (text, action) in enumerate((("Kill race", self.say_kill_race), ("Lobby summary", self.say_lobby_summary))):
            b = FlatButton(bar, text, action, self.small)
            b.pack(side="right", padx=(4, 0 if n else 8), pady=7)
            self.lobby_buttons.append(b)
        self._section_label(bar, "Say in chat").pack(side="right", padx=6)

        # On the right of the list while a player is selected: who they are, what's known about
        # them, why they're flagged, and their buttons.
        panel = self.actions
        top = tk.Frame(panel, bg=BAR_BG)
        top.pack(fill="x", padx=(12, 6), pady=(8, 0))
        self.player_title = tk.Label(top, font=(FONT_LABEL, 14), fg=TEXT, bg=BAR_BG,
                                     anchor="w", justify="left", wraplength=PANEL_WRAP - 30)
        self.player_title.pack(side="left", fill="x", expand=True)
        FlatButton(top, "✕", lambda: self.select(self.selected), self.small).pack(side="right", anchor="n")
        self.player_about = tk.Label(panel, font=self.small, fg=MUTED, bg=BAR_BG, anchor="w", justify="left",
                                     wraplength=PANEL_WRAP)
        self.player_about.pack(fill="x", padx=12, pady=(2, 0))
        # Why the selected player is flagged, under what's known.
        self.why_label = tk.Label(panel, font=self.small, fg=TEXT2, bg=BAR_BG, justify="left", anchor="w",
                                  wraplength=PANEL_WRAP)
        self.player_buttons = tk.Frame(panel, bg=BAR_BG)
        self.player_buttons.pack(fill="x", padx=12, pady=(8, 12))
        self.buttons = {}
        self.enabled = set()  # the buttons that apply to the selected player
        row = 0
        for group, entries in PLAYER_ACTIONS:
            self._section_label(self.player_buttons, group).grid(row=row, column=0, sticky="w", pady=(6 if row else 0, 2))
            row += 1
            per_row = 2 if group == "Act on them" else 4  # short words fit on one line: the panel stays low
            for n in range(0, len(entries), per_row):
                line = tk.Frame(self.player_buttons, bg=BAR_BG)
                line.grid(row=row, column=0, sticky="w", pady=2)
                row += 1
                for key, text, method in entries[n:n + per_row]:
                    b = FlatButton(line, text, getattr(self, method), self.small, danger=key == "kick",
                                   link=key == "history")
                    b.pack(side="left", padx=(0, 4))
                    self.buttons[key] = b

    def _card_grid(self, parent):
        """A frame for cards in two equal columns."""
        grid = tk.Frame(parent, bg=BG)
        grid.pack(fill="x", padx=8, pady=8)
        grid.columnconfigure((0, 1), weight=1, uniform="cards")
        return grid

    def _setting(self, parent, row, column, title, about, action, span=1, example=None):
        card = SettingRow(parent, title, about, action, self.bold, self.small, example=example, mono=self.mono,
                          label_font=self.tiny)
        card.grid(row=row, column=column, columnspan=span, sticky="nsew", padx=4, pady=4)
        return card

    def _build_ai_page(self):
        """The Duels page: on or off, the duels running now with their scores, and what players
        can type. While HoovyGPT may talk (the heavy_talks setting), its model, who can mute it
        and its tokens are here too; otherwise those stay out of sight."""
        page, heavy = self.pages["Duels"], self.cfg["heavy_talks"]
        grid = self._card_grid(page)
        self.ai_button = self._setting(grid, 0, 0, "HoovyGPT + Duels" if heavy else "Duels",
                                       "Players start a duel by typing !duel and a name in chat.",
                                       self.toggle_ai, span=2)
        # On again after a restart if it was on, as Heavy can't talk; with heavy_talks on it starts
        # off, so Heavy never starts talking by surprise.
        if self.cfg["duels_on"] and not heavy and not self.ai_on:
            self.toggle_ai()
        self.update_ai_button()

        running = round_card(tk.Frame(page), CARD_BG, BG)
        running.pack(fill="x", padx=11, pady=(0, 8))
        top = tk.Frame(running, bg=CARD_BG)
        top.pack(fill="x", padx=12, pady=(8, 0))
        tk.Label(top, text="Running now", font=self.bold, fg=TEXT, bg=CARD_BG).pack(side="left")
        FlatButton(top, "Stop all duels", self.stop_duels_from_page, self.small, danger=True).pack(side="right")
        self.duels_label = tk.Label(running, text="No duels running.", font=self.small, fg=TEXT, bg=CARD_BG,
                                    justify="left", anchor="w")
        self.duels_label.pack(fill="x", padx=12, pady=(4, 10))

        how = round_card(tk.Frame(page), CARD_BG, BG)
        how.pack(fill="x", padx=11, pady=(0, 8))
        tk.Label(how, text="What players can type in chat", font=self.bold, fg=TEXT, bg=CARD_BG, anchor="w").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(8, 2))
        for row, (command, about) in enumerate(DUEL_COMMANDS, 1):
            tk.Label(how, text=command, font=self.mono, fg=TEXT, bg=CARD_BG, anchor="w").grid(
                row=row, column=0, sticky="w", padx=(12, 14), pady=(0, 10 if row == len(DUEL_COMMANDS) else 0))
            tk.Label(how, text=about, font=self.small, fg=MUTED, bg=CARD_BG, anchor="w").grid(
                row=row, column=1, sticky="w", padx=(0, 12), pady=(0, 10 if row == len(DUEL_COMMANDS) else 0))

        # HoovyGPT's own settings. They're always built (ai.py keeps them up to date), but only
        # on the page while it may talk.
        self.heavy_cards = tk.Frame(page, bg=BG)
        if heavy:
            self.heavy_cards.pack(fill="x")
        grid = self._card_grid(self.heavy_cards)
        self.model_button = self._setting(grid, 0, 0, "Model", "The one asked first. Click to pick another.",
                                          self.show_model_menu, span=2)
        self.model_button_loop()
        lock = round_card(tk.Frame(grid), CARD_BG, grid.cget("bg"))
        lock.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=3, pady=3)
        lock.columnconfigure(0, weight=1)
        tk.Label(lock, text="Who can mute Heavy", font=self.bold, fg=TEXT, bg=CARD_BG, anchor="w").grid(
            row=0, column=0, sticky="w", padx=12, pady=(8, 0))
        tk.Label(lock, text="Do !badbot and !goodbot work for others?", font=self.small, fg=MUTED, bg=CARD_BG,
                 anchor="w").grid(row=1, column=0, sticky="w", padx=12)
        self.lock_control = Segmented(lock, (("off", "Anyone"), ("on", "Stays on"), ("muted", "Stays muted")),
                                      lambda lock: self.pick_lock(None if lock == "off" else lock), self.small,
                                      under=CARD_BG)
        self.lock_control.grid(row=2, column=0, sticky="w", padx=12, pady=(6, 10))
        self.update_lock_button()
        tokens = round_card(tk.Frame(self.heavy_cards), CARD_BG, BG)
        tokens.pack(fill="x", padx=11, pady=(0, 11))
        top = tk.Frame(tokens, bg=CARD_BG)
        top.pack(fill="x", padx=12, pady=(8, 0))
        tk.Label(top, text="Tokens today", font=self.bold, fg=TEXT, bg=CARD_BG).pack(side="left")
        self.tokens_button = FlatButton(top, "", self.toggle_token_panel, self.small)
        self.tokens_button.pack(side="right")
        self.tokens_inline = tk.Label(tokens, font=self.mono, fg=TEXT, bg=CARD_BG, justify="left", anchor="w")
        self.tokens_inline.pack(fill="x", padx=12, pady=(4, 8))
        self.update_tokens_button()

    def _help_card(self, parent, row, column, title, rows, note=""):
        """One card of the Help page: a title, then command and what it does, one per row."""
        card = round_card(tk.Frame(parent), CARD_BG, parent.cget("bg"))
        card.grid(row=row, column=column, sticky="nsew", padx=3, pady=3)
        tk.Label(card, text=title, font=self.bold, fg=TEXT, bg=CARD_BG, anchor="w").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(8, 2))
        for i, (command, about) in enumerate(rows, 1):
            last = i == len(rows) and not note
            tk.Label(card, text=command, font=self.mono, fg=TEXT, bg=CARD_BG, anchor="w").grid(
                row=i, column=0, sticky="nw", padx=(12, 14), pady=(0, 10 if last else 2))
            tk.Label(card, text=about, font=self.small, fg=MUTED, bg=CARD_BG, anchor="w", justify="left",
                     wraplength=380).grid(row=i, column=1, sticky="w", padx=(0, 12), pady=(0, 10 if last else 2))
        if note:
            tk.Label(card, text=note, font=self.small, fg=MUTED, bg=CARD_BG, anchor="w", justify="left",
                     wraplength=560).grid(row=len(rows) + 1, column=0, columnspan=2, sticky="w", padx=12, pady=(4, 10))
        return card

    def _build_help_page(self):
        """Every key and every command anyone can type in chat, with what it does."""
        page = self.pages["Help"]
        tk.Label(page, text="Everything you can press, and everything players can type in chat. "
                            "Part of a name is enough: !who iva finds Ivan.",
                 font=self.small, fg=MUTED, bg=BG, anchor="w").pack(fill="x", padx=12, pady=(10, 0))
        grid = self._card_grid(page)
        keys = ((self.cfg["toggle_key"], "Show or hide the scanner window."),
                ("F8", "Unlock the translations to move them with the mouse. F8 again locks them."))
        self._help_card(grid, 0, 0, "Keys (work in the game)", keys)
        info = [("!who <name>", "A player's summary and stats, in two messages.")]
        info += [usage_about for usage_about in INFO_COMMANDS.values()]
        self._help_card(grid, 0, 1, "Information", info, "Switch each one off or on on the Chat page.")
        self._help_card(grid, 1, 0, "Translate", SPEAK_COMMANDS, "Switch !speak off or on on the Chat page. "
                        "Mute one player's !speak in their panel (click them on the Players page).")
        self._help_card(grid, 1, 1, "HoovyGPT", HEAVY_COMMANDS, "Switch it on with HoovyGPT + Duels on the Duels page.")
        self._help_card(grid, 2, 0, "Duels", DUEL_COMMANDS, "Duels work while HoovyGPT + Duels is on.").grid(columnspan=2)

    def stop_duels_from_page(self):
        """The Stop all duels button: what "!duel stopall" does, said in chat the same way."""
        if not self.chat_duels:
            self.notify("No duels running")
        elif self.me in self.players:
            self.stop_all_duels(self.me)
        else:
            self.chat_duels = []  # you're not in a match: nothing to say it in
        self.dirty = True

    def _build_chat_page(self):
        """Everything the scanner says in chat: what posts by itself, and the commands players type."""
        page = self.pages["Chat"]
        tk.Label(page, text="What the scanner says in chat. The switches post by themselves; the chat commands "
                            "answer when a player types them. All of it waits behind what you say yourself.",
                 font=self.small, fg=MUTED, bg=BG, anchor="w").pack(fill="x", padx=12, pady=(10, 0))
        grid = self._card_grid(page)
        self.announcer_button = self._setting(grid, 0, 0, "Announcer: first blood, gardens, humiliations, rage-quits",
                                              "Calls these out in chat when they happen.",
                                              self.toggle_announcer, example=CHAT_EXAMPLES["announcer"])
        self.update_announcer_button()
        self.ez_button = self._setting(grid, 0, 1, '"ez" after your kills', 'Says "ez <name>" for every kill you make.',
                                       self.toggle_ez_mode, example=CHAT_EXAMPLES["ez"])
        self.update_ez_button()
        self.translate_button = self._setting(grid, 1, 0, "Post translations in chat",
                                              "Says every translation for everyone (not your own lines).",
                                              self.toggle_translate_to_chat, example=CHAT_EXAMPLES["translate"])
        self.update_translate_button()
        self.beef_button = self._setting(grid, 1, 1, "", "Announces each kill between these two countries, with the score.",
                                         self.toggle_country_beef, example=CHAT_EXAMPLES["beef"])
        self.update_beef_button()
        self.idle_button = self._setting(
            grid, 2, 0, "Auto-reconnect when idle",
            "TF2 kicks you after 3 minutes idle. This types retry 10 seconds before, so you reconnect first.",
            self.toggle_idle_rejoin, example=CHAT_EXAMPLES["idle"])
        self.update_idle_button()
        self.speak_mutes_button = self._setting(
            grid, 2, 1, "!speak: muted players", "Players you muted in their panel (Mute !speak). Click to unmute them all.",
            self.unmute_all_speak)
        self.update_speak_mutes_button()
        # One pill per info command: blue answers, gray doesn't.
        info = round_card(tk.Frame(page), CARD_BG, BG)
        info.pack(fill="x", padx=11, pady=(0, 11))
        tk.Label(info, text="Chat commands", font=self.bold, fg=TEXT, bg=CARD_BG, anchor="w").pack(
            fill="x", padx=16, pady=(12, 0))
        tk.Label(info, text="What anyone can type in chat. Click one to switch it off or on. The Help page says "
                            "what each one does.", font=self.small,
                 fg=MUTED, bg=CARD_BG, anchor="w").pack(fill="x", padx=16)
        pills = tk.Frame(info, bg=CARD_BG)
        pills.pack(fill="x", padx=16, pady=(8, 12))
        self.info_buttons = {}
        # !who first: its own setting (who_command), but switched here like the others.
        self.who_button = Pill(pills, "!who <name>", self.mono, TEXT, BUTTON_BG, under=CARD_BG, padx=10, pady=4,
                               radius=10, cursor="hand2")
        self.who_button.pack(side="left", padx=(0, 6))
        self.who_button.bind("<Button-1>", lambda e: self.toggle_who_command())
        self.update_who_button()
        self.speak_button = Pill(pills, "!speak", self.mono, TEXT, BUTTON_BG, under=CARD_BG, padx=10, pady=4,
                                 radius=10, cursor="hand2")
        self.speak_button.pack(side="left", padx=(0, 6))
        self.speak_button.bind("<Button-1>", lambda e: self.toggle_translate_command())
        self.update_speak_button()
        for command, (usage, about) in INFO_COMMANDS.items():
            pill = Pill(pills, usage, self.mono, TEXT, BUTTON_BG, under=CARD_BG, padx=10, pady=4,
                        cursor="hand2")
            pill.pack(side="left", padx=(0, 6))
            pill.bind("<Button-1>", lambda e, command=command: self.toggle_info_command(command))
            self.info_buttons[command] = pill
        self.update_info_buttons()

    def _build_cheat_page(self):
        """The live cheat check: its switches, the last checks, and what it found, as a summary and
        as a list to click through like demo-analysis's gui.exe."""
        page = self.pages["Cheat check"]
        grid = self._card_grid(page)
        self.demo_check_button = self._setting(
            grid, 0, 0, "Live cheat check", "Checks the demo TF2 records about once a minute, with demo-analysis.",
            self.toggle_demo_check)
        self.demo_keep_button = self._setting(
            grid, 0, 1, "Keep only demos with a cheater", "Deletes a finished match's demo if nothing was found.",
            self.toggle_demo_keep)
        self.demo_record_button = self._setting(
            grid, 1, 0, "Record only with a flagged player", RECORD_ONLY_FLAGGED_ABOUT,
            self.toggle_record_only_flagged, span=2)
        self.update_demo_buttons()
        state = tk.Frame(page, bg=BG)
        state.pack(fill="x", padx=12)
        self.demo_state_label = tk.Label(state, font=self.small, fg=MUTED, bg=BG, anchor="w")
        self.demo_state_label.pack(side="left")
        FlatButton(state, "Check now", self.check_demo_now, self.small).pack(side="right")
        self.demo_record_label = tk.Label(state, font=self.small, fg=MUTED, bg=BG, anchor="w")
        self.demo_record_label.pack(side="left", padx=(16, 0))
        # The last checks: when, which demo, how much of the match it held, and what was found.
        self.demo_log_label = tk.Label(page, font=self.mono, fg=TEXT, bg=BG, anchor="w", justify="left")
        self.demo_log_label.pack(fill="x", padx=12, pady=(4, 0))

        bar = tk.Frame(page, bg=BG)
        bar.pack(fill="x", padx=12, pady=(10, 4))
        self._section_label(bar, "Found").pack(side="left")
        FlatButton(bar, "Open demos folder", self.open_demos_folder, self.small).pack(side="right")
        FlatButton(bar, "Open...", self.open_detections_file, self.small).pack(side="right", padx=(0, 4))
        FlatButton(bar, "Export evidence", self.export_evidence, self.small).pack(side="right", padx=(0, 4))
        FlatButton(bar, "Copy", self.copy_demo_lines, self.small).pack(side="right", padx=(0, 4))
        FlatButton(bar, "Votekick", self.votekick_demo_player, self.small, danger=True).pack(side="right", padx=(0, 4))
        panes = tk.Frame(page, bg=BG)
        panes.pack(fill="x", padx=12, pady=(0, 12))
        mono = self.mono
        boxes = dict(font=mono, fg=TEXT, bg=CARD_BG, relief="flat", highlightthickness=0, selectbackground=SELECTED_BG,
                     selectforeground=TEXT)
        self.demo_summary_box = tk.Text(panes, width=60, height=8, wrap="none", padx=8, pady=6, **boxes)
        # Right of the summary: what each check that was found looks for.
        self.demo_meaning_box = tk.Text(panes, width=40, height=8, wrap="word", padx=8, pady=6,
                                        **dict(boxes, fg=TEXT2))
        self.demo_players_box = tk.Listbox(panes, width=24, height=12, exportselection=False, activestyle="none", **boxes)
        self.demo_dets_box = tk.Listbox(panes, width=24, height=12, exportselection=False, activestyle="none", **boxes)
        self.demo_details_box = tk.Text(panes, width=30, height=12, wrap="word", padx=8, pady=6, **boxes)
        self._section_label(panes, "Summary").grid(row=0, column=0, columnspan=2, sticky="w")
        self._section_label(panes, "What these mean").grid(row=0, column=2, sticky="w", padx=(6, 0))
        self.demo_summary_box.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(0, 8))
        self.demo_meaning_box.grid(row=1, column=2, sticky="nsew", padx=(6, 0), pady=(0, 8))
        for column, (box, title) in enumerate(((self.demo_players_box, "Players"), (self.demo_dets_box, "Detections"),
                                               (self.demo_details_box, "Details"))):
            self._section_label(panes, title).grid(row=2, column=column, sticky="w", padx=(0 if column == 0 else 6, 0))
            box.grid(row=3, column=column, sticky="nsew", padx=(0 if column == 0 else 6, 0))
        panes.columnconfigure(2, weight=1)
        self._set_text(self.demo_summary_box, "Nothing found yet.")
        self._set_text(self.demo_details_box, "Click a player, then a detection.")
        self.demo_players_box.bind("<<ListboxSelect>>", lambda e: self._demo_player_picked())
        self.demo_players_box.bind("<Double-Button-1>", lambda e: self._demo_open_profile())
        self.demo_dets_box.bind("<<ListboxSelect>>", lambda e: self._demo_detection_picked())
        for box in (self.demo_summary_box, self.demo_players_box, self.demo_dets_box, self.demo_details_box):
            self._make_copyable(box)
        self.demo_summary_shown = ""
        self.demo_browser_key = None
        self.demo_view_sids, self.demo_view_dets, self.demo_picked_sid = [], [], None

    def _make_copyable(self, box):
        """Ctrl+C copies what's selected in box, and right-click offers Copy and Copy all. A click
        gives the window keyboard focus first: it doesn't take it by itself, so Ctrl+C went nowhere."""
        box.bind("<ButtonPress-1>", lambda e: box.focus_force(), add="+")
        for key in ("<Control-c>", "<Control-C>"):
            box.bind(key, lambda e: (self.copy_from(box), "break")[1])
        box.bind("<Button-3>", lambda e: self._copy_menu(box, e))

    def copy_from(self, box, everything=False):
        """Copies the selection in box, or all of it (also when nothing's selected). For the
        Players list that's the player's one line, as Copy gives it."""
        if box is self.demo_players_box and self.demo_view:
            sids = self.demo_view_sids if everything else [self.demo_view_sids[i] for i in box.curselection()]
            lines = copy_lines({"detections": [det for det in self.demo_view["result"]["detections"]
                                               if det["player"] in sids]}, self.demo_view["names"])
            text = "\n".join(lines)
        elif isinstance(box, tk.Listbox):
            picked = range(box.size()) if everything else box.curselection()
            text = "\n".join(box.get(i) for i in picked)
        else:
            try:
                text = box.get("1.0", "end-1c") if everything else box.get("sel.first", "sel.last")
            except tk.TclError:  # nothing selected
                text = box.get("1.0", "end-1c")
        if text:
            self.copy(text)
            self.notify("Copied")

    def _copy_menu(self, box, e):
        menu = tk.Menu(self.root, tearoff=0, bg=BAR_BG, fg=TEXT, activebackground=SELECTED_BG,
                       activeforeground=TEXT, font=self.small)
        menu.add_command(label="Copy", command=lambda: self.copy_from(box))
        menu.add_command(label="Copy all", command=lambda: self.copy_from(box, everything=True))
        menu.tk_popup(e.x_root, e.y_root)

    def _set_text(self, box, text):
        """Replaces a read-only Text's contents; it stays selectable, so it can be copied."""
        box.config(state="normal")
        box.delete("1.0", "end")
        box.insert("1.0", text)
        box.config(state="disabled")

    def refresh_demo_browser(self):
        """Fills the Players list from the shown result, keeping the picked player when they're still in it."""
        view = self.demo_view
        key = view and (view["demo"], len(view["result"].get("detections", [])), tuple(sorted(view["names"].items())))
        if key == self.demo_browser_key:
            return
        self.demo_browser_key = key
        counts = count_checks(view["result"].get("detections", [])) if view else {}
        self.demo_view_sids = sorted(counts, key=lambda sid: -sum(counts[sid].values()))
        box = self.demo_players_box
        box.delete(0, "end")
        for sid in self.demo_view_sids:
            box.insert("end", f"{view['names'].get(sid, sid)} ({sum(counts[sid].values())})")
        if self.demo_view_sids:
            index = self.demo_view_sids.index(self.demo_picked_sid) if self.demo_picked_sid in self.demo_view_sids else 0
            box.selection_set(index)
            self._demo_player_picked()

    def _demo_player_picked(self):
        """A click on a player: their detections, in the order they happened."""
        picked = self.demo_players_box.curselection()
        if not picked:
            return
        self.demo_picked_sid = self.demo_view_sids[picked[0]]
        self.demo_view_dets = sorted((det for det in self.demo_view["result"]["detections"]
                                      if det["player"] == self.demo_picked_sid), key=lambda det: det["tick"])
        box = self.demo_dets_box
        box.delete(0, "end")
        for det in self.demo_view_dets:
            box.insert("end", f"{det['tick']}: {det['algorithm']}")
        if self.demo_view_dets:
            box.selection_set(0)
            self._demo_detection_picked()

    def _demo_detection_picked(self):
        """A click on a detection: everything about it."""
        picked = self.demo_dets_box.curselection()
        if picked:
            self._set_text(self.demo_details_box, detection_details(
                self.demo_view_dets[picked[0]], self.demo_view["names"], self.demo_view["user_names"],
                self.demo_view.get("pings")))

    def _demo_open_profile(self):
        """A double-click on a player opens their Steam profile."""
        if self.demo_picked_sid:
            webbrowser.open(f"https://steamcommunity.com/profiles/{self.demo_picked_sid}")

    def _build_status_page(self):
        """The mini HUD's switch, what each connection is doing, whether every feature works, and the
        keys that work in the game."""
        grid = self._card_grid(self.pages["Status"])
        self.hud_button = self._setting(
            grid, 0, 0, "Mini HUD over the game",
            "One thin line at the top of your screen: the enemy line-up, their Medics (MEDIC DOWN - PUSH) "
            "and their Spies.", self.toggle_hud)
        self.hud_move_button = self._setting(
            grid, 0, 1, "Move the mini HUD", "Press, drag the line where you can read it, then press Done.",
            self.toggle_hud_move)
        self.hud_move_button.show("Move")
        columns = tk.Frame(self.pages["Status"], bg=BG)
        columns.pack(fill="x", padx=12, pady=10)
        columns.columnconfigure((0, 1), weight=1, uniform="status")
        left = tk.Frame(columns, bg=BG)
        left.grid(row=0, column=0, sticky="new")
        self._section_label(left, "Connections").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 4))
        self.status_rows = {}
        for row, (name, about) in enumerate((("TF2", "RCON"), ("Steam", "bans, hours, age"),
                                             ("History", "server bans"), ("Lists", "cheater lists")), 1):
            light = tk.Label(left, text="\u25cf", font=self.small, fg=FAINT, bg=BG)
            light.grid(row=row, column=0, sticky="w", padx=(0, 6))
            tk.Label(left, text=f"{name}: {about}", font=self.small, fg=TEXT, bg=BG, anchor="w").grid(row=row, column=1, sticky="w")
            state = tk.Label(left, font=self.small, fg=MUTED, bg=BG, anchor="w")
            state.grid(row=row, column=2, sticky="w", padx=(12, 0))
            self.status_rows[name] = light, state
        self._section_label(left, "Chat this session").grid(row=5, column=0, columnspan=3, sticky="w", pady=(10, 2))
        self.status_chat = tk.Label(left, font=self.small, fg=TEXT, bg=BG, anchor="w")
        self.status_chat.grid(row=6, column=0, columnspan=3, sticky="w")
        # One line per feature: green works, orange works partly, red doesn't, gray is switched off.
        self._section_label(left, "Is everything working?").grid(row=7, column=0, columnspan=3, sticky="w", pady=(10, 4))
        self.health_rows = {}
        for row, name in enumerate(HEALTH_ROWS, 8):
            light = tk.Label(left, text="\u25cf", font=self.small, fg=FAINT, bg=BG)
            light.grid(row=row, column=0, sticky="nw", padx=(0, 6))
            tk.Label(left, text=name, font=self.small, fg=TEXT, bg=BG, anchor="w").grid(row=row, column=1, sticky="nw")
            state = tk.Label(left, font=self.small, fg=MUTED, bg=BG, anchor="w", justify="left", wraplength=300)
            state.grid(row=row, column=2, sticky="w", padx=(12, 0))
            self.health_rows[name] = light, state
        right = tk.Frame(columns, bg=BG)
        right.grid(row=0, column=1, sticky="new", padx=(16, 0))
        self._section_label(right, "Keys").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        for row, (key, about) in enumerate(((self.cfg["toggle_key"], "Show or hide this window"),
                                            ("F8", "Move the translation overlay")), 1):
            Pill(right, key, self.mono, TEXT, BG, padx=8, pady=2, outline=BORDER).grid(row=row, column=0, sticky="w", pady=2)
            tk.Label(right, text=about, font=self.small, fg=TEXT, bg=BG, anchor="w").grid(row=row, column=1, sticky="w", padx=(8, 0))
        self._section_label(right, "Typed by players in chat").grid(row=7, column=0, columnspan=2, sticky="w", pady=(10, 2))
        tk.Label(right, text="!duel  !speak  !who\n" + "  ".join(u.split(" ")[0] for u, _ in INFO_COMMANDS.values()), font=self.small, fg=TEXT, bg=BG, anchor="w",
                 justify="left").grid(row=8, column=0, columnspan=2, sticky="w")

    def update_info_buttons(self):
        for command, pill in self.info_buttons.items():
            on = self.cfg["info_commands"].get(command, True)
            pill.configure(fg=ON_FG if on else MUTED)
            pill.set_fill(ON_BG if on else BG, ON_BG if on else BORDER)

    def feature_health(self):
        """(name, "ok" | "warn" | "bad" | "off", what's going on) for every feature on the Status
        page, so you can see what's off, and why, without asking."""
        cfg, connected = self.cfg, self.rcon_state == "connected"
        waiting = "waits for TF2 (not connected yet)"
        muted = len(cfg["speak_muted"])
        speak = "on" if cfg["translate_command"] else "off: switch it on on the Chat page"
        demo = self.demo_state
        return [
            ("Duels", "off" if not self.ai_on else "ok" if connected else "warn",
             "off: switch them on on the Duels page" if not self.ai_on else
             f"on, {len(self.chat_duels)} running" if connected else f"on, {waiting}"),
            ("!speak", "off" if not cfg["translate_command"] else "ok" if connected else "warn",
             (speak if connected or not cfg["translate_command"] else f"on, {waiting}")
             + (f" \u00b7 {muted} player{'s' * (muted != 1)} muted" if muted else "")),
            ("!who", "off" if not cfg["who_command"] else "ok" if connected else "warn",
             "off: switch it on on the Chat page" if not cfg["who_command"] else "on" if connected else f"on, {waiting}"),
            ("Info commands",) + self.info_health(connected, waiting),
            ("Translator",) + translator_health(),
            ("Cheat check", "off" if demo == "off" else "bad" if "missing" in demo or "couldn't" in demo else "ok", demo),
        ]

    def info_health(self, connected, waiting):
        on = [usage.split(" ")[0] for command, (usage, _) in INFO_COMMANDS.items()
              if self.cfg["info_commands"].get(command, True)]
        if not on:
            return "off", "all off: switch them on on the Chat page"
        text = f"{len(on)} of {len(INFO_COMMANDS)} on" + (f" ({', '.join(on)})" if len(on) < len(INFO_COMMANDS) else "")
        return ("ok", text) if connected else ("warn", f"{text}, {waiting}")

    def applicable(self, p):
        """The buttons that would do something for this player; the rest are grayed out."""
        kills = self.kills.get(p.sid, (0, 0))
        crits = self.all_crits.get(p.sid, (0, 0))
        checks = {
            "kick": self.team_of(p) != "ENEMY",  # votes only work on your own team (incl. yourself)
            "say": True,
            "stats": bool(kills[1] or crits[1] or self.gardens.get(p.sid) or self.player_class(p)
                          or self.player_streak(p)[1] or self.weapons.get(p.sid)),
            "friends": bool(lobby_friends(p, list(self.players.values()))),
            "ip": True,  # a random reserved address (fake_ipv4): looks real, can't belong to anyone
            "mark": p.sid != self.me,
            "mute": p.sid != self.me,
            "history": True,
        }
        return {key for key, ok in checks.items() if ok}

    def render_actions(self):
        """Updates the selected player's panel, only when something changed."""
        self.show_player_panel()
        p = self.players.get(self.selected)
        marked = p is not None and str(p.sid) in self.marks
        self.enabled = self.applicable(p) if p else set()
        self.width_spacer.config(width=self.window_width())  # the table may have grown
        why = explain_flags(self.flags.get(p.sid, []) + profile_flags(p.profile)) if p else ""
        about = self.player_details(p) if p else ""
        muted = p is not None and p.sid in self.cfg["speak_muted"]
        state = (p and (p.sid, p.name), marked, muted, self.feedback, frozenset(self.enabled), why, about)
        if state == self.actions_state:
            return
        self.actions_state = state
        self.feedback_label.config(text=self.feedback)
        self.why_label.config(text=why)
        self.player_about.config(text=about)
        self.player_title.config(text=p.name if p else "")
        self.buttons["mark"].config(text="Unmark" if marked else "Mark cheater")
        self.buttons["mute"].config(text="Unmute !speak" if muted else "Mute !speak")
        for key, button in self.buttons.items():
            button.set_enabled(key in self.enabled)
        self.why_label.pack_forget()
        if why:
            self.why_label.pack(fill="x", padx=12, pady=(6, 0), before=self.player_buttons)

    def show_player_panel(self):
        """The panel right of the list is there while a player is selected (and the window isn't
        minimized), so a plain click on a row opens it."""
        wanted = self.selected in self.players and not self.cfg["scanner_minimized"]
        if wanted != bool(self.actions.winfo_manager()):
            if wanted:
                self.actions.pack(side="right", fill="y", padx=(0, 6), pady=(0, 6), before=self.table)
            else:
                self.actions.pack_forget()

    def player_details(self, p):
        """One line for the player you clicked: their team and class, then what the list may
        not show (streak, headshots, crits, account age, profile)."""
        cells = dict(zip(COLUMNS, self.row_cells(p)))

        def known(column, label=""):
            text = cells[column][0]
            return f"{label}{text}" if text not in BLANK_CELLS else ""
        return " \u00b7 ".join(s for s in (
            self.team_of(p), self.player_class(p), known("TF2", ""), known("Age", "account "),
            known("Streak", "streak "), known("HS", "headshots "), known("Crit", "crits "), known("Duel", "duels "),
            known("Profile", "profile: ")) if s and s not in BLANK_CELLS)

    def sized(self):
        """True once you've given the window a size by dragging (or maximized it); False while it
        fits its contents."""
        return bool(self.maximized or self.cfg["scanner_width"] and self.cfg["scanner_height"])

    def window_size(self):
        """(width, height) it has: the screen while maximized, else the size you dragged it to."""
        if self.maximized:
            return work_area(self.root)[2:]
        return self.cfg["scanner_width"], self.cfg["scanner_height"]

    def window_width(self):
        """The width you dragged it to, or, while it fits its contents, the table's widest so far
        this match (so scrolling to longer names doesn't make it jump)."""
        if self.sized():
            return self.window_size()[0]
        self.table_widest = max(getattr(self, "table_widest", 0), self.table.winfo_reqwidth() + 8)
        return max(self.table_widest, 400)

    def visible_rows(self):
        """How many table rows fit in the window you sized, the rest by scrolling; 0 = all of them."""
        height = self.table.winfo_height()
        if not self.sized() or height <= 1:
            return 0
        side = self.sides["mine"]
        header = side.header_labels["Player"].winfo_reqheight()
        strip = max(s.strip.winfo_reqheight() if s.strip.winfo_manager() else 0 for s in self.sides.values())
        top = header + side.title.winfo_reqheight() + strip + 4  # the accent line, title, strip and headers
        return max(1, (height - top) // (self.row_height or header + 4))

    def _table_resized(self, e):
        """The list got a new height: in a sized window, how many rows fit is worked out again.
        Only the rows are laid out again (no flags worked out again), and only once the size has
        stopped changing for a moment, so dragging the window stays smooth."""
        if self.sized() and e.height != self.table_height:
            self.table_height = e.height
            if self.rows_job:
                self.root.after_cancel(self.rows_job)
            self.rows_job = self.root.after(60, self._rows_after_resize)

    def _rows_after_resize(self):
        self.rows_job = None
        if self.visible:
            self.render()

    MIN_SIZE = (320, 110)  # px: the title bar and tabs still fit
    rows_job = resize_job = None
    resize_target = None

    def _build_resize_handles(self):
        """A thin strip along every edge and a small square in every corner to drag the window to
        any size from. Double-click the bottom-right corner to fit it to what's in it again."""
        root = self.root
        self.grip = tk.Label(root, text="\u2198", font=self.bold, fg=FAINT, bg=BG, cursor="size_nw_se")
        self.right_edge = tk.Frame(root, bg=BG, width=4, cursor="sb_h_double_arrow")
        self.left_edge = tk.Frame(root, bg=BAR_BG, width=4, cursor="sb_h_double_arrow")
        self.top_edge = tk.Frame(root, bg=BAR_BG, height=4, cursor="sb_v_double_arrow")
        self.corners = {"nw": tk.Frame(root, bg=BAR_BG, width=8, height=8, cursor="size_nw_se"),
                        "ne": tk.Frame(root, bg=BAR_BG, width=8, height=8, cursor="size_ne_sw"),
                        "sw": tk.Frame(root, bg=BAR_BG, width=8, height=8, cursor="size_ne_sw")}
        # The letters say which sides move with the mouse: n(orth) = top, e = right, s = bottom, w = left.
        handles = {"se": self.grip, "e": self.right_edge, "w": self.left_edge, "n": self.top_edge,
                   "s": self.bottom_edge, **self.corners}
        for mode, handle in handles.items():
            handle.bind("<ButtonPress-1>", self._resize_start)
            handle.bind("<B1-Motion>", lambda e, mode=mode: self._resize_move(e, mode))
            handle.bind("<ButtonRelease-1>", self._resize_end)
        self.grip.bind("<Double-Button-1>", lambda e: self.fit_to_contents())

    def _resize_start(self, e):
        if self.maximized:
            self.toggle_maximized()  # dragging an edge of a maximized window: back to a normal one
        self.resizing = (e.x_root, e.y_root, self.root.winfo_width(), self.root.winfo_height(),
                         self.root.winfo_x(), self.root.winfo_y())

    def _resize_move(self, e, mode="se"):
        """Dragging an edge or a corner: mode holds the sides that follow the mouse ("w" the left
        edge, "se" the bottom-right corner...). The opposite side stays where it is, so dragging
        the left or the top edge also moves the window. The mouse sends far more moves than the
        screen can show: the newest size is applied once per frame (about 60 a second)."""
        x0, y0, w0, h0, left, top = self.resizing
        dx, dy = e.x_root - x0, e.y_root - y0
        was_sized = self.sized()
        width, height = w0, h0
        if "e" in mode:
            width = max(self.MIN_SIZE[0], w0 + dx)
        if "w" in mode:
            width = max(self.MIN_SIZE[0], w0 - dx)
            left += w0 - width  # the right edge stays put
        if "s" in mode:
            height = max(self.MIN_SIZE[1], h0 + dy)
        if "n" in mode:
            height = max(self.MIN_SIZE[1], h0 - dy)
            top += h0 - height  # the bottom edge stays put
        self.cfg["scanner_width"], self.cfg["scanner_height"] = width, height
        if not was_sized:
            self.show_body()  # from fitting its contents to a set size: the layout changes
        self.resize_target = f"{width}x{height}+{left}+{top}"
        if not self.resize_job:
            self.resize_job = self.root.after(16, self._apply_resize)

    def _apply_resize(self):
        self.resize_job = None
        self.root.geometry(self.resize_target)

    def toggle_maximized(self):
        """The maximize button or a double-click on the title bar: the whole screen it's on
        (taskbar left free), and back to where and how big it was."""
        if self.maximized:
            x, y = self.maximized
            self.maximized = None
            self.root.geometry(f"+{x}+{y}")
        else:
            self.maximized = self.root.winfo_x(), self.root.winfo_y()
            left, top, _, _ = work_area(self.root)
            self.root.geometry(f"+{left}+{top}")
            if self.cfg["scanner_minimized"]:
                self.cfg["scanner_minimized"] = False
        self.maximize_button.config(text="\ue923" if self.maximized else "\ue922")
        self.show_body()
        self.dirty = True

    def fit_to_contents(self):
        """Double-click on the corner: the window fits what's in it again."""
        self.cfg["scanner_width"] = self.cfg["scanner_height"] = 0
        self.table_widest = 0
        save_config(self.cfg)
        self.show_body()
        self.dirty = True

    def _scroll(self, e, key=None):
        """The mouse wheel scrolls the half it's over, or both halves anywhere else."""
        if self.sized():
            for k in (key,) if key else SIDES:
                self.sides[k].scroll += -2 if e.delta > 0 else 2
            self.render()

    def toggle_minimized(self):
        self.cfg["scanner_minimized"] = not self.cfg["scanner_minimized"]
        save_config(self.cfg)
        self.show_body()

    def show_body(self):
        """Everything under the title bar, or nothing of it while minimized. A window you sized
        keeps that size: the player's buttons stay at the bottom and the list scrolls; otherwise
        the window fits what's in it."""
        minimized = self.cfg["scanner_minimized"]
        self.minimize_button.config(text="\u25a1" if minimized else "\u2013")
        for w in (self.tab_bar, self.page_area, self.width_spacer, self.bottom_edge,
                  self.toolbar, self.table, self.actions):
            w.pack_forget()
        for w in (self.grip, self.right_edge, self.left_edge, self.top_edge, *self.corners.values()):
            w.place_forget()
        if minimized:
            self.root.geometry("")  # just the title bar
            return
        self.bottom_edge.pack(fill="x", side="bottom")  # first: it runs under the sidebar too
        self.tab_bar.pack(side="left", fill="y")
        if not self.sized():
            self.width_spacer.pack(side="bottom")  # as wide as the table has been
        self.page_area.pack(fill="both", expand=True)
        self.toolbar.pack(fill="x")
        self.table.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.show_player_panel()
        self.right_edge.place(relx=1.0, rely=0, relheight=1.0, anchor="ne")
        self.left_edge.place(relx=0, rely=0, relheight=1.0, anchor="nw")
        self.top_edge.place(relx=0, rely=0, relwidth=1.0, anchor="nw")
        self.grip.place(relx=1.0, rely=1.0, anchor="se")
        self.corners["nw"].place(relx=0, rely=0, anchor="nw")
        self.corners["ne"].place(relx=1.0, rely=0, anchor="ne")
        self.corners["sw"].place(relx=0, rely=1.0, anchor="sw")
        for w in (self.grip, *self.corners.values()):
            w.lift()  # a corner wins from the two edges it sits on
        self.root.geometry("{}x{}".format(*self.window_size()) if self.sized() else "")

    def _resize_end(self, e):
        if self.resize_job:  # the last move, not yet applied
            self.root.after_cancel(self.resize_job)
            self._apply_resize()
        self.cfg["scanner_width"] = self.window_width()  # what it really became (the table's the minimum)
        self.cfg["x"], self.cfg["y"] = self.root.winfo_x(), self.root.winfo_y()  # the left or top edge moved it
        save_config(self.cfg)
        self.render()

    def select_row(self, key, row):
        sids = self.sides[key].row_sids
        if row < len(sids) and sids[row] is not None:  # not a team header
            self.select(sids[row])

    def select(self, sid):
        self.selected = None if self.selected == sid else sid
        if self.visible:
            self.render()  # right away instead of on the next tick

    def notify(self, text):
        self.feedback = text
        self.render_actions()
        self.root.after(3000, self._clear_feedback, text)

    def _clear_feedback(self, text):
        if self.feedback == text:
            self.feedback = ""
            self.dirty = True

    def copy(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
