"""Cleanup task B: the Cheat check page's table, short status line and Export menu, and the Duels
page without the separate tokens window."""
import json
import os
import unittest

from helpers import Game, ME  # first: it puts the app's folder on the path
import ai
import demo_check
import web_state  # noqa: F401  (registers the pages and actions)
from game_log import STEAM64_BASE
from test_demo_check import detection, result
from web_cheat_duels import cheat_state, duels_state, found_short, log_entries
from web_state import ACTIONS, run_action

HANK, DAN = STEAM64_BASE + 2, STEAM64_BASE + 3  # in helpers.Game's STATUS
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FoundRowsTest(unittest.TestCase):
    def test_rows_per_player_and_check(self):
        found = result(detection(DAN, "angle_history"), detection(HANK, "angle_history"),
                       detection(HANK, "nocrex/oob_pitch"), detection(HANK, "nocrex/oob_pitch"), detection(HANK, "odd_check"))
        rows = demo_check.found_rows(found, {HANK: "Hank"})
        self.assertEqual([(r["name"], r["check"], r["count"], r["strong"]) for r in rows],
                         [("Hank", "nocrex/oob_pitch", 2, True), ("Hank", "angle_history", 1, False),
                          ("Hank", "odd_check", 1, False), ("?", "angle_history", 1, False)])
        self.assertEqual(rows[0]["about"], demo_check.STRONG_CHECKS["nocrex/oob_pitch"])
        self.assertEqual(rows[1]["about"], "aim flicks")
        self.assertEqual(rows[2]["about"], "odd_check")  # no plain words for it: its own name

    def test_duration(self):
        self.assertEqual(demo_check.duration_text(96000), "00:24:00")
        # summary_text (what the evidence report and the Tk page use) still says the same.
        self.assertIn("Duration: 00:24:00 (96000 ticks)", demo_check.summary_text("x.dem", result(ticks=96000), {}, "now"))


class LogTest(unittest.TestCase):
    def test_found_short(self):
        self.assertEqual(found_short("found Hank, dan"), "found 2 players")
        self.assertEqual(found_short("found Hank"), "found 1 player")
        self.assertEqual(found_short("nothing found"), "nothing found")


class CheatPageTest(unittest.TestCase):
    def test_table_status_and_export_actions(self):
        def script(g):
            a = g.app

            def state():
                s = g.on_screen_thread(lambda: cheat_state(a))
                json.dumps(s)
                return s

            def act(*args):
                g.on_screen_thread(lambda: run_action(a, args[0], args[1:]))

            found = result(detection(HANK, "nocrex/oob_pitch", 900), detection(HANK, "angle_history", 700),
                           detection(ME, "angle_history", 300), ticks=96000)
            g.on_screen_thread(lambda: a.show_demo_result("2026-11-17_20-14-03.dem", found, {HANK: "Hank", ME: "me"}, {},
                                                          "20:15:00", "C:\\Somewhere\\demos\\x_detections.json"))
            s = state()
            t = s["table"]
            self.assertEqual((t["map"], t["duration"], t["file"]), ("ctf_2fort", "00:24:00", "2026-11-17_20-14-03.dem"))
            self.assertEqual([(r["name"], r["check"], r["count"], r["strong"], r["you"]) for r in t["rows"]],
                             [("Hank", "nocrex/oob_pitch", 1, True, False), ("Hank", "angle_history", 1, False, False),
                              ("me", "angle_history", 1, False, True)])
            self.assertTrue(all(isinstance(r["sid"], str) for r in t["rows"]))  # 64-bit IDs as text
            self.assertNotIn("Somewhere", json.dumps(s))
            self.assertNotIn("summary", s)  # the raw text dump is gone from the page
            self.assertEqual(s["meaning"][0]["check"], "nocrex/oob_pitch")  # "What these mean" stays

            # The status line: nothing the switches already say.
            a.demo_state = "checks about once a minute"
            self.assertEqual(state()["state"], "")
            a.demo_state = "checking..."
            self.assertEqual(state()["state"], "checking...")
            a.cfg["record_only_flagged"], a.recording = False, False
            self.assertIsNone(state()["recording"])
            a.cfg["record_only_flagged"] = True
            self.assertEqual(state()["recording"], {"on": False, "text": "Not recording"})
            a.recording = True
            self.assertTrue(state()["recording"]["on"])
            a.recording = False
            a.demo_log.appendleft("20:15:00   2026-11-17_20-14-03.dem   1.0 min read   found Hank")
            a.demo_log.appendleft("20:16:00   2026-11-17_20-20-00.dem   0.5 min read   nothing found   (finished, kept)")
            log = state()["log"]
            self.assertEqual(log[0], {"time": "20:16:00", "demo": "2026-11-17_20-20-00.dem", "read": "0.5 min read",
                                      "found": "nothing found", "after": "finished, kept"})
            self.assertEqual(log[1]["demo"], "")  # the table names it
            self.assertEqual(log[1]["found"], "found 1 player")
            self.assertEqual(len(log_entries(a)), 2)

            # Copy (in the Export menu) still copies the full lines it copied before.
            copied, called = [], []
            a.copy = copied.append
            a.open_detections_file = lambda: called.append("open")
            a.open_demos_folder = lambda: called.append("folder")
            act("cheat_copy")
            self.assertEqual(copied[-1], "\n".join(demo_check.copy_lines(found, {HANK: "Hank", ME: "me"}, {a.me})))
            act("cheat_open")
            act("cheat_open_folder")
            self.assertEqual(called, ["open", "folder"])
            self.assertIn("cheat_export", ACTIONS)
        Game().play(script)

    def test_page_script_has_two_buttons_and_the_menu(self):
        with open(os.path.join(HERE, "web", "pages", "cheat_duels.js"), encoding="utf-8") as f:
            js = f.read()
        for action in ("cheat_copy", "cheat_export", "cheat_open", "cheat_open_folder"):
            self.assertIn(f'["{action}", ', js)  # in the Export menu
        self.assertIn('data-a="cheat_votekick"', js)
        self.assertNotIn('data-a="cheat_copy"', js)
        self.assertIn("<h1>HoovyGPT</h1>", js)
        self.assertIn("// AI chat bot + duels", js)
        self.assertNotIn("duels_token_window", js)
        self.assertNotIn("Open in its own window", js)


class DuelsPageTest(unittest.TestCase):
    def test_no_tokens_window(self):
        def script(g):
            a = g.app
            a.check_ai_keys = lambda keys: None
            s = g.on_screen_thread(lambda: duels_state(a))
            self.assertNotIn("token_window", s)
            self.assertIn("tokens", s)  # the table stays, behind Details
            self.assertNotIn("duels_token_window", ACTIONS)
        Game().play(script)

    def test_toolbox_not_scanner(self):
        self.assertIn("toolbox", ai.TOKEN_NOTE)
        self.assertNotIn("scanner", ai.TOKEN_NOTE)


if __name__ == "__main__":
    unittest.main()
