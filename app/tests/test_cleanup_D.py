"""The three Tk windows drawn over the game in the Tactical look: the mini HUD, the toast and the
translation overlay. Off-screen windows, made-up names."""
import tkinter as tk
import unittest

import helpers  # noqa: F401  (also points the overlay's settings file at a temp folder)
import hud
import screens
import settings
import tf2_translator
from settings import ACCENT, BG, BORDER, KEY_COLOR, TEAM_ACCENT, TEXT


def texts(canvas):
    return [canvas.itemcget(i, "text") for i in canvas.find_all() if canvas.type(i) == "text"]


class TkCase(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        self.root.destroy()


class HudStripTest(TkCase):
    def strip(self):
        strip = hud.HudStrip(self.root, ("Bahnschrift SemiBold SemiConden", 11), (-5000, -3800))
        return strip

    def test_team_tag_boxes_and_bright_counts(self):
        s = self.strip()
        s.show([("RED", TEAM_ACCENT["RED"]), ("  2 Pyro 1 Medic", TEXT), (hud.SEP, hud.MUTED),
                ("MEDIC DOWN - PUSH", hud.GOOD), (hud.SEP, hud.MUTED), ("Spies 1 (1 alive)", hud.WARN)])
        c = s.canvas
        fills = [c.itemcget(i, "fill") for i in c.find_all() if c.type(i) == "rectangle"]
        self.assertIn(TEAM_ACCENT["RED"], fills)          # the team as a filled tag
        self.assertIn(BG, fills)                          # on the dark bar
        self.assertEqual(sum(1 for i in c.find_all() if c.type(i) == "line"), 2)  # a line between the parts
        shown = texts(c)
        self.assertIn("2", shown)                         # counts drawn on their own, brighter
        self.assertIn(hud.spaced("MEDIC DOWN - PUSH"), shown)
        self.assertNotIn(hud.SEP, shown)

    def test_empty_draws_nothing_and_moving_shows_the_outline(self):
        s = self.strip()
        s.show([])
        self.assertEqual(s.canvas.find_all(), ())
        s.set_moving(True)
        c = s.canvas
        self.assertIn(hud.MOVE_TEXT, texts(c))
        edges = [c.itemcget(i, "outline") for i in c.find_all() if c.type(i) == "rectangle"]
        self.assertIn(ACCENT, edges)
        s.set_moving(False)
        edges = [c.itemcget(i, "outline") for i in c.find_all() if c.type(i) == "rectangle"]
        self.assertIn(BORDER, edges)


class ToastTest(TkCase):
    def test_label_time_and_height(self):
        t = screens.Toast(self.root, ("Bahnschrift SemiBold", 12), ("Bahnschrift SemiBold SemiConden", 9))
        t.win.geometry("+-5000+-4000")
        t.show("Gravy: 94% headshots (weak)", 1)
        t.show("New key found: steam", 0)
        shown = texts(t.canvas)
        self.assertIn(t._spaced("Alert"), shown)
        self.assertIn(t._spaced("Toolbox"), shown)       # the program's name, not "scanner"
        self.assertFalse(any("SCANNER" in x.replace(" ", "") for x in shown))
        self.assertTrue(all(len(item) == 3 for item in t.items))
        for _ in range(2):
            t.show("Mr Mittens: demo check: 12 anti-aim (strong)", 3)
        bottom = max(t.canvas.bbox(i)[3] for i in t.canvas.find_all())
        self.assertLessEqual(bottom, t.h)                 # four alerts: none cut off
        t.win.update_idletasks()
        self.assertEqual((t.win.winfo_x(), t.win.winfo_y()), (-5000, -4000))  # it grew where it was


class OverlayTest(TkCase):
    def overlay(self):
        real, tf2_translator.on_screen = tf2_translator.on_screen, lambda x, y: True
        self.addCleanup(setattr, tf2_translator, "on_screen", real)
        cfg = dict(settings.DEFAULTS, translator_x=-5000, translator_y=-5000)
        o = tf2_translator.Overlay(cfg, self.root)
        for name, text, team in (("Pancake", "nice shot", False), ("Waffles", "push now", True)):
            o.add({"name": name, "text": text, "original": text, "lang": "ru", "team": team})
        self.root.update()
        o.redraw()
        return o

    def test_lines_have_no_box_but_edged_text_and_a_tag(self):
        o = self.overlay()
        c = o.canvas
        self.assertEqual(c.cget("bg"), KEY_COLOR)        # locked: see-through around the lines
        for i in (0, 1):
            items = c.find_withtag(f"e{i}")
            fills = {c.itemcget(x, "fill") for x in items if c.type(x) == "rectangle"}
            self.assertEqual(fills - {""}, {tf2_translator.ACCENT})  # only the RU tag (+ TEAM outline): no dark box
            texts = [c.itemcget(x, "fill") for x in items if c.type(x) == "text"]
            self.assertIn(tf2_translator.TEXT_EDGE, texts)  # the dark edge that keeps it readable on any map
            self.assertIn("RU", [c.itemcget(x, "text") for x in items if c.type(x) == "text"])
        team = [c.itemcget(x, "text") for x in c.find_withtag("e1") if c.type(x) == "text"]
        self.assertIn("TEAM", team)
        self.assertGreater(c.bbox("e1")[1], c.bbox("e0")[1])   # the newest at the bottom
        self.assertLessEqual(c.bbox("e1")[3], c.winfo_height())

    def test_unlocked_has_the_dark_window_the_hint_and_the_buttons(self):
        o = self.overlay()
        o.toggle()
        c = o.canvas
        self.assertEqual(c.cget("bg"), tf2_translator.UNLOCKED_BG)
        shown = texts(c)
        self.assertIn("F8", shown)
        on = [x for x in c.find_withtag(f"mode_{o.cfg['translator_languages']}") if c.type(x) == "rectangle"]
        self.assertEqual(c.itemcget(on[0], "fill"), tf2_translator.ACCENT)
        buttons_left = min(c.bbox(f"mode_{m}")[0] for m in tf2_translator.LANGUAGE_MODES)
        hint = next(x for x in c.find_all() if c.type(x) == "text" and "LOCK" in c.itemcget(x, "text").replace(" ", ""))
        self.assertLess(c.bbox(hint)[2], buttons_left)  # the help never runs under the buttons
        o._show_status("Copied translation")
        self.assertIn(tf2_translator.spaced("Copied translation"), texts(c))
        o.toggle()
        self.assertEqual(c.cget("bg"), KEY_COLOR)


if __name__ == "__main__":
    unittest.main()
