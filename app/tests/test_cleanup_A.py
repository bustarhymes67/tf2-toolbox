"""Players page cleanup: one scoring system in WHY FLAGGED (the cheater score's multipliers, every
flag still shown as a clue), your mark as a clue, the Flags column only a stamp and the score, one
Say in chat menu, the Mini HUD switch in the toolbar, the team line and legend in hovers."""
import json
import os
import re
import unittest
from collections import Counter

from helpers import Game, ME
import cheat_score as cs
from game_log import STEAM64_BASE
from player_flags import Player
from settings import DEFAULTS
import web_players
import web_state

SID = STEAM64_BASE + 60
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FakeApp:
    def __init__(self, **kw):
        self.me, self.cfg = ME, dict(DEFAULTS)
        self.lists, self.marks, self.flags = {}, {}, {}
        self.kills, self.crits, self.weapons = {}, {}, {}
        self.__dict__.update(kw)

    def demo_checks_of(self, sid):
        return Counter()


def player(**kw):
    p = Player(SID, "[U:1:60]", 60, "someone", 0, 0)
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def read(*parts):
    with open(os.path.join(HERE, *parts), encoding="utf-8") as f:
        return f.read()


class EveryFlagIsAClue(unittest.TestCase):
    def setUp(self):
        self.saved = list(cs.CLUE_SOURCES)
        cs.CLUE_SOURCES[:] = list(cs.BUILTIN_SOURCES)

    def tearDown(self):
        cs.CLUE_SOURCES[:] = self.saved

    def test_flags_without_their_own_clue_get_one_that_moves_nothing(self):
        flags = [(2, "on list three list (racist)"), (1, "trade probation"), (0, "friends in lobby: Ann, Bo"),
                 (2, "80% headshots (8/10 sniper kills)"), (1, "a kind of flag nobody knows yet")]
        app = FakeApp(flags={SID: flags}, lists={SID: {"attributes": {"racist"}, "sources": ["list three"]}},
                      kills={SID: [10, 8]})
        sc = cs.score(app, player())
        for _, text in flags:
            clue = cs.flag_clue(text, sc.clues)
            self.assertIsNotNone(clue, text)
            self.assertEqual(clue.lr, 1.0, text)  # shown, but none of these changes the odds
            self.assertTrue(clue.why, text)
        self.assertAlmostEqual(sc.prob, cs.PRIOR)
        self.assertEqual(sc.band, "Clean")
        hs = next(c for c in sc.clues if c.key == "hs_rate")
        self.assertIn("by luck", hs.why)  # 8/10 at 50%: luck explains it
        few = cs.score(FakeApp(flags={SID: [(2, "100% headshots (6/6 sniper kills)")]}, kills={SID: [6, 6]}), player())
        self.assertIn("too few", next(c for c in few.clues if c.key == "hs_rate").why)

    def test_a_real_rate_clue_replaces_the_small_sample_one(self):
        app = FakeApp(flags={SID: [(2, "92% headshots (24/26 sniper kills)")]}, kills={SID: [26, 24]})
        hs = next(c for c in cs.score(app, player()).clues if c.key == "hs_rate")
        self.assertGreater(hs.lr, 1.0)

    def test_list_and_server_ban_clues_keep_what_the_flag_said(self):
        app = FakeApp(lists={SID: {"attributes": {"cheater"}, "sources": ["alpha"]}})
        self.assertEqual(cs.score(app, player()).clues[0].text, "on 1 cheater list (cheater): alpha")
        bans = [{"Server": "srv one", "Reason": "aimbot"}, {"Server": "srv two", "Reason": "Aimbot"}]
        clue = next(c for c in cs.score(FakeApp(), player(sourcebans=bans)).clues if c.key == "server_bans")
        self.assertEqual(clue.text, "banned for cheating by 2 server communities: aimbot")

    def test_why_flagged_is_one_system_with_your_mark_first(self):
        app = FakeApp(flags={SID: [(3, "marked by you as cheater"), (1, "trade banned")]},
                      marks={str(SID): {"reason": "cheater"}},
                      lists={SID: {"attributes": {"cheater"}, "sources": ["a", "b", "c"]}})
        p = player()
        reasons = web_players.reasons_json(app, p, cs.score(app, p))
        self.assertEqual(reasons[0]["key"], cs.MARK_KEY)
        self.assertTrue(reasons[0]["you"])
        self.assertEqual(reasons[0]["text"], "cheater")
        for r in reasons:
            self.assertEqual(set(r), {"key", "text", "why", "lr", "up", "proof", "you"})  # no WEAK/STRONG level
            self.assertTrue(r["lr"].startswith("×"))
        self.assertIn("trade banned", [r["text"] for r in reasons])


