"""The live cheat check: reading demo-analysis's results, flags, and which finished demos are kept."""
import json
import os
import tempfile
import time
import unittest
from collections import Counter

from helpers import Game, ME
import demo_check
import player_flags

HIM = ME + 2  # dan


def detection(player, algorithm, tick=1):
    return {"tick": tick, "algorithm": algorithm, "player": player, "data": {}}


def result(*detections, ticks=4000):
    return {"author": "tomato", "detections": list(detections), "duration": ticks, "map": "ctf_2fort"}


class FlagsTest(unittest.TestCase):
    def test_strong_and_weak_checks(self):
        counts = Counter({"nocrex/oob_pitch": 23, "doubletap": 6, "nocrex/angle_repeat": 22})
        flags = demo_check.demo_flags(counts)
        self.assertIn((3, "demo check: looked past the game's 89° limit (23x)"), flags)
        self.assertIn((1, "demo check: 6 double taps, 22 one-tick aim jumps"), flags)
        self.assertEqual(player_flags.flag_why(3, flags[0][1])[0], "strong")
        self.assertEqual(player_flags.flag_why(1, flags[1][1])[0], "weak")

    def test_nothing_found_no_flags(self):
        self.assertEqual(demo_check.demo_flags(Counter()), [])

    def test_counts_per_player(self):
        counts = demo_check.count_checks([detection(5, "doubletap"), detection(5, "doubletap"), detection(6, "backtrack")])
        self.assertEqual(counts, {5: Counter({"doubletap": 2}), 6: Counter({"backtrack": 1})})


class FinishedDemoTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.dem = os.path.join(self.folder.name, "2026-11-05_21-44-05.dem")
        open(self.dem, "wb").write(b"demo")

    def tearDown(self):
        self.folder.cleanup()

    def sidecar(self, events):
        json.dump({"events": events}, open(self.dem[:-4] + ".json", "w"))

    def test_nothing_found_is_deleted_with_its_json(self):
        self.sidecar([{"name": "Killstreak", "value": "4", "tick": 9}])
        open(demo_check.detections_path(self.dem), "w").write("{}")
        self.assertEqual(demo_check.tidy_finished(self.dem, [], True), "deleted")
        self.assertEqual(os.listdir(self.folder.name), [])

    def test_a_detection_keeps_it(self):
        self.assertEqual(demo_check.tidy_finished(self.dem, [detection(5, "doubletap")], True), "kept")
        self.assertTrue(os.path.exists(self.dem))

    def test_a_bookmark_keeps_it(self):
        self.sidecar([{"name": "Bookmark", "value": "mine", "tick": 9}])
        self.assertEqual(demo_check.tidy_finished(self.dem, [], True), "kept")

    def test_with_the_setting_off_nothing_is_deleted(self):
        self.assertEqual(demo_check.tidy_finished(self.dem, [], False), "kept")
        self.assertTrue(os.path.exists(self.dem))


class NamesFromLogTest(unittest.TestCase):
    def test_the_latest_name_of_each_player_and_user_id(self):
        with tempfile.TemporaryDirectory() as folder:
            log = os.path.join(folder, "console.log")
            open(log, "w", encoding="utf-8").write(
                '#   2206 "old name"          [U:1:444555666]     01:00      110    0 active\n'
                'last man killed someone with force_a_nature.\n'
                '#   2206 "last man"          [U:1:444555666]     04:51      110    1 active\n'
                '#   2207 "someone else"      [U:1:5]     04:51      50    0 active\n')
            him = demo_check.STEAM64_BASE + 444555666
            by_sid, by_userid = demo_check.names_from_log(log)
            self.assertEqual(by_sid[him], "last man")
            self.assertEqual(by_userid, {2206: "last man", 2207: "someone else"})
            self.assertEqual(demo_check.names_from_log(os.path.join(folder, "missing.log")), ({}, {}))


CHEATER = demo_check.STEAM64_BASE + 111222333
CHEATER_RESULT = result(*[detection(CHEATER, "nocrex/oob_pitch", 59151 + i) for i in range(23)],
                        *[detection(CHEATER, "nocrex/angle_repeat", 1200 + i) for i in range(22)],
                        *[detection(CHEATER, "doubletap", 16377 + i) for i in range(6)],
                        *[detection(CHEATER, "angle_history", 32924 + i) for i in range(5)], ticks=117356)


