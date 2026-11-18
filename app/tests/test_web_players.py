"""The web window's Players page: its state (web_players.players_state) and its actions, on a real App."""
import json
import os
import tempfile
import time
import unittest

from helpers import Game, ME
from game_log import STEAM64_BASE
from player_flags import Player
import web_players
import web_state

HANK, DAN = STEAM64_BASE + 2, STEAM64_BASE + 3


def board(a, sid, team, hp, kills, deaths):
    a.board[sid] = {"m_iTeam": str(team), "m_iHealth": str(hp), "m_iScore": str(kills), "m_iDeaths": str(deaths),
                    "m_bAlive": "true", "m_iAccountID": str(sid - STEAM64_BASE), "m_bConnected": "true"}


def setup(a):
    """tomato (you) and Hank on BLU, dan on RED with a VAC ban."""
    a.refresh_board = lambda: None  # keep the made-up scoreboard
    board(a, ME, 3, 150, 4, 2)
    board(a, HANK, 3, 140, 7, 5)
    board(a, DAN, 2, 125, 14, 1)
    a.classes.update({ME: "Medic", HANK: "Soldier", DAN: "Sniper"})
    a.flags[DAN] = [(3, "VAC ban"), (2, "92% headshots")]
    a.reevaluate = lambda: None


def rows(state):
    return [r for t in state["teams"] for r in t["rows"] if "sid" in r]


