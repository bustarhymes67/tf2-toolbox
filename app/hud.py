"""The mini HUD: one thin line over the game, also while the scanner's window is hidden (F9). It
shows, for the team you play against: its class line-up, its Medics (and "MEDIC DOWN - PUSH" the
moment one dies) and its Spies. Clicks pass through it to the game. All from TF2's scoreboard,
never the game's memory."""

import time
import tkinter as tk
from collections import Counter

from tf2_translator import set_click_through
from settings import ACCENT, BG, BORDER, FONT_LABEL, GOOD, KEY_COLOR, MUTED, TEAM_ACCENT, TEXT, WAITING, save_config

CLASS_ORDER = ["Scout", "Soldier", "Pyro", "Demo", "Heavy", "Engineer", "Medic", "Sniper", "Spy"]
SHORT_CLASS = {"Engineer": "Engi"}
ALERT_SECONDS = 6       # how long "MEDIC DOWN" and a line-up change stand out
TEAM_COLOR = TEAM_ACCENT
WARN = WAITING
SEP = "   ·   "


BACKDROP = BG           # the dark box behind the text, so it reads on any map
MOVE_EDGE = ACCENT      # its outline while you move it


def default_place(root):
    """Where the strip goes until you move it: the top-left corner of the screen."""
    return 10, 10


