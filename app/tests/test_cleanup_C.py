"""Cleanup task C: the Chat, Status and Help pages without their duplicates, the shared !top /
Kill race line, and the toolbox's wording, on a real App kept off-screen (made-up players)."""
import json
import os
import re
import unittest

from helpers import Game
from info_commands import INFO_COMMANDS
import web_state  # noqa: F401  (registers the pages and actions)
from web_chat_status_help import chat_state, help_state, status_state
from web_state import ACTIONS, run_action

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(path):
    with open(os.path.join(APP, path), encoding="utf-8") as f:
        return f.read()


class CleanupCTest(unittest.TestCase):
    def test_pages_have_no_duplicates(self):
        def script(g):
            a = g.app
            chat = g.on_screen_thread(lambda: chat_state(a))
            status = g.on_screen_thread(lambda: status_state(a))
            help_ = g.on_screen_thread(lambda: help_state(a))
            json.dumps([chat, status, help_])
            # Each Chat pill carries what its command does; Help only points to the Chat page.
            about = {c["id"]: c["about"] for c in chat["commands"]}
            self.assertTrue(all(about.values()))
            self.assertEqual(about["info:stats"], INFO_COMMANDS["stats"][1])
            cards = {c["id"]: c for c in help_["cards"]}
            self.assertEqual(cards["info"]["rows"], [])
            self.assertEqual(cards["info"]["link"]["page"], "Chat")
            self.assertEqual(list(cards), ["keys", "speak", "heavy", "duels", "info"])  # a short manual, in order
            self.assertIn("toolbox", cards["keys"]["rows"][0]["about"])
            # The chat counts are under Last posts; Status has no keys, chat counts or Mini HUD.
            self.assertEqual((chat["sent"], chat["refused"]), (a.chat_sent_count, a.chat_refused_count))
            self.assertEqual(set(status), {"connections", "health", "health_ok"})
            self.assertNotIn("the Duels page", json.dumps(help_) + json.dumps(status))
            # The Players page's Mini HUD switch uses these actions.
            self.assertIn("hud_toggle", ACTIONS)
            self.assertIn("hud_move", ACTIONS)
        Game().play(script)

    def test_kill_race_and_top_say_the_same(self):
        def script(g):
            a = g.app
            me, hank, dan = (a.sid_by_name(n) for n in ("tomato", "Hank", "dan"))
            self.assertEqual(a.top_line(), "[TOP] Scores not known yet (needs -g15)")
            self.assertIsNone(a.top_line(unknown=None))
            a.reevaluate = lambda: None  # keeps the scoreboard set here
            a.board = {me: {"m_iTeam": "2", "m_iScore": "8", "m_iDeaths": "5"},
                       dan: {"m_iTeam": "2", "m_iScore": "3", "m_iDeaths": "7"},
                       hank: {"m_iTeam": "3", "m_iScore": "18", "m_iDeaths": "16"}}
            line = g.on_screen_thread(lambda: a.top_line())
            self.assertEqual(line, "[TOP] Kills: RED 11 - 18 BLU | RED: tomato 8/5 | BLU: Hank 18/16")
            posted = []
            a.post = posted.append
            g.on_screen_thread(lambda: run_action(a, "players_lobby", ["kill_race"]))
            self.assertEqual(posted, [line])
        Game().play(script)

    def test_no_scanner_wording_and_sidebar(self):
        page = read("web/pages/chat_status_help.js")
        index = read("web/index.html")
        for text in (page, index, read("web/bridge.js"), read("web_chat_status_help.py")):
            self.assertNotRegex(text, re.compile("scanner", re.I))
        # The Duels page is labelled HoovyGPT in the sidebar, but stays "duels" / "Duels" inside.
        self.assertRegex(index, r'data-p="duels"><svg[^\n]*</svg>HoovyGPT</button>')
        self.assertIn('"Duels": "duels"', read("web/bridge.js"))
        self.assertIn(".side-foot .fserver{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}", index)
        self.assertNotIn("hud-sw", page)  # the Mini HUD switch is on the Players page


if __name__ == "__main__":
    unittest.main()
