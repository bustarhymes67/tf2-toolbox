"""The texts and tables the web window's pages share (web_*.py), the click-through alert at the top of
the screen (Toast), and ScreensMixin: the part of the App behind those pages (which page is open, who
the player list shows, the selected player, the title bar's feedback)."""

import ctypes
import re
import time
import tkinter as tk
import webbrowser
from collections import Counter

from tf2_translator import set_click_through, translator_health

from settings import (ACCENT, BAD, BG, DANGER_FG, FAINT, GOOD, KEY_COLOR, MUTED, SEVERITY_FG, TEAM_ACCENT, TEAM_FG,
                      TEXT, TEXT2, WAITING, mono_family, save_config)
from game_log import weapon_name
from player_flags import crit_flag, fmt_age, fmt_hours, headshot_flag, lobby_friends, profile_text
from info_commands import INFO_COMMANDS


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
# Each team gets its own half of the window, so by default it shows fewer columns (the "columns"
# setting). The Columns menu switches each of these on or off; the flag stripe and the name always show.
PICKABLE_COLUMNS = tuple(c for c in COLUMNS if c not in ("Mark", "Player"))
COLUMN_NAMES = {"Ctry": "Country", "TF2": "Hours", "HS": "Headshot %", "Crit": "Crit %"}
HEALTH_ROWS = ("Duels", "!speak", "!who", "Info commands", "Translator", "Cheat check")  # the Status page's check
FILTERS = (("all", "Everyone"), ("flagged", "Flagged"), ("cheaters", "Cheaters"), ("new", "New accounts"))
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


def short_cell(column, cell):
    """(text, colour) for the list, with a long Flags cell cut short, keeping its "+2"."""
    text, fg = cell[:2]
    if column != "Flags" or len(text) <= FLAGS_CELL_CHARS:
        return cell
    more = text[text.rfind("  +"):] if "  +" in text else ""
    return (text[:FLAGS_CELL_CHARS - len(more) - 1].rstrip() + "\u2026" + more, fg) + tuple(cell[2:])


# The "Record only with a flagged player" switch's text, on the Cheat check page.
RECORD_ONLY_FLAGGED_ABOUT = ("TF2 records a demo only while someone flagged is in your match, so clean matches "
                             "never fill your disk.")

# Clicking a header sorts by it: these go A to Z (or ALLY first), all others biggest first.
ASCENDING_COLUMNS = {"Ctry", "Class", "Player"}
CLASS_ORDER = ["Scout", "Soldier", "Pyro", "Demo", "Heavy", "Engineer", "Medic", "Sniper", "Spy"]


class Toast:
    """Click-through alert lines at the top of the screen, in the main window's Tactical look: a
    near-black box with a thin line and a bar in the alert's colour, a small label in capitals with
    the time, and the text."""

    SECONDS = 8
    LABEL_FG = {3: DANGER_FG}   # the strongest alerts: the lighter red of the danger buttons, as in the window
    MIN_WIDTH = 360

    def __init__(self, root, font, label_font=None):
        """A see-through window at the top of the screen that clicks pass through."""
        self.font, self.label_font = font, label_font or font
        size = label_font[1] if isinstance(label_font, tuple) and len(label_font) > 1 else 9
        self.time_font = (mono_family(root), size)
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
        self.items = (self.items + [(time.time() + self.SECONDS, text, severity)])[-4:]
        self.redraw()

    def tick(self):
        alive = [i for i in self.items if i[0] > time.time()]
        if len(alive) != len(self.items):
            self.items = alive
            self.redraw()

    @staticmethod
    def _spaced(text):
        """Capitals with a little room between the letters, like the window's labels."""
        return "\u200a".join(text.upper())

    @staticmethod
    def _dim(colour, share=0.6):
        """The colour mixed into the dark background (a see-through line, as in the window)."""
        a, b = int(colour[1:], 16), int(BG[1:], 16)
        mix = [round(((a >> s) & 255) * share + ((b >> s) & 255) * (1 - share)) for s in (16, 8, 0)]
        return "#%02x%02x%02x" % tuple(mix)

    def redraw(self):
        """Draws the current alerts, centred one under the other."""
        c = self.canvas
        c.delete("all")
        y = 2
        for expires, text, severity in self.items:
            colour = SEVERITY_FG[severity] if severity >= 1 else ACCENT
            label = c.create_text(0, y + 8, text=self._spaced("Alert" if severity >= 1 else "Toolbox"),
                                  anchor="nw", font=self.label_font, fill=self.LABEL_FG.get(severity, colour))
            when = c.create_text(0, y + 8, text=time.strftime("%H:%M:%S", time.localtime(expires - self.SECONDS)),
                                 anchor="ne", font=self.time_font, fill=MUTED)
            item = c.create_text(0, c.bbox(label)[3] + 3, text=text, anchor="nw", font=self.font, fill=TEXT,
                                     width=self.w - 32)
            label_w = c.bbox(label)[2] - c.bbox(label)[0] + 24 + c.bbox(when)[2] - c.bbox(when)[0]
            inner = max(label_w, c.bbox(item)[2] - c.bbox(item)[0], self.MIN_WIDTH - 28)
            width = min(inner + 28, self.w - 2)
            x0 = (self.w - width) // 2
            c.move(label, x0 + 16, 0)
            c.move(item, x0 + 16, 0)
            c.move(when, x0 + width - 12, 0)
            bottom = c.bbox(item)[3] + 8
            box = c.create_rectangle(x0, y, x0 + width, bottom, fill=BG, outline=self._dim(colour))
            bar = c.create_rectangle(x0, y, x0 + 4, bottom + 1, fill=colour, outline="")
            c.tag_lower(bar)
            c.tag_lower(box)
            y = bottom + 6
        height = max(y, 1)
        if height != self.h:  # as tall as its alerts, so none is cut off; it stays where it is
            self.h = height
            self.win.geometry(f"{self.w}x{self.h}")