class HudStrip:
    """A window with one line of coloured parts on a dark box. Clicks pass through it to the game,
    except while you move it."""

    def __init__(self, root, font, place):
        self.font = font
        self.shown = None   # what's drawn now: (text, colour) parts
        self.moving = False
        self.win = win = tk.Toplevel(root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.attributes("-transparentcolor", KEY_COLOR)
        self.w, self.h = 1100, 30
        self.canvas = tk.Canvas(win, bg=KEY_COLOR, highlightthickness=0, width=self.w, height=self.h)
        self.canvas.pack(fill="both", expand=True)
        self.place(*place)
        win.update_idletasks()
        set_click_through(win, True)
        self.canvas.bind("<ButtonPress-1>", self._drag_start)
        self.canvas.bind("<B1-Motion>", self._drag_move)
        self.drag = None

    def place(self, x, y):
        self.win.geometry(f"{self.w}x{self.h}+{x}+{y}")

    def where(self):
        return self.win.winfo_x(), self.win.winfo_y()

    def _drag_start(self, e):
        if self.moving:
            self.drag = (e.x_root, e.y_root) + self.where()

    def _drag_move(self, e):
        if self.moving and self.drag:
            x0, y0, wx, wy = self.drag
            self.place(wx + e.x_root - x0, wy + e.y_root - y0)

    def set_moving(self, moving):
        """While moving, it takes the mouse so you can drag it, and shows its outline."""
        self.moving = moving
        set_click_through(self.win, not moving)
        shown, self.shown = self.shown, None
        self.show(shown or (("Drag me where you want me, then press Done on the Status page", TEXT),))

    def show(self, parts):
        """Draws the parts from the left on a dark box, each in its colour. No parts (and not
        moving): nothing is drawn."""
        parts = tuple(parts)
        if parts == self.shown:
            return
        self.shown = parts
        c = self.canvas
        c.delete("all")
        if not parts and not self.moving:
            return
        if not parts:
            parts = (("Drag me where you want me, then press Done on the Status page", TEXT),)
        x, pad = 10, 10
        for text, colour in parts:
            item = c.create_text(x, self.h // 2, text=text, anchor="w", font=self.font, fill=colour)
            x = c.bbox(item)[2]
        box = c.create_rectangle(0, 0, min(x + pad, self.w - 1), self.h - 1, fill=BACKDROP,
                                 outline=MOVE_EDGE if self.moving else BORDER, width=2 if self.moving else 1)
        c.tag_lower(box)


class HudMixin:
    """The part of the App that works out what the strip says."""

    def hud_init(self):
        place = (self.cfg["hud_x"], self.cfg["hud_y"])
        self.hud = HudStrip(self.root, (FONT_LABEL, 11),
                            place if None not in place else default_place(self.root))
        self.hud_medics_alive = None    # enemy Medics alive at the last look, to see one die
        self.hud_lineup = None          # the enemy line-up at the last look, to see it change
        self.hud_alerts = {}            # kind -> (until, text, colour)

    def hud_tick(self):
        if self.hud.moving:
            return  # it shows what it showed when you started moving it
        if not self.cfg["hud"] or self.rcon_state != "connected":
            self.hud.show(())
            return
        self.hud.show(self.hud_parts())

    def hud_parts(self, now=None):
        """The strip's parts: [line-up] · [Medics] · [Spies]."""
        now = now or time.time()
        enemies = [p for p in self.players.values() if self.team_of(p) == "ENEMY"]
        if not enemies:
            return []
        color = next((c for c in map(self.team_color, enemies) if c), "")
        classes = {p.sid: self.player_class(p) for p in enemies}

        # Line-up: noticed when it changes, once it was known before.
        lineup = Counter(c for c in classes.values() if c)
        if self.hud_lineup is not None and lineup != self.hud_lineup:
            grew = [cls for cls in lineup if lineup[cls] > self.hud_lineup.get(cls, 0)]
            if grew:
                cls = grew[0]
                self.hud_alerts["lineup"] = (now + ALERT_SECONDS, f"now {lineup[cls]} {cls}", WARN)
        self.hud_lineup = lineup

        # Medics: alive or dead from the scoreboard; one dying is the moment to push.
        medics = [p for p in enemies if classes[p.sid] == "Medic"]
        alive = {p.sid for p in medics if self.alive(p)}
        if self.hud_medics_alive is not None and self.hud_medics_alive - alive:
            self.hud_alerts["medic"] = (now + ALERT_SECONDS, "MEDIC DOWN - PUSH", GOOD)
        self.hud_medics_alive = alive
        self.hud_alerts = {k: v for k, v in self.hud_alerts.items() if v[0] > now}

        parts = []
        names = " ".join(f"{lineup[c]} {SHORT_CLASS.get(c, c)}" for c in CLASS_ORDER if lineup[c])
        parts.append((color or "ENEMY", TEAM_COLOR.get(color, MUTED)))
        parts.append(("  " + (names or "classes not known yet"), TEXT))
        if "lineup" in self.hud_alerts:
            _, text, colour = self.hud_alerts["lineup"]
            parts.append((f"  ({text})", colour))

        parts.append((SEP, MUTED))
        if "medic" in self.hud_alerts:
            parts.append(self.hud_alerts["medic"][1:])
        elif not medics:
            parts.append(("no Medic", MUTED))
        elif len(medics) == 1:
            parts.append(("Medic alive", WARN) if alive else ("Medic dead", GOOD))
        else:
            parts.append((f"Medics {len(alive)}/{len(medics)} alive", WARN if alive else GOOD))

        spies = [p for p in enemies if classes[p.sid] == "Spy"]
        if spies:
            spies_alive = sum(1 for p in spies if self.alive(p))
            parts += [(SEP, MUTED), (f"Spies {len(spies)} ({spies_alive} alive)", WARN if spies_alive else MUTED)]
        return parts

    def alive(self, p):
        """True unless TF2's scoreboard says they're dead (no scoreboard: counted as alive)."""
        return (self.board.get(p.sid) or {}).get("m_bAlive") != "false"

    def toggle_hud(self):
        """The Mini HUD card on the Status page."""
        self.cfg["hud"] = not self.cfg["hud"]
        save_config(self.cfg)
        self.update_hud_button()
        self.hud_tick()

    def toggle_hud_move(self):
        """The Move card on the Status page: drag the strip, then press it again (Done) to keep the place."""
        moving = not self.hud.moving
        self.hud.set_moving(moving)
        if not moving:
            self.cfg["hud_x"], self.cfg["hud_y"] = self.hud.where()
            save_config(self.cfg)
            self.hud.shown = None
            self.hud_tick()
        self.hud_move_button.show("Done" if moving else "Move", moving)

    def reset_hud_place(self):
        """Back in the top-left corner, where it starts."""
        self.cfg["hud_x"] = self.cfg["hud_y"] = None
        save_config(self.cfg)
        self.hud.place(*default_place(self.root))

    def update_hud_button(self):
        on = self.cfg["hud"]
        self.hud_button.show("ON" if on else "OFF", on)
