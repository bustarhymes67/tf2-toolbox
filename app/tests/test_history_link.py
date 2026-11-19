"""A cheater's SteamHistory link: "Post their summary" posts it as a second line (and its hover shows
it); for anyone else it posts the summary alone. Made-up players, no real network."""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers import Game  # noqa: E402
import web_players  # noqa: E402


class HistoryLinkTest(unittest.TestCase):
    def test_post_their_summary_adds_the_link_for_a_cheater_only(self):
        def script(g):
            a = g.app
            a.reevaluate = lambda: None
            a.rcon_state = "connected"
            hank, dan = a.sid_by_name("Hank"), a.sid_by_name("dan")
            a.flags[hank] = [(3, "1 VAC ban (36d ago)")]
            link = f"Hank | ban history: https://steamhistory.net/id/{hank}"
            self.assertEqual(a.history_line(a.players[hank]), link)
            self.assertIsNone(a.history_line(a.players[dan]))

            g.on_screen_thread(lambda: a.select(hank))
            hover = g.on_screen_thread(lambda: web_players.player_previews(a, a.players[hank]))["say"]["text"]
            self.assertEqual(hover.split("\n"), [a.chat_text(a.players[hank]), link])
            g.on_screen_thread(a.say_in_chat)
            deadline = time.time() + 20
            while time.time() < deadline and len(g.said()) < 2:
                time.sleep(0.2)
            self.assertEqual(g.said(), [a.chat_text(a.players[hank]), link])

            before = len(g.said())
            g.on_screen_thread(lambda: a.select(dan))
            g.on_screen_thread(a.say_in_chat)
            deadline = time.time() + 20
            while time.time() < deadline and len(g.said()) < before + 1:
                time.sleep(0.2)
            time.sleep(1.0)
            self.assertEqual(g.said()[before:], [a.chat_text(a.players[dan])])  # not a cheater: no link
        Game().play(script)


if __name__ == "__main__":
    unittest.main()
