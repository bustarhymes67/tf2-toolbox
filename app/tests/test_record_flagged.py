"""Recording demos only while a flagged player is in the match (record_only_flagged): ds_record once,
ds_stop a minute after the last flagged player left, nothing twice, and the page's recording line."""
import time
import unittest
from unittest import mock

from helpers import Game, ME  # first: it puts the app's folder on the path
import tf2_lobby_scanner
import web_state  # noqa: F401  (registers the pages and actions)
from game_log import STEAM64_BASE
from web_cheat_duels import cheat_state
from web_state import run_action

HANK, DAN = STEAM64_BASE + 2, STEAM64_BASE + 3  # in helpers.Game's STATUS


def ds_commands(g):
    """The demo commands sent so far (nothing reads the queue in the tests: it keeps them all)."""
    return [c for c in list(g.commands.queue) if c.startswith("ds_")]


class RecordFlaggedTest(unittest.TestCase):
    def test_flagged_players_start_and_stop_the_recording(self):
        def script(g):
            a = g.app
            run = g.on_screen_thread

            # The app's own ticks use the clock; here the test sets the time.
            a.record_flagged_tick = lambda now=None: None

            def tick(now):
                run(lambda: tf2_lobby_scanner.App.record_flagged_tick(a, now))

            now = time.time()
            self.assertEqual(run(lambda: cheat_state(a)["recording"]), {"on": False, "text": "Not recording"})
            tick(now)
            self.assertEqual(ds_commands(g), [])  # nobody flagged

            # Only severity 2 or more (or your mark) counts, and never you.
            def flagged_with(flags):
                a.flags = flags
                return a.flagged_in_match()
            self.assertFalse(run(lambda: flagged_with({HANK: [(1, "new account")]})))
            self.assertTrue(run(lambda: flagged_with({HANK: [(2, "VAC banned")]})))
            self.assertFalse(run(lambda: flagged_with({ME: [(3, "on a cheater list")]})))

            run(lambda: a.marks.__setitem__(str(HANK), {"name": "Hank", "reason": "cheater"}))
            for later in (0, 1, 2):
                tick(now + later)
            self.assertEqual(ds_commands(g), ["ds_record"])  # once, however many ticks
            s = run(lambda: cheat_state(a))
            self.assertEqual(s["recording"], {"on": True, "text": "Recording: flagged player in the match"})
            self.assertTrue(s["recording"])

            # Hank leaves (unmarked here): stops after a minute without anyone flagged, not before.
            run(lambda: a.marks.pop(str(HANK)))
            tick(now + 10)
            tick(now + 10 + 59)
            self.assertEqual(ds_commands(g), ["ds_record"])
            tick(now + 10 + 60)
            self.assertEqual(ds_commands(g), ["ds_record", "ds_stop"])
            tick(now + 200)
            self.assertEqual(ds_commands(g), ["ds_record", "ds_stop"])

            # Flagged again after the stop: a new recording. Back within the minute: no stop.
            run(lambda: a.marks.__setitem__(str(DAN), {"name": "dan", "reason": "cheater"}))
            tick(now + 300)
            run(lambda: a.marks.pop(str(DAN)))
            tick(now + 310)
            run(lambda: a.marks.__setitem__(str(DAN), {"name": "dan", "reason": "cheater"}))
            tick(now + 340)
            tick(now + 400)
            self.assertEqual(ds_commands(g), ["ds_record", "ds_stop", "ds_record"])

            # A new map ends TF2's recording: recorded again once the map has loaded.
            run(lambda: a.handle_line("Client reached server_spawn."))
            self.assertFalse(a.recording)
            loaded = a.match_joined_at
            tick(loaded + 1)
            self.assertEqual(ds_commands(g).count("ds_record"), 2)
            tick(loaded + tf2_lobby_scanner.RECORD_AFTER_JOIN)
            self.assertEqual(ds_commands(g).count("ds_record"), 3)

            # Switched off (or the cheat check off): the scanner never types ds_record.
            run(lambda: a.handle_line("Client reached server_spawn."))
            a.cfg["record_only_flagged"] = False
            tick(time.time() + 1000)
            self.assertEqual(ds_commands(g).count("ds_record"), 3)
            self.assertEqual(run(lambda: cheat_state(a)["recording"]), None)  # every match: the switch says it
            a.cfg["record_only_flagged"], a.cfg["demo_check"] = True, False
            tick(time.time() + 1000)
            self.assertEqual(ds_commands(g).count("ds_record"), 3)
            self.assertEqual(run(lambda: cheat_state(a)["recording"]), None)  # cheat check off: the switch says it
            a.cfg["demo_check"] = True
            tick(time.time() + 1000)
            self.assertEqual(ds_commands(g).count("ds_record"), 4)

            # Leaving the server: TF2 stopped by itself, so no ds_stop, and nothing is typed in the
            # menu while the old player list is still shown.
            run(lambda: a.handle_line("Disconnect: Server shutting down"))
            self.assertFalse(a.recording)
            tick(time.time() + 2000)
            self.assertEqual(ds_commands(g).count("ds_stop"), 1)
            self.assertEqual(ds_commands(g).count("ds_record"), 4)

        Game(demo_check=True, record_only_flagged=True).play(script)

    def test_without_rcon_nothing_is_typed(self):
        def script(g):
            a = g.app
            g.events.put(("rcon", "not connected"))
            time.sleep(0.4)
            g.on_screen_thread(lambda: a.marks.__setitem__(str(HANK), {"name": "Hank", "reason": "cheater"}))
            g.on_screen_thread(lambda: a.record_flagged_tick(time.time() + 100))
            time.sleep(0.3)  # the app's own ticks too
            self.assertEqual(ds_commands(g), [])
            self.assertFalse(a.recording)

        Game(demo_check=True, record_only_flagged=True).play(script)

    def test_the_switch_tells_tf2_its_recording_mode(self):
        def script(g):
            a = g.app
            with mock.patch.object(tf2_lobby_scanner, "DEMO_TOOL", tf2_lobby_scanner.__file__):  # "installed"
                g.on_screen_thread(lambda: run_action(a, "cheat_toggle_record", []))
                self.assertFalse(a.cfg["record_only_flagged"])
                self.assertFalse(g.on_screen_thread(lambda: cheat_state(a))["record_only"])
                g.on_screen_thread(lambda: run_action(a, "cheat_toggle_record", []))
                self.assertTrue(a.cfg["record_only_flagged"])
                self.assertEqual(ds_commands(g), ["ds_enable 2", "ds_enable 0"])
                # Connecting again tells TF2 too, as the launch option does at start.
                g.events.put(("rcon", "not connected"))
                g.events.put(("rcon", "connected"))
                time.sleep(0.4)
                self.assertEqual(ds_commands(g), ["ds_enable 2", "ds_enable 0", "ds_enable 0"])
            # Without demo-analysis nothing is recorded for it, so ds_enable is left alone.
            g.on_screen_thread(lambda: run_action(a, "cheat_toggle_record", []))
            self.assertEqual(len(ds_commands(g)), 3)

        Game(demo_check=True, record_only_flagged=True).play(script)


if __name__ == "__main__":
    unittest.main()