class PageTests(unittest.TestCase):
    def test_state_has_the_hud_the_team_info_and_no_panel_boxes(self):
        def script(g):
            a = g.app

            def arrange():
                a.refresh_board = lambda: None
                a.reevaluate = lambda: None
                for sid, team in ((ME, 3), (STEAM64_BASE + 2, 3), (STEAM64_BASE + 3, 2)):
                    a.board[sid] = {"m_iTeam": str(team), "m_iHealth": "125", "m_iScore": "3", "m_iDeaths": "1",
                                    "m_bAlive": "true", "m_iAccountID": str(sid - STEAM64_BASE), "m_bConnected": "true"}
                a.players[STEAM64_BASE + 3].hours = 700
                a.flags[STEAM64_BASE + 3] = [(1, "only 40h in TF2")]
                a.select(STEAM64_BASE + 3)
            g.on_screen_thread(arrange)
            s = g.on_screen_thread(lambda: web_players.players_state(a))
            json.dumps(s)
            self.assertEqual(s["hud"], bool(a.cfg["hud"]))
            self.assertFalse(s["hud_moving"])
            self.assertIn("5 s", s["together_short"])
            enemy = next(t for t in s["teams"] if t["colour"] == "RED")
            self.assertIn("average 700 hours", enemy["info"])  # on the title line's hover
            self.assertFalse(any("hours" in what for _, what in enemy["lineup"]))
            row = next(r for r in enemy["rows"] if r.get("sid") == str(STEAM64_BASE + 3))
            flags = dict(zip(s["all_columns"], row["cells"]))["Flags"]
            self.assertEqual(flags["tag"][0], "WEAK")  # a weak flag still shows a stamp
            for gone in ("verdict", "kd", "ratio", "hp"):
                self.assertNotIn(gone, s["panel"])
            # the Mini HUD switch uses the Status page's actions
            before = a.cfg["hud"]
            g.on_screen_thread(lambda: web_state.run_action(a, "hud_toggle", []))
            self.assertNotEqual(g.on_screen_thread(lambda: web_players.players_state(a))["hud"], before)
            g.on_screen_thread(lambda: web_state.run_action(a, "hud_toggle", []))
        Game().play(script)

    def test_page_script_and_styles(self):
        js, css = read("web", "pages", "players.js"), read("web", "pages", "players.css")
        # one Say in chat menu in the toolbar, with both lobby lines
        self.assertIn('id="pl-saybtn"', js)
        self.assertNotIn("saygrp", js)
        self.assertIn('data-lobby="summary"', js)
        self.assertIn('data-lobby="kill_race"', js)
        # Mini HUD switch and Move
        self.assertIn('act("hud_toggle")', js)
        self.assertIn('act("hud_move")', js)
        # the legend is a "?" hover, the K/D-ratio-HP boxes and the strength boxes are gone
        self.assertIn("pl-legbtn", js)
        self.assertNotIn('class="legend"', js)
        self.assertNotIn("dstats", js)
        self.assertNotIn("str ${", js)
        self.assertNotIn("pl-ftx", js)
        # the card's Post in chat buttons: two by two, so "Post their friends here" isn't cut
        self.assertIn(".pl-agrid{display:grid;grid-template-columns:1fr 1fr", css)
        # the group chip: a link icon and the number, with a short tooltip
        self.assertIn("${LINK}${n}</span>", js)

    def test_no_scanner_wording(self):
        for parts in (("web_players.py",), ("web", "pages", "players.js"), ("web", "pages", "players.css"),
                      ("cheat_score.py",), ("player_flags.py",)):
            self.assertIsNone(re.search(r"\bscanner\b", read(*parts), re.I), parts)


if __name__ == "__main__":
    unittest.main()