def status_colour(state):
    """The colour of a status light for a state like "connected" or "no key"."""
    if state in ("ok", "connected") or "known" in state:
        return GOOD
    if state in ("starting", "loading", "not connected"):
        return WAITING
    return FAINT if state == "no key" else BAD

class ScreensMixin:
    """The part of the App behind the web window's pages (web_*.py): which page is open, who the
    player list shows and in what order, the selected player, the feedback in the title bar."""

    def set_visible(self, visible):
        """Shows or hides the window (F9). Where it was is saved when it hides."""
        self.visible = visible
        if visible:
            self.dirty = True
            self.web_pushed_at = 0.0
        if getattr(self, "web", None):
            self.web.set_visible(visible)
            if not visible:
                self.cfg["x"], self.cfg["y"] = self.web.where()[:2]
                save_config(self.cfg)

    def show_page(self, name):
        """Opens a page. It's remembered for the next start."""
        name = "Duels" if name == "HoovyGPT" else name  # that page's name before it became Duels
        name = name if name in PAGES else PAGES[0]
        if name != self.cfg["page"]:
            self.cfg["page"] = name
            save_config(self.cfg)
        self.dirty = True

    # --- player list ----------------------------------------------------------------

    def set_filter(self, name):
        """A chip above the list: who it shows. Remembered for the next start."""
        self.cfg["player_filter"] = name
        save_config(self.cfg)
        self.dirty = True

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

    def set_search(self, text):
        """Typing in the search box: only players with that in their name show."""
        text = text.strip().casefold()
        if text != self.search:
            self.search = text
            self.dirty = True

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
        self.dirty = True

    def toggle_column(self, column):
        """Shows or hides a column on both halves, and remembers it."""
        shown = self.cfg["columns"]
        self.cfg["columns"] = [c for c in PICKABLE_COLUMNS if (c in shown) != (c == column)]
        save_config(self.cfg)
        self.dirty = True

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
        """What one player's row shows: (text, colour) for each column of COLUMNS."""
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
            ("▌" if severity >= 1 else "", SEVERITY_FG[severity]),
            # Country as set on their public Steam profile ("…" while it's being looked up).
            ("…" if p.summary is None else p.summary.get("loccountrycode", ""), TEXT2),
            (self.player_class(p), TEXT2),
            ((p.name if len(p.name) <= 26 else p.name[:25] + "…") + ("  (you)" if p.sid == self.me else ""),
             TEAM_FG["YOU"] if p.sid == self.me else SEVERITY_FG[severity]),
            # Only TF2's scoreboard knows these (needs -g15); blank without it.
            self.health_cell(p),
            (f"{kills or 0}/{deaths or 0}" if kills or deaths else "", TEXT),
            self.streak_cell(p),
            (duel, duel_fg),
            (hs, hs_fg),
            (crit, crit_fg),
            (fmt_hours(p.hours), TEXT2),
            (fmt_age(p.summary), TEXT2),
            # The worst flag and how many more: every flag with its reason shows in the player's panel.
            ((flags[0][1] + (f"  +{len(flags) - 1}" if len(flags) > 1 else "")) if flags else "", SEVERITY_FG[severity]),
            (profile, SEVERITY_FG[2] if profile_hit else MUTED),
        )

    def team_strip(self, group):
        """What a team is made of: "3 Sniper · 2 Medic · 4 more · average 1,240 hours · 2 new
        accounts". Each part is left out while nothing is known."""
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

    def player_details(self, p):
        """One line for the player you clicked: their team and class, then what the list may
        not show (streak, headshots, crits, account age, profile)."""
        cells = dict(zip(COLUMNS, self.row_cells(p)))

        def known(column, label=""):
            text = cells[column][0]
            return f"{label}{text}" if text not in BLANK_CELLS else ""
        return " · ".join(s for s in (
            self.team_of(p), self.player_class(p), known("TF2", ""), known("Age", "account "),
            known("Streak", "streak "), known("HS", "headshots "), known("Crit", "crits "), known("Duel", "duels "),
            known("Profile", "profile: ")) if s and s not in BLANK_CELLS)

    def select(self, sid):
        """A click on a player: their panel opens; a click on them again closes it."""
        self.selected = None if self.selected == sid else sid
        self.dirty = True

    # --- the other pages -----------------------------------------------------------------

    def stop_duels_from_page(self):
        """The Stop all duels button: what "!duel stopall" does, said in chat the same way."""
        if not self.chat_duels:
            self.notify("No duels running")
        elif self.me in self.players:
            self.stop_all_duels(self.me)
        else:
            self.chat_duels = []  # you're not in a match: nothing to say it in
        self.dirty = True

    def _demo_open_profile(self):
        """A double-click on a player in the cheat check's list opens their Steam profile."""
        if self.demo_picked_sid:
            webbrowser.open(f"https://steamcommunity.com/profiles/{self.demo_picked_sid}")

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
             + (f" · {muted} player{'s' * (muted != 1)} muted" if muted else "")),
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

    # --- the title bar's feedback and the clipboard -----------------------------------------

    def notify(self, text):
        """A short confirmation in the window's title bar, for 3 seconds."""
        self.feedback = text
        self.dirty = True
        self.root.after(3000, self._clear_feedback, text)

    def _clear_feedback(self, text):
        if self.feedback == text:
            self.feedback = ""
            self.dirty = True

    def copy(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
