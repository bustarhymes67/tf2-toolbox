"""The info commands anyone can type in chat (info_commands.py), in a real App."""
import contextlib
import io
import os
import tempfile
import time
import unittest

from helpers import Game
import info_commands
import tf2_lobby_scanner


class InfoCommandsTest(unittest.TestCase):
    def test_every_command_answers(self):
        def script(g):
            a = g.app
            me, hank, dan = (a.sid_by_name(n) for n in ("tomato", "Hank", "dan"))
            a.reevaluate = lambda: None  # keeps the scoreboard and flags set here
            a.board = {me: {"m_iTeam": "2", "m_iScore": "8", "m_iDeaths": "5", "m_iHealth": "200", "m_bAlive": "true"},
                       dan: {"m_iTeam": "2", "m_iScore": "3", "m_iDeaths": "7", "m_iHealth": "70", "m_bAlive": "true"},
                       hank: {"m_iTeam": "3", "m_iScore": "18", "m_iDeaths": "16", "m_iHealth": "87", "m_bAlive": "true"}}
            a.classes.update({me: "Soldier", dan: "Medic", hank: "Sniper"})
            a.players[hank].hours = 2621
            a.flags[hank] = [(3, "1 VAC ban (36d ago)")]
            asked = [("!check han", "[CHECK] Hank (BLU) | Sniper | 87/125 HP"),
                     ("!check all", "[CHECK] BLU: 1 Sniper"),  # dan is on RED: the other team is BLU
                     ("!stats", a.stats_line()),
                     ("!hours hank", "[HOURS] Hank (BLU) | 2,621 hours in TF2"),
                     ("!cheaters", "[CHEATERS] Hank (1 VAC ban)"),
                     ("!check zzz", "[CHECK] nobody here is called 'zzz'"),
                     ("!check", "[CHECK] Type !check <name>, or !check all. Part of a name works")]
            for typed, answer in asked:
                g.say("dan", typed)
                deadline = time.time() + 20  # TF2's spam limit makes later lines wait
                while time.time() < deadline and answer not in g.said():
                    time.sleep(0.2)
                self.assertIn(answer, g.said(), typed)
            a.board[hank]["m_bAlive"] = "false"
            self.assertEqual(a.check_line(a.players[hank]), "[CHECK] Hank (BLU) | Sniper | dead")
            a.board[hank].update(m_bAlive="true", m_iHealth="185")
            self.assertEqual(a.health_words(a.players[hank]), "185/125 HP (overhealed)")
            help_line = a.help_line()
            self.assertTrue(help_line.startswith("[HELP] !who"), help_line)
            self.assertFalse(help_line.endswith("more"), help_line)  # every command named, in one message
            self.assertIn("Kills RED 11 - 18 BLU | MVP Hank 18/16", a.stats_line())
            for gone in ("!medic", "!top", "!kd"):
                self.assertNotIn(gone, help_line)
            g.on_screen_thread(lambda: a.toggle_info_command("stats"))
            self.assertFalse(a.cfg["info_commands"]["stats"])
            self.assertNotIn("!stats", a.help_line())
            before = len(g.sent)
            g.say("dan", "!stats", 1.0)
            self.assertEqual(len(g.sent), before)  # switched off: no answer
        Game().play(script)

    def test_ip_gives_a_player_the_same_address_every_time(self):
        def script(g):
            a = g.app
            hank = a.players[a.sid_by_name("Hank")]
            self.assertIsNone(info_commands.__dict__.get("FAKE_IPS_PATH"))
            g.say("dan", "!ip han")
            deadline = time.time() + 10
            while time.time() < deadline and not any("IPv4" in line for line in g.said()):
                time.sleep(0.2)
            first = next(line for line in g.said() if "IPv4" in line)
            self.assertTrue(first.startswith("Hank | IPv4 "))
            self.assertEqual(a.ip_line(hank), first)  # again: the same address
            self.assertEqual(first, a.ip_line(hank))  # and the panel button says the same
            g.say("dan", "!ip toma")  # at you
            deadline = time.time() + 15
            while time.time() < deadline and "tomato | same WiFi as your mom" not in g.said():
                time.sleep(0.2)
            self.assertIn("tomato | same WiFi as your mom", g.said())
            other = a.ip_line(a.players[a.sid_by_name("dan")])
            self.assertNotEqual(other.split("IPv4 ")[1], "")
        Game().play(script)

    def test_fake_ips_last_one_match_only(self):
        def script(g):
            a = g.app
            hank, dan = (a.players[a.sid_by_name(n)] for n in ("Hank", "dan"))

            def ips():
                return g.on_screen_thread(lambda: (a.fake_ip_of(hank), a.fake_ip_of(dan)))
            first = ips()
            self.assertEqual(ips(), first)  # the same all match
            self.assertEqual(set(a.fake_ips), {str(hank.sid), str(dan.sid)})
            g.on_screen_thread(lambda: a.handle_line("Client reached server_spawn."))  # a new match
            self.assertEqual(a.fake_ips, {})
            second = ips()
            self.assertEqual(ips(), second)
            g.on_screen_thread(lambda: a.handle_line("Disconnect: Server shutting down"))  # you left
            self.assertEqual(a.fake_ips, {})
            self.assertEqual(len(ips()), 2)  # drawn again, from nothing kept
        Game().play(script)

    def test_old_player_memory_files_are_deleted_once(self):
        old = (tf2_lobby_scanner.SEEN_PATH, tf2_lobby_scanner.FAKE_IPS_PATH)
        with tempfile.TemporaryDirectory() as folder:
            seen, ips, keep = (os.path.join(folder, n) for n in ("seen_players.json", "fake_ips.json", "marks.json"))
            for path in (seen, seen + ".tmp", ips, keep):
                open(path, "w").close()
            tf2_lobby_scanner.SEEN_PATH, tf2_lobby_scanner.FAKE_IPS_PATH = seen, ips  # never your real files
            try:
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    tf2_lobby_scanner.forget_old_player_memory()
                    tf2_lobby_scanner.forget_old_player_memory()  # nothing left: no error, no line
            finally:
                tf2_lobby_scanner.SEEN_PATH, tf2_lobby_scanner.FAKE_IPS_PATH = old
            self.assertEqual(len(out.getvalue().splitlines()), 1)  # one line says so
            self.assertEqual(os.listdir(folder), ["marks.json"])  # only those, nothing else

    def test_kick_starts_a_vote_only_for_you_and_only_on_your_team(self):
        def script(g):
            a = g.app
            me, hank, dan = (a.sid_by_name(n) for n in ("tomato", "Hank", "dan"))
            a.reevaluate = lambda: None
            a.board = {me: {"m_iTeam": "2"}, dan: {"m_iTeam": "2"}, hank: {"m_iTeam": "3"}}
            votes = lambda: [c for c in g.sent if c.startswith("callvote")]
            g.say("dan", "!kick toma", 0.6)  # somebody else: ignored
            self.assertEqual(votes(), [])
            g.say("tomato", "!kick han", 0.6)  # the other team: no vote
            self.assertEqual(votes(), [])
            g.say("tomato", "!kick da", 0.6)  # part of a teammate's name
            self.assertEqual(votes(), [f'callvote kick "{a.players[dan].userid} cheating"'])
            g.say("tomato", "!kick toma", 0.6)  # yourself: allowed too
            self.assertEqual(votes()[-1], f'callvote kick "{a.players[me].userid} cheating"')
            self.assertEqual(len([c for c in g.sent if c.startswith("say")]), 0)  # nothing said in chat
        Game().play(script)

    def test_long_lists_end_with_how_many_more(self):
        line = info_commands.fit_list("[CHEATERS] ", [f"player_number_{n} (on 3 cheater lists)" for n in range(9)])
        self.assertLessEqual(len(line.encode()), 127)
        self.assertTrue(line.endswith("more"))


if __name__ == "__main__":
    unittest.main()
