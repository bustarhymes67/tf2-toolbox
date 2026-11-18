"""EXPORT EVIDENCE on the Cheat check page: the folder next to the demos, with the demo, its saved
detections and report.txt, for the picked player (else the one found most)."""
import os
import shutil
import tempfile
import unittest
from unittest import mock

from helpers import Game  # first: it puts the app's folder on the path
import demo_check
import web_state  # noqa: F401  (registers the pages and actions)
from game_log import STEAM64_BASE
from test_demo_check import detection, result
from web_state import run_action

HANK, DAN = STEAM64_BASE + 2, STEAM64_BASE + 3  # in helpers.Game's STATUS
DEMO = "2026-11-17_20-14-03.dem"
FOUND = result(detection(HANK, "nocrex/oob_pitch", 900), detection(HANK, "nocrex/oob_pitch", 500),
               detection(HANK, "angle_history", 700), detection(DAN, "angle_history", 300))
NAMES = {HANK: "Hank", DAN: "dan"}


class EvidenceFilesTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="tf2scanner-evidence-")
        self.addCleanup(shutil.rmtree, self.folder, True)

    def test_folder_name_is_safe(self):
        self.assertEqual(demo_check.evidence_folder_name("Hank", DEMO), "evidence Hank 2026-11-17_20-14-03")
        self.assertEqual(demo_check.safe_file_part('a<b>:c"/d\\e|f?g*h. '), "abcdefgh")
        self.assertEqual(demo_check.safe_file_part("..."), "player")
        self.assertEqual(len(demo_check.safe_file_part("x" * 100)), demo_check.EVIDENCE_NAME_CHARS)

    def test_report(self):
        text = demo_check.evidence_report(HANK, "Hank", DEMO, FOUND)
        for line in ("Player: Hank", f"SteamID64: {HANK}", f"Profile: https://steamcommunity.com/profiles/{HANK}",
                     "Map: ctf_2fort", f"Demo: {DEMO}", "Duration: 00:01:00 (4000 ticks)", "Detections: 3",
                     "nocrex/oob_pitch: 2 detections, STRONG: an unmodified game can't do this",
                     "  Ticks: 500, 900", "  In TF2's console while playing the demo: demo_gototick 500",
                     "angle_history: 1 detection, weak: lag or packet loss can cause it too",
                     "  In TF2's console while playing the demo: demo_gototick 700",
                     "  What it means: " + demo_check.CHECK_MEANING["angle_history"],
                     demo_check.EVIDENCE_CREDIT):
            self.assertIn(line + "\n", text)
        self.assertLess(text.index("oob_pitch"), text.index("angle_history"))  # strong first
        self.assertNotIn("300", text)  # dan's detection isn't in Hank's report
        self.assertNotIn("gone", text)

    def test_export_copies_the_demo_and_its_detections(self):
        with open(os.path.join(self.folder, DEMO), "wb") as f:
            f.write(b"HL2DEMO\0")
        demo_check.save_detections(os.path.join(self.folder, DEMO), FOUND, NAMES)
        target = demo_check.export_evidence(self.folder, DEMO, FOUND, HANK, "Hank")
        self.assertEqual(os.path.dirname(target), self.folder)
        self.assertEqual(sorted(os.listdir(target)),
                         sorted([DEMO, "2026-11-17_20-14-03_detections.json", "report.txt"]))
        with open(os.path.join(target, DEMO), "rb") as f:
            self.assertEqual(f.read(), b"HL2DEMO\0")

    def test_export_without_the_demo_says_so(self):
        target = demo_check.export_evidence(self.folder, DEMO, FOUND, HANK, "Hank")
        self.assertEqual(os.listdir(target), ["report.txt"])
        with open(os.path.join(target, "report.txt"), encoding="utf-8") as f:
            self.assertIn("The demo file is gone", f.read())


class EvidenceButtonTest(unittest.TestCase):
    def test_button_on_the_web_page(self):
        folder = tempfile.mkdtemp(prefix="tf2scanner-evidence-")
        self.addCleanup(shutil.rmtree, folder, True)
        opened = []

        def script(g):
            a = g.app

            def act(name, *args):
                g.on_screen_thread(lambda: run_action(a, name, args))

            act("cheat_export")
            self.assertEqual(a.feedback, "Nothing found yet, so there's no evidence to save")
            g.on_screen_thread(lambda: a.show_demo_result(DEMO, FOUND, NAMES, {}, "20:15:00"))
            with mock.patch("os.startfile", opened.append, create=True):
                act("cheat_export")  # nobody picked: the one found most
                self.assertEqual(a.feedback, "Evidence saved: evidence Hank 2026-11-17_20-14-03")
                act("cheat_pick_player", str(DAN))
                act("cheat_export")
                self.assertEqual(a.feedback, "Evidence saved: evidence dan 2026-11-17_20-14-03")
            self.assertEqual([os.path.basename(p) for p in opened],
                             ["evidence Hank 2026-11-17_20-14-03", "evidence dan 2026-11-17_20-14-03"])
            with open(os.path.join(opened[1], "report.txt"), encoding="utf-8") as f:
                report = f.read()
            self.assertIn(f"SteamID64: {DAN}", report)
            self.assertIn("The demo file is gone", report)

        Game(demos_dir=folder).play(script)


if __name__ == "__main__":
    unittest.main()
