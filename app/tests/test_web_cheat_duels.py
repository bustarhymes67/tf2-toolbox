"""The web window's Cheat check and Duels pages (web_cheat_duels.py): their state and clicks,
on a real App kept off-screen."""
import json
import unittest

from helpers import Game  # first: it puts the app's folder on the path
import demo_check
import screens
import web_state  # noqa: F401  (registers the pages and actions)
from ai import AI_MODELS
from game_log import STEAM64_BASE
from test_demo_check import detection, result
from web_cheat_duels import cheat_state, duels_state
from web_state import run_action

HANK, DAN = STEAM64_BASE + 2, STEAM64_BASE + 3  # in helpers.Game's STATUS


class WebCheatDuelsTest(unittest.TestCase):
    def test_cheat_check_page(self):
        def script(g):
            a = g.app

            def state():
                s = g.on_screen_thread(lambda: cheat_state(a))
                json.dumps(s)  # the page gets it as JSON
                return s

            def act(*args):
                g.on_screen_thread(lambda: run_action(a, args[0], args[1:]))

            # Nothing checked yet: every known check is explained.
            s = state()
            self.assertEqual(s["summary"], "Nothing found yet.")
            self.assertIsNone(s["found"])
            self.assertEqual(s["players"], [])
            self.assertEqual([m["check"] for m in s["meaning"]], list(demo_check.CHECK_MEANING))
            self.assertTrue(s["state"].startswith("Cheat check: "))
            for key, setting in (("cheat_toggle_check", "demo_check"), ("cheat_toggle_keep", "demo_keep_only_cheaters")):
                was = a.cfg[setting]
                act(key)
                self.assertEqual(a.cfg[setting], not was)
                self.assertEqual(state()["check" if setting == "demo_check" else "keep"], not was)
            act("cheat_check_now")
            self.assertEqual(a.feedback, "Checking the demo now")  # (a demo worker may already have taken CHECK_NOW)

            found = result(detection(HANK, "nocrex/oob_pitch", 900), detection(HANK, "nocrex/oob_pitch", 500),
                           detection(HANK, "angle_history", 700), detection(DAN, "angle_history", 300))
            names = {HANK: "Hank", DAN: "dan"}
            g.on_screen_thread(lambda: a.show_demo_result("2026-11-17_20-14-03.dem", found, names, {}, "20:15:00",
                                                          "C:\\Somewhere\\demos\\2026-11-17_20-14-03_detections.json"))
            s = state()
            self.assertIn("Saved: 2026-11-17_20-14-03_detections.json", s["summary"])
            self.assertNotIn("Somewhere", s["summary"])  # no folders (user names) on the page
            self.assertEqual([m["check"] for m in s["meaning"]], ["nocrex/oob_pitch", "angle_history"])
            self.assertEqual([m["strong"] for m in s["meaning"]], [True, False])
            self.assertEqual(s["found"]["who"], "Hank")
            self.assertEqual(s["found"]["what"], "2 oob_pitch (strong) \u00b7 1 angle_history (weak) \u00b7 +1 more player")
            self.assertEqual([(p["name"], p["count"], p["strong"]) for p in s["players"]],
                             [("Hank", 3, True), ("dan", 1, False)])
            self.assertEqual(s["picked"], str(HANK))
            self.assertEqual([d["tick"] for d in s["dets"]], [500, 700, 900])
            self.assertEqual(s["det"], s["dets"][0]["key"])
            self.assertEqual(json.loads(s["details"])["player"], "Hank")
            self.assertEqual(s["goto"], "demo_gototick 300")

            # A detection, then another player: like the Tk lists, and kept across states.
            act("cheat_pick_det", s["dets"][2]["key"])
            s = state()
            self.assertEqual(s["det"], s["dets"][2]["key"])
            self.assertEqual(s["goto"], "demo_gototick 700")
            self.assertEqual(state()["det"], s["det"])
            act("cheat_pick_player", str(DAN))
            s = state()
            self.assertEqual(s["picked"], str(DAN))
            self.assertEqual(a.demo_picked_sid, DAN)
            self.assertEqual([d["check"] for d in s["dets"]], ["angle_history"])
            self.assertEqual(json.loads(s["details"])["player"], "dan")

            # The FOUND bar's buttons call the Tk buttons' methods.
            kicked, copied, called = [], [], []
            a.votekick_player = lambda p: kicked.append(p.sid)
            a.copy = copied.append
            a.open_detections_file = lambda: called.append("open")
            a.open_demos_folder = lambda: called.append("folder")
            act("cheat_votekick")
            self.assertEqual(kicked, [DAN])
            act("cheat_copy")
            self.assertTrue(copied[-1].startswith(demo_check.COPY_TAG))
            self.assertIn("PLAYER: Hank", copied[-1])
            act("cheat_copy_goto")
            self.assertEqual(copied[-1], "demo_gototick 100")
            act("cheat_open")
            act("cheat_open_folder")
            self.assertEqual(called, ["open", "folder"])

        Game().play(script)

    def test_duels_page(self):
        def script(g):
            a = g.app
            a.check_ai_keys = lambda keys: None  # never tries the fake keys online

            def state():
                s = g.on_screen_thread(lambda: duels_state(a))
                json.dumps(s)
                return s

            def act(*args):
                g.on_screen_thread(lambda: run_action(a, args[0], args[1:]))

            s = state()
            self.assertEqual(s["title"], "HoovyGPT + Duels")
            self.assertTrue(s["on"])
            self.assertEqual(s["commands"], [list(c) for c in screens.DUEL_COMMANDS])
            self.assertEqual(s["duels"], [])
            self.assertEqual([c[0] for c in s["model"]["choices"]], ["auto"] + [m for _, m in AI_MODELS])
            self.assertEqual(s["lock"], "off")
            self.assertEqual(len(s["tokens"]["rows"]), len(AI_MODELS))
            self.assertEqual(sum(r[0] == ">" for r in s["tokens"]["rows"]), 1)

            act("duels_toggle")
            self.assertFalse(a.ai_on)
            self.assertEqual(state()["text"], "OFF")
            act("duels_toggle")
            self.assertTrue(state()["on"])

            # Running duels, from App.duel_entries, with each side's team colour.
            a.board[HANK] = {"m_iTeam": "2"}
            a.board[DAN] = {"m_iTeam": "3"}
            entries = ["Hank 3-1 dan", "ALL vs ALL: RED 4-2 BLU", "tomato vs ALL OF BLU: won 1, lost 0, tied 2"]
            a.duel_entries = lambda: entries
            duels = state()["duels"]
            self.assertEqual(duels[0], {"a": "Hank", "sa": "3", "sb": "1", "b": "dan", "label": "", "ta": "r", "tb": "b"})
            self.assertEqual((duels[1]["label"], duels[1]["a"], duels[1]["ta"], duels[1]["tb"]), ("ALL vs ALL", "RED", "r", "b"))
            self.assertEqual(duels[2], {"text": entries[2]})
            del a.duel_entries
            act("duels_stop")
            self.assertEqual(a.feedback, "No duels running")

            act("duels_model", "gemini-3.5-flash-lite")
            self.assertEqual(a.cfg["ai_model"], "gemini-3.5-flash-lite")
            self.assertEqual(state()["model"]["name"], "gemini-3.5-flash-lite")
            act("duels_model", "not-a-model")
            self.assertEqual(a.cfg["ai_model"], "gemini-3.5-flash-lite")
            act("duels_model", "auto")
            self.assertTrue(state()["model"]["name"].startswith("Auto: "))

            act("duels_lock", "on")
            self.assertEqual(a.cfg["ai_lock"], "on")
            self.assertEqual(state()["lock"], "on")
            act("duels_lock", "off")
            self.assertIsNone(a.cfg["ai_lock"])
            act("duels_lock", "bogus")
            self.assertIsNone(a.cfg["ai_lock"])

            was = a.cfg["token_panel"]
            act("duels_token_window")
            self.assertEqual(state()["token_window"], not was)
            act("duels_token_window")

            # heavy_talks off: only the duels, as on the Tk page.
            a.cfg["heavy_talks"] = False
            s = state()
            self.assertEqual(s["title"], "Duels")
            self.assertNotIn("model", s)
            self.assertNotIn("tokens", s)

        Game().play(script)


if __name__ == "__main__":
    unittest.main()