class TextTest(unittest.TestCase):
    def test_the_copy_line(self):
        self.assertEqual(demo_check.copy_lines(CHEATER_RESULT, {CHEATER: "Some Very Sneaky Cheater1"}), [
            "[demo-analysis by Nocrex]: PLAYER: Some Very Sneak… | oob_pitch 23 STRONG, angle_repeat 22 +2 more "
            "| github.com/MegaAntiCheat"])

    def test_one_cheaters_txt_updated_per_demo(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        names = {CHEATER: "Some Very Sneaky Cheater1", ME: "me"}
        first = result(detection(CHEATER, "nocrex/oob_pitch", 500), detection(ME, "doubletap", 9))
        demo_check.save_cheater_ticks(folder.name, "2026-11-05_21-44-05.dem", first, names, {ME})
        demo_check.save_cheater_ticks(folder.name, "2026-11-06_20-00-00.dem",
                                      result(detection(CHEATER, "doubletap", 77)), names)
        # The first demo, checked again while still recording, finds more: its block is updated.
        more = result(detection(CHEATER, "nocrex/oob_pitch", 500), detection(CHEATER, "nocrex/oob_pitch", 620),
                      detection(CHEATER, "angle_history", 900))
        demo_check.save_cheater_ticks(folder.name, "2026-11-05_21-44-05.dem", more, names, {ME})
        self.assertEqual(os.listdir(folder.name), ["cheaters.txt"])
        text = open(os.path.join(folder.name, "cheaters.txt"), encoding="utf-8").read()
        self.assertEqual(text, demo_check.CHEATERS_HEAD + (
            "\n=== 2026-11-05_21-44-05.dem ===\n"
            f"Some Very Sneaky Cheater1 ({CHEATER})\n"
            "  oob_pitch STRONG: ticks 500, 620\n"
            "  angle_history: ticks 900\n"
            "\n=== 2026-11-06_20-00-00.dem ===\n"
            f"Some Very Sneaky Cheater1 ({CHEATER})\n"
            "  doubletap: ticks 77\n"))

    def test_a_copy_line_always_fits_one_chat_message(self):
        line = demo_check.fit_copy_line("Очень длинное имя игрока на сервере",
                                        [f"check_number_{i} {i}" for i in range(9)])
        self.assertLessEqual(len(line.encode()), 127)
        self.assertIn("…", line)
        self.assertRegex(line, r"\+\d+ more \| github\.com/MegaAntiCheat$")

    def test_the_summary_is_like_the_command_line_with_names(self):
        text = demo_check.summary_text("cheater.dem", CHEATER_RESULT, {CHEATER: "Some Very Sneaky Cheater1"}, "23:51:16")
        self.assertIn("Map: ctf_2fort\nDuration: 00:29:20 (117356 ticks), checked 23:51:16\nDemo: cheater.dem", text)
        self.assertIn("Total detections: 56", text)
        self.assertIn("  nocrex/oob_pitch: 1 player, 23 detections   STRONG (anti-aim)\n"
                      f"    Some Very Sneaky Cheater1 ({CHEATER}): 23", text)
        self.assertLess(text.index("oob_pitch"), text.index("angle_repeat"))
        self.assertLess(text.index("doubletap"), text.index("angle_history"))

    def test_details_name_the_victim_and_say_how_to_jump_there(self):
        det = {"tick": 43930, "algorithm": "doubletap", "player": CHEATER,
               "data": {"class": "scout", "​​​​victim": 854, "​​​​​weapon_id": 16}}
        text = demo_check.detection_details(det, {CHEATER: "Some Very Sneaky Cheater1"}, {854: "tomato"})
        self.assertIn('"victim": "tomato (user 854)"', text)
        self.assertIn('"player": "Some Very Sneaky Cheater1"', text)
        self.assertIn("demo_gototick 43730", text)


class AppTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.folder.cleanup()

    def test_a_find_is_saved_reported_and_copyable(self):
        def script(g):
            g.events.put(("demo", "2026-11-05_23-40-24.dem", result(detection(HIM, "angle_history", 4585)), None))
            time.sleep(0.5)
            saved = os.path.join(self.folder.name, "2026-11-05_23-40-24_detections.json")
            data = json.load(open(saved, encoding="utf-8"))
            self.assertEqual(data["detections"][0]["tick"], 4585)
            self.assertEqual(data["players"][str(HIM)], "dan")
            self.assertIn(f"dan ({HIM}): 1", g.app.demo_summary)
            self.assertIn(saved, g.app.demo_summary)
            from web_cheat_duels import cheat_state
            s = g.on_screen_thread(lambda: cheat_state(g.app))  # what the Cheat check page shows
            self.assertIn("angle_history", g.app.demo_summary)
            self.assertEqual([(p["name"], p["count"]) for p in s["players"]], [("dan", 1)])
            self.assertEqual([(d["tick"], d["check"]) for d in s["dets"]], [(4585, "angle_history")])
            self.assertIn("demo_gototick 4385", s["goto"])
            g.on_screen_thread(g.app.copy_demo_lines)
            self.assertEqual(g.on_screen_thread(g.app.root.clipboard_get),
                             "[demo-analysis by Nocrex]: PLAYER: dan | angle_history 1 | github.com/MegaAntiCheat")
            ticks = open(os.path.join(self.folder.name, "cheaters.txt"), encoding="utf-8").read()
            self.assertIn(f"=== 2026-11-05_23-40-24.dem ===\ndan ({HIM})\n  angle_history: ticks 4585\n", ticks)
            self.assertTrue(any("dan: demo check: 1 aim flicks (weak)" in t for _, t, _ in g.app.toast.items))
        Game(demos_dir=self.folder.name).play(script)

    def test_the_copy_line_and_the_goto_tick_can_be_copied(self):
        def script(g):
            from web_state import run_action
            g.events.put(("demo", "2026-11-05_23-40-24.dem", result(detection(HIM, "nocrex/angle_repeat", 4585)), None))
            time.sleep(0.5)
            a = g.app
            line = "[demo-analysis by Nocrex]: PLAYER: dan | angle_repeat 1 | github.com/MegaAntiCheat"
            self.assertIn(line, a.demo_summary)  # the copy line is in the summary too
            self.assertIn("Total detections: 1", a.demo_summary)
            g.on_screen_thread(lambda: run_action(a, "cheat_copy", []))
            self.assertEqual(g.on_screen_thread(a.root.clipboard_get), line)
            g.on_screen_thread(lambda: run_action(a, "cheat_copy_goto", []))
            self.assertIn("demo_gototick", g.on_screen_thread(a.root.clipboard_get))
        Game(demos_dir=self.folder.name).play(script)

    def test_a_player_who_left_gets_their_name_from_the_log(self):
        def script(g):
            gone = ME + 99
            g.events.put(("demo", "2026-11-05_23-40-24.dem", result(detection(gone, "angle_history")), None,
                          {gone: "last man"}, {}))
            time.sleep(0.5)
            data = json.load(open(os.path.join(self.folder.name, "2026-11-05_23-40-24_detections.json"), encoding="utf-8"))
            self.assertEqual(data["players"][str(gone)], "last man")
            self.assertIn("last man", g.app.demo_summary)
        Game(demos_dir=self.folder.name).play(script)

    def test_nothing_found_saves_nothing(self):
        def script(g):
            g.events.put(("demo", "2026-11-05_23-40-24.dem", result(), None))
            time.sleep(0.5)
            self.assertEqual(os.listdir(self.folder.name), [])
            self.assertEqual(g.app.demo_summary, "")
        Game(demos_dir=self.folder.name).play(script)

    def test_a_detection_flags_the_player_and_bookmarks_the_demo(self):
        def script(g):
            g.events.put(("demo", "2026-11-05_22-27-16.dem", result(detection(HIM, "nocrex/oob_pitch")), None))
            time.sleep(0.5)
            self.assertIn((3, "demo check: looked past the game's 89° limit (1x)"), g.app.flags[HIM])
            self.assertTrue(any(c.startswith('ds_mark "cheat check: dan') for c in g.sent), g.sent)
            g.events.put(("demo", "2026-11-05_22-27-16.dem", result(*[detection(HIM, "nocrex/oob_pitch")] * 2), None))
            time.sleep(0.5)
            self.assertEqual(sum(c.startswith("ds_mark") for c in g.sent), 1)  # one bookmark per demo
            self.assertIn("found dan", g.app.demo_log[0])
        Game(demos_dir=self.folder.name).play(script)

    def test_a_finished_demo_does_not_get_a_bookmark(self):
        def script(g):
            g.events.put(("demo", "2026-11-05_22-27-16.dem", result(detection(HIM, "doubletap"), ticks=18000), "kept"))
            time.sleep(0.5)
            self.assertFalse(any(c.startswith("ds_mark") for c in g.sent))
            self.assertIn("4.5 min read", g.app.demo_log[0])
            self.assertIn("finished, kept", g.app.demo_log[0])
        Game(demos_dir=self.folder.name).play(script)

    def test_nothing_found_is_logged_and_check_now_wakes_the_worker(self):
        def script(g):
            g.events.put(("demo", "2026-11-05_22-27-16.dem", result(ticks=4000), None))
            time.sleep(0.5)
            self.assertIn("1.0 min read   nothing found", g.app.demo_log[0])
            demo_check.CHECK_NOW.clear()
            g.on_screen_thread(g.app.check_demo_now)
            self.assertTrue(demo_check.CHECK_NOW.is_set())
            demo_check.CHECK_NOW.clear()
        Game(demos_dir=self.folder.name).play(script)


if __name__ == "__main__":
    unittest.main()
