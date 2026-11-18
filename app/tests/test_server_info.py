"""The server's name and player slots from TF2's status: read, shortened for the title bar, shown
in the web window and the Tk header, and forgotten when you leave."""
import json
import unittest

from helpers import Game  # first: it puts the app's folder on the path
import web_state
from game_log import HOSTNAME_RE, PLAYERS_RE, SERVER_NAME_CHARS, server_label

VALVE = "Valve Matchmaking Server (Frankfurt srcds5020-fra2 #228)"  # the status line's example from TF2
HOSTNAME_LINE = "hostname: " + VALVE
PLAYERS_LINE = "players : 24 humans, 0 bots (24 max)"
MAP_LINE = "map     : ctf_2fort at: 0 x, 0 y, 0 z"


class ServerLinesTest(unittest.TestCase):
    def test_hostname_and_players_lines(self):
        self.assertEqual(HOSTNAME_RE.match(HOSTNAME_LINE)[1], VALVE)
        m = PLAYERS_RE.match(PLAYERS_LINE)
        self.assertEqual((m[1], m[2], m[3]), ("24", "0", "24"))

    def test_chat_from_players_called_hostname_or_players_is_not_status(self):
        # Chat is "name :  message": a space before the colon and two after.
        self.assertIsNone(HOSTNAME_RE.match("hostname :  " + VALVE))
        self.assertIsNone(PLAYERS_RE.match("players :  24 humans, 0 bots (24 max)"))

    def test_valve_server_label_is_casual_and_its_region(self):
        self.assertEqual(server_label(VALVE), "Casual · Frankfurt")

    def test_community_server_label_is_its_name_cut(self):
        self.assertEqual(server_label(""), "")
        self.assertEqual(server_label("x" * SERVER_NAME_CHARS), "x" * SERVER_NAME_CHARS)
        long = server_label("x" * (SERVER_NAME_CHARS + 10))
        self.assertEqual(len(long), SERVER_NAME_CHARS)
        self.assertTrue(long.endswith("…"))


class ServerInAppTest(unittest.TestCase):
    def test_title_bar_footer_and_tk_header(self):
        def script(g):
            a = g.app

            def feed(*lines):
                g.on_screen_thread(lambda: [a.handle_line(line) for line in lines])

            def header():
                h = g.on_screen_thread(lambda: web_state.header(a))
                json.dumps(h)
                return h

            h = header()
            self.assertEqual((h["server"], h["slots"], h["hostname"], h["foot"]["server"]), ("", "", "", "-"))
            feed(HOSTNAME_LINE, MAP_LINE, PLAYERS_LINE)
            h = header()
            self.assertEqual((h["server"], h["slots"], h["map"]), ("Casual · Frankfurt", "24/24", "ctf_2fort"))
            self.assertEqual((h["hostname"], h["foot"]["server"]), (VALVE, VALVE))
            g.on_screen_thread(a.update_status)
            self.assertEqual(g.on_screen_thread(lambda: a.info.cget("text")),
                             "ctf_2fort · Casual · Frankfurt · 24/24 players")

            # A new server (or map): forgotten until its status names it.
            feed("Client reached server_spawn.")
            h = header()
            self.assertEqual((h["server"], h["slots"], h["foot"]["server"]), ("", "", "-"))
            feed(HOSTNAME_LINE, PLAYERS_LINE)
            self.assertEqual(header()["slots"], "24/24")
            # Leaving the server.
            feed("Disconnect: Server shutting down")
            h = header()
            self.assertEqual((h["server"], h["slots"], h["hostname"]), ("", "", ""))

        Game().play(script)


if __name__ == "__main__":
    unittest.main()