class WebPlayersTest(unittest.TestCase):
    def test_state_shows_both_teams_with_their_cells(self):
        icons = tempfile.mkdtemp()
        with open(os.path.join(icons, "Sniper-20px.png"), "wb") as f:
            f.write(b"\x89PNG fake")
        old_dir, web_players.CLASS_ICONS_DIR = web_players.CLASS_ICONS_DIR, icons

        def script(g):
            a = g.app
            g.on_screen_thread(lambda: setup(a))
            s = g.on_screen_thread(lambda: web_players.players_state(a))
            json.dumps(s)  # the page gets it as JSON
            self.assertEqual([t["name"] for t in s["teams"]], ["YOUR TEAM", "ENEMY TEAM"])
            mine, enemy = s["teams"]
            self.assertEqual((mine["colour"], mine["count"], mine["flagged"]), ("BLU", 2, 0))
            self.assertEqual((enemy["colour"], enemy["count"], enemy["flagged"]), ("RED", 1, 1))
            self.assertIn(["1", "Sniper"], enemy["lineup"])
            counts = {f["key"]: f["n"] for f in s["filters"]}
            self.assertEqual(counts, {"all": 3, "flagged": 1, "cheaters": 1, "new": 0})
            self.assertEqual(s["empty"], "")
            self.assertIsNone(s["panel"])
            dan = next(r for r in rows(s) if r["sid"] == str(DAN))  # a string: too big for JS numbers
            cells = dict(zip(s["all_columns"], dan["cells"]))
            self.assertEqual(cells["Mark"]["m"], "red")
            self.assertEqual(cells["Flags"]["tag"][0], "BANNED")
            self.assertNotIn("t", cells["Flags"])  # only the stamp (and the score's chip): no cut-off reason text
            self.assertEqual((cells["HP"]["t"], cells["HP"]["max"], cells["HP"]["pct"]), ("125", 125, 100))
            self.assertEqual((cells["K/D"]["k"], cells["K/D"]["d"]), ("14", "1"))
            self.assertTrue(cells["Class"]["img"].startswith("data:image/png;base64,"))
            me = next(r for r in rows(s) if r["sid"] == str(ME))
            self.assertTrue(dict(zip(s["all_columns"], me["cells"]))["Player"]["you"])
            self.assertIsNone(dict(zip(s["all_columns"], me["cells"]))["Class"]["img"])  # no Medic icon: the name
            for column in ("Mark", "Class", "Player", "HP", "K/D", "Flags"):
                self.assertIn(column, s["shown"])
        try:
            Game().play(script)
        finally:
            web_players.CLASS_ICONS_DIR = old_dir

    def test_toolbar_actions(self):
        def script(g):
            a = g.app
            g.on_screen_thread(lambda: setup(a))

            def run(name, *args):
                g.on_screen_thread(lambda: web_state.run_action(a, name, list(args)))
                return g.on_screen_thread(lambda: web_players.players_state(a))
            s = run("players_filter", "cheaters")
            self.assertEqual(a.cfg["player_filter"], "cheaters")
            self.assertEqual({r["sid"] for r in rows(s)}, {str(ME), str(DAN)})  # you always stay
            s = run("players_filter", "all")
            s = run("players_search", "han")
            self.assertEqual({r["sid"] for r in rows(s)}, {str(HANK)})
            s = run("players_search", "zzz")
            self.assertEqual(s["empty"], "Nobody here matches that.")
            s = run("players_search", "")
            before = "Streak" in a.cfg["columns"]
            s = run("players_column", "Streak")
            self.assertNotEqual("Streak" in a.cfg["columns"], before)
            self.assertEqual(next(c["on"] for c in s["columns"] if c["key"] == "Streak"), not before)
            s = run("players_sort", "K/D")
            self.assertEqual(s["sort"], ["K/D", True])
            g.sent.clear()
            run("players_lobby", "kill_race")
            run("players_lobby", "summary")
            g.on_screen_thread(lambda: None)
            self.assertTrue(g.commands.qsize() or g.sent)
        Game().play(script)

    def test_selected_player_panel_and_its_buttons(self):
        def script(g):
            a = g.app
            g.on_screen_thread(lambda: setup(a))

            def run(name, *args):
                g.on_screen_thread(lambda: web_state.run_action(a, name, list(args)))
                return g.on_screen_thread(lambda: web_players.players_state(a))
            s = run("players_select", str(DAN))
            p = s["panel"]
            self.assertEqual((p["name"], p["side"], p["cls"], p["enemy"]), ("dan", "Enemy", "Sniper", True))
            self.assertNotIn("kd", p)  # K/D and HP are in the row; the ratio is on the about line
            self.assertIn("K/D ratio 14.00", p["about"])
            # every flag is a clue line with a multiplier (here x1: no ban data or kills behind them)
            self.assertEqual({r["text"] for r in p["reasons"]}, {"VAC ban", "92% headshots"})
            self.assertTrue(all(r["lr"].startswith("×") and "level" not in r for r in p["reasons"]))
            buttons = {key: (text, on) for group in p["actions"] for key, text, on, _ in group}
            self.assertEqual(buttons["kick"], ("Votekick", False))  # an enemy: votes only work on your team
            self.assertTrue(buttons["mark"][1] and buttons["history"][1] and buttons["say"][1])
            self.assertTrue(next(r for r in rows(s) if r["sid"] == str(DAN))["sel"])
            s = run("players_act", "mark")
            self.assertIn(str(DAN), a.marks)
            self.assertEqual({k: t for g_ in s["panel"]["actions"] for k, t, *_ in g_}["mark"], "Unmark as cheater")
            first = s["panel"]["reasons"][0]  # your mark: a clue line of its own, first, labelled as yours
            self.assertEqual((first["you"], first["text"], first["lr"]), (True, "cheater", "×150"))
            run("players_act", "mark")
            s = run("players_act", "mute")
            self.assertIn(DAN, a.cfg["speak_muted"])
            self.assertEqual({k: t for g_ in s["panel"]["actions"] for k, t, *_ in g_}["mute"], "Allow their !speak")
            run("players_act", "mute")
            g.sent.clear()
            run("players_act", "say")
            self.assertTrue(g.commands.qsize() or g.sent)
            s = run("players_select", str(HANK))
            self.assertEqual((s["panel"]["side"], s["panel"]["reasons"]), ("Team", []))
            self.assertNotIn("seen", s["panel"])  # nothing remembered from earlier matches
            s = run("players_deselect")
            self.assertIsNone(s["panel"])
            self.assertIsNone(a.selected)
        Game().play(script)

    def test_players_whose_team_is_not_known(self):
        def script(g):
            a = g.app
            g.on_screen_thread(lambda: setup(a))
            g.on_screen_thread(lambda: a.board.pop(HANK))
            s = g.on_screen_thread(lambda: web_players.players_state(a))
            enemy = s["teams"][-1]
            self.assertIn({"sub": "TEAM NOT KNOWN YET"}, enemy["rows"])
            self.assertEqual(enemy["count"], 1)  # only the enemy team's own players
        Game().play(script)

    def test_likely_together_groups(self):
        """Same team and joined within 5 s of each other: a group. The other team, 10 s apart, or a
        group of one: not."""
        AMY, BOB, CAL, EVE = (STEAM64_BASE + n for n in (20, 21, 22, 23))

        def script(g):
            a = g.app

            def arrange():
                setup(a)
                now = time.time()
                # join moment = last_seen - connected (status measured it at their last line)
                joined = {ME: 500, HANK: 300, DAN: 297, AMY: 297, BOB: 290, CAL: 600, EVE: 700}
                for n, sid in enumerate((AMY, BOB, CAL, EVE)):
                    a.players[sid] = Player(sid, f"[U:1:{sid - STEAM64_BASE}]", 30 + n, ["amy", "bob", "cal", "eve"][n], 0, 0)
                board(a, AMY, 3, 125, 0, 0)  # BLU, like Hank
                board(a, BOB, 3, 125, 0, 0)  # BLU, 10 s before Hank
                board(a, CAL, 2, 125, 0, 0)  # RED, alone
                board(a, EVE, 3, 125, 0, 0)  # BLU, alone
                for sid, at in joined.items():
                    p = a.players[sid]
                    p.last_seen = now - 2 if sid == AMY else now  # an older status line: still the same moment
                    p.connected = int(p.last_seen - (now - 1000 + at))
            g.on_screen_thread(arrange)
            s = g.on_screen_thread(lambda: web_players.players_state(a))
            json.dumps(s)
            self.assertEqual([(gr["colour"], sorted(gr["sids"])) for gr in s["groups"]],
                             [("BLU", sorted([str(HANK), str(AMY)]))])  # Dan joined then too, but on RED
            mine, enemy = s["teams"]
            self.assertEqual((mine["groups"], enemy["groups"]), (1, 0))
            grp = {r["sid"]: r["grp"] for r in rows(s)}
            self.assertEqual((grp[str(HANK)], grp[str(AMY)]), (1, 1))
            self.assertIsNone(grp[str(BOB)])
            self.assertIsNone(grp[str(DAN)])
            self.assertIsNone(grp[str(EVE)])
            self.assertIsNone(grp[str(ME)])
            self.assertIn("within 5 seconds", s["together_why"])
            g.on_screen_thread(lambda: web_state.run_action(a, "players_select", [str(HANK)]))
            s = g.on_screen_thread(lambda: web_players.players_state(a))
            self.assertEqual(s["panel"]["together"], {"n": 1, "names": ["amy"]})
            g.on_screen_thread(lambda: web_state.run_action(a, "players_select", [str(EVE)]))
            s = g.on_screen_thread(lambda: web_players.players_state(a))
            self.assertIsNone(s["panel"]["together"])
            # Within 5 s of the group's first joiner, Bob too; a whole team at once (a map change) is no party.
            g.on_screen_thread(lambda: setattr(a.players[BOB], "connected", a.players[BOB].connected - 7))
            s = g.on_screen_thread(lambda: web_players.players_state(a))
            self.assertEqual(sorted(s["groups"][0]["sids"]), sorted([str(BOB), str(HANK), str(AMY)]))

            def everyone_at_once():
                for sid in (ME, HANK, AMY, BOB, EVE):
                    a.players[sid].last_seen, a.players[sid].connected = time.time(), 60
                for n in range(4):
                    sid = STEAM64_BASE + 30 + n
                    a.players[sid] = Player(sid, f"[U:1:{30 + n}]", 40 + n, f"extra{n}", 60, 0, last_seen=time.time())
                    board(a, sid, 3, 125, 0, 0)
            g.on_screen_thread(everyone_at_once)
            s = g.on_screen_thread(lambda: web_players.players_state(a))
            self.assertEqual([gr for gr in s["groups"] if gr["colour"] == "BLU"], [])
        Game().play(script)


if __name__ == "__main__":
    unittest.main()
