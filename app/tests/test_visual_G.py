"""Visual pass, task G: the Cheat check and HoovyGPT (Duels) pages. Votekick's hover and grey state,
the calmer FOUND bar (red only for a STRONG find), the !badbot choice named by its effect, the exact
chat lines behind Stop all duels, and the agreed names, icons, fonts and motion in the page files."""
import json
import os
import re
import unittest

from helpers import Game, ME  # first: it puts the app's folder on the path
import web_state  # noqa: F401  (registers the pages and actions)
from game_log import STEAM64_BASE
from test_demo_check import detection, result
from web_cheat_duels import CANT_KICK, LOCK_OPTIONS, cheat_state, duels_state
from web_state import run_action

HANK, DAN = STEAM64_BASE + 2, STEAM64_BASE + 3  # in helpers.Game's STATUS
APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def page_file(name):
    with open(os.path.join(APP, "web", "pages", name), encoding="utf-8") as f:
        return f.read()


class CheatCheckTest(unittest.TestCase):
    def test_votekick_hover_and_found_bar(self):
        def script(g):
            a = g.app

            def state():
                s = g.on_screen_thread(lambda: cheat_state(a))
                json.dumps(s)
                return s

            def act(*args):
                g.on_screen_thread(lambda: run_action(a, args[0], args[1:]))

            self.assertFalse(state()["kick"]["ok"])  # nothing found: nobody to vote on
            weak = result(detection(HANK, "angle_history", 700))
            g.on_screen_thread(lambda: a.show_demo_result("x.dem", weak, {HANK: "Hank"}, {}, "20:15:00", "x_detections.json"))
            self.assertFalse(state()["found"]["strong"])  # weak only: the bar stays orange
            found = result(detection(HANK, "nocrex/oob_pitch", 900), detection(HANK, "angle_history", 700),
                           detection(DAN, "angle_history", 300))
            g.on_screen_thread(lambda: a.show_demo_result("x.dem", found, {HANK: "Hank", DAN: "dan"}, {}, "20:16:00",
                                                          "x_detections.json"))
            self.assertTrue(state()["found"]["strong"])

            # On your own team: a vote can start; on the other team: greyed, and the hover says why.
            a.board[ME], a.board[HANK], a.board[DAN] = {"m_iTeam": "2"}, {"m_iTeam": "2"}, {"m_iTeam": "3"}
            kick = state()["kick"]
            self.assertTrue(kick["ok"])
            self.assertIn("Hank", kick["why"])
            act("cheat_pick_player", str(DAN))
            self.assertEqual(state()["kick"], {"ok": False, "why": CANT_KICK})
            self.assertEqual(CANT_KICK, "Votes only work on your own team")

            # Votekick before any click acts on the player the page shows picked (the first).
            kicked = []
            a.votekick_player = lambda p: kicked.append(p.sid)
            a.demo_picked_sid = None
            act("cheat_votekick")
            self.assertEqual(kicked, [HANK])
        Game().play(script)


class DuelsTest(unittest.TestCase):
    def test_badbot_choice_and_stop_preview(self):
        def script(g):
            a = g.app
            a.check_ai_keys = lambda keys: None
            s = g.on_screen_thread(lambda: duels_state(a))
            self.assertEqual(s["lock_question"], "Who can use !badbot and !goodbot")
            self.assertEqual([o[0] for o in s["lock_options"]], ["off", "on", "muted"])
            self.assertEqual([o[1] for o in s["lock_options"]], ["Everyone", "Only you, Heavy talks", "Only you, Heavy quiet"])
            self.assertEqual(s["stop_preview"], [])  # no duels: it posts nothing

            # Each option does what its name says (ai.py): picked, Heavy is talking or quiet.
            for lock, muted in (("muted", True), ("on", False)):
                g.on_screen_thread(lambda: run_action(a, "duels_lock", [lock]))
                self.assertEqual(a.ai_muted, muted)
                self.assertEqual(g.on_screen_thread(lambda: duels_state(a))["lock"], lock)
            g.on_screen_thread(lambda: run_action(a, "duels_lock", ["off"]))
            self.assertIsNone(a.cfg["ai_lock"])

            # Stop all duels: its hover shows the exact line, and looking changes nothing.
            duel = {"sids": (ME, HANK), "score": {ME: 2, HANK: 1}}
            a.chat_duels = [duel]
            queued = len(a.announce_queue)
            lines = g.on_screen_thread(lambda: duels_state(a))["stop_preview"]
            self.assertEqual(len(lines), 1)
            self.assertTrue(lines[0].startswith(">>> [DUEL OVER] All 1 duel stopped <<< (by "))
            self.assertEqual(a.chat_duels, [duel])
            self.assertEqual(len(a.announce_queue), queued)
            self.assertNotIn("announce_chat", vars(a))
            a.chat_duels = []
        Game(heavy_talks=True).play(script)

    def test_every_option_has_its_effect(self):
        self.assertTrue(all(len(o) == 3 and o[2].endswith(".") for o in LOCK_OPTIONS))


class PageFilesTest(unittest.TestCase):
    def test_names(self):
        js = page_file("cheat_duels.js")
        self.assertIn("<b>Demo check</b>", js)
        self.assertNotIn("Live cheat check", js)
        self.assertIn('"Open demo",', js)
        self.assertNotIn("Open demo…", js)
        self.assertNotIn("Who can mute Heavy", js)
        self.assertNotIn("Stays muted", js)

    def test_icons_outline_and_motion(self):
        js, css = page_file("cheat_duels.js"), page_file("cheat_duels.css")
        self.assertIn("${ICON.kick}Votekick", js)
        self.assertIn("${ICON.export}Export", js)
        self.assertNotIn("btn dng", js)  # Votekick is an outline button, not filled red
        self.assertIn("prefers-reduced-motion", css)
        self.assertIn("var(--fade,.1s)", css)
        for font in ("--f-text,", "--f-head,", "--f-num,"):
            self.assertIn(f"var({font}", css)  # with a fallback, as index.html may not have them
        # spacing on the 8 / 16 / 24 grid only
        sizes = {int(n) for n in re.findall(r"(?:padding|gap|margin)[^;}]*?(\d+)px", css)}
        self.assertLessEqual(sizes - {0, 8, 16, 24, 240}, set())

    def test_brackets_only_on_main_panels(self):
        js = page_file("cheat_duels.js")
        self.assertEqual(js.count(" brk"), 2)  # the FOUND bar and the HoovyGPT switch


if __name__ == "__main__":
    unittest.main()
