"""The live cheater clues (live_clues.py): kill rate, spawn kills, chat accusations and bot behaviour,
each with too little data giving no clue, and the App hooks that collect their data for one match."""
import dataclasses
import importlib
import importlib.util
import sys
import time
import types
import unittest

from helpers import Game, ME
from game_log import STEAM64_BASE, G15_DONE
from player_flags import Player

# cheat_score.py is written by another task: when it isn't there yet, a stand-in only for this test.
_STUB = None
if importlib.util.find_spec("cheat_score") is None:
    _STUB = types.ModuleType("cheat_score")

    @dataclasses.dataclass
    class _Clue:
        key: str
        lr: float
        text: str
        why: str
        proof: bool = False
        source: str = ""

    _STUB.Clue, _STUB.CLUE_SOURCES = _Clue, []
    _STUB.register = lambda fn: (_STUB.CLUE_SOURCES.append(fn), fn)[1]
    sys.modules["cheat_score"] = _STUB
import live_clues  # noqa: E402
if _STUB is not None:
    live_clues = importlib.reload(live_clues)  # registers with the stand-in even if imported before
import cheat_score  # noqa: E402


def tearDownModule():
    if _STUB is not None and sys.modules.get("cheat_score") is _STUB:
        del sys.modules["cheat_score"]


HANK, DAN = STEAM64_BASE + 2, STEAM64_BASE + 3
NOW = 1_000_000.0


class FakeApp:
    """Just the parts of App the clues read."""

    def __init__(self):
        self.players, self.board, self.me = {}, {}, ME
        self.match_chat, self.name_changes, self.spawn_times, self.kill_times = [], {}, {}, []
        self.cfg = {"new_account_days": 90}
        self.teams = {}

    def add(self, n, name, minutes=10, kills=None, team="RED", joined=None):
        sid = STEAM64_BASE + n
        p = Player(sid, f"[U:1:{n}]", n, name, int(minutes * 60), 0)
        p.last_seen = NOW
        if joined is not None:
            p.connected = int(NOW - joined)
        self.players[sid] = p
        if kills is not None:
            self.board[sid] = {"m_iScore": str(kills)}
        self.teams[sid] = team
        return p

    def board_int(self, sid, field):
        v = self.board.get(sid, {}).get(field)
        return int(v) if v is not None else None

    def team_color(self, p):
        return self.teams.get(p.sid, "")


def lobby(top_kills, minutes=10):
    """Eleven players at about 1 kill/min, and Topper with top_kills."""
    a = FakeApp()
    for i, k in enumerate([8, 9, 10, 10, 11, 12, 9, 10, 11, 7]):
        a.add(10 + i, f"Normal{i}", minutes, k)
    top = a.add(50, "Topper", minutes, top_kills)
    return a, top


class RegistrationTest(unittest.TestCase):
    def test_all_four_registered(self):
        names = {getattr(fn, "__name__", "") for fn in cheat_score.CLUE_SOURCES}
        for fn in ("kill_rate_clues", "spawn_kill_clues", "accusation_clues", "bot_clues"):
            self.assertIn(fn, names)


class KillRateTest(unittest.TestCase):
    def clues(self, a, p):
        return live_clues.kill_rate_clues(a, p, now=NOW)

    def test_normal_player_no_clue(self):
        a, top = lobby(13)
        self.assertEqual(self.clues(a, top), [])

    def test_extreme_outlier_raises_up_to_five(self):
        a, top = lobby(60)  # 6 kills/min in a lobby of ~1
        [c] = self.clues(a, top)
        self.assertEqual((c.key, c.source), ("kill_rate", "live"))
        self.assertGreater(c.lr, 4.0)
        self.assertLessEqual(c.lr, 5.0)
        self.assertIn("kills/min", c.text)

    def test_curve_is_smooth_and_rising(self):
        lrs = [live_clues.kill_rate_lr(z) for z in (3.5, 4, 5, 6, 8, 20)]
        self.assertEqual(lrs[0], 1.0)
        self.assertEqual(lrs, sorted(lrs))
        self.assertLess(lrs[-1], 5.0)

    def test_not_enough_minutes_kills_or_lobby(self):
        a, top = lobby(60, minutes=4)  # under 5 minutes
        self.assertEqual(self.clues(a, top), [])
        a, top = lobby(7)  # under 8 kills
        self.assertEqual(self.clues(a, top), [])
        a = FakeApp()
        for i in range(4):
            a.add(10 + i, f"N{i}", 10, 10)
        top = a.add(50, "Topper", 10, 60)
        self.assertEqual(self.clues(a, top), [])  # only 5 players: no lobby spread to compare with

    def test_no_scoreboard_no_clue(self):
        a, top = lobby(60)
        a.board.pop(top.sid)
        self.assertEqual(self.clues(a, top), [])


class SpawnKillTest(unittest.TestCase):
    def setup(self, fast, slow, weapon="sniperrifle"):
        a = FakeApp()
        k = a.add(50, "Camper")
        victims = [a.add(60 + i, f"V{i}") for i in range(fast + slow)]
        for i, v in enumerate(victims):
            spawn = NOW + i * 100
            a.spawn_times[v.sid] = [spawn]
            a.kill_times.append((spawn + (2 if i < fast else 30), k.sid, v.sid, weapon))
        return a, k

    def test_repeated_sniper_spawn_kills(self):
        a, k = self.setup(fast=8, slow=2)
        [c] = live_clues.spawn_kill_clues(a, k)
        self.assertEqual(c.key, "spawn_kills")
        self.assertGreater(c.lr, 2.5)
        self.assertLessEqual(c.lr, 3.0)
        self.assertIn("8 of 10", c.text)
        self.assertIn("sniper", c.text)

    def test_other_weapons_capped_lower(self):
        a, k = self.setup(fast=8, slow=2, weapon="scattergun")
        [c] = live_clues.spawn_kill_clues(a, k)
        self.assertLessEqual(c.lr, 2.0)

    def test_honest_share_no_clue(self):
        a, k = self.setup(fast=2, slow=10)
        self.assertEqual(live_clues.spawn_kill_clues(a, k), [])

    def test_too_few_kills_no_clue(self):
        a, k = self.setup(fast=4, slow=0)  # 4 kills: under the 5 needed
        self.assertEqual(live_clues.spawn_kill_clues(a, k), [])

    def test_unknown_spawns_not_judged(self):
        a, k = self.setup(fast=8, slow=2)
        a.spawn_times.clear()
        self.assertEqual(live_clues.spawn_kill_clues(a, k), [])


class AccusationTest(unittest.TestCase):
    def setup(self):
        a = FakeApp()
        a.add(1, "tomato")
        accused = a.add(50, "xX_Sniperwolf_Xx")
        others = [a.add(60 + i, n) for i, n in enumerate(["Alice", "Bob", "Carol", "Dave"])]
        return a, accused, others

    def say(self, a, p, msg):
        a.match_chat.append((NOW, p.sid if p else None, p.name if p else "?", msg))

    def test_two_and_three_accusers(self):
        a, accused, (alice, bob, carol, _) = self.setup()
        self.say(a, alice, "sniperwolf is hacking")
        self.say(a, alice, "SNIPERWOLF AIMBOT")  # same accuser twice counts once
        self.assertEqual(live_clues.accusation_clues(a, accused), [])
        self.say(a, bob, "wolf читер")
        [c] = live_clues.accusation_clues(a, accused)
        self.assertEqual((c.key, c.lr), ("chat_accused", 1.5))
        self.say(a, carol, "xX_Sniperwolf_Xx hileci")
        [c] = live_clues.accusation_clues(a, accused)
        self.assertEqual(c.lr, 2.5)
        self.assertIn("3 different", c.text)

    def test_you_and_the_accused_dont_count(self):
        a, accused, (alice, *_rest) = self.setup()
        self.say(a, a.players[ME], "sniperwolf cheater")
        self.say(a, accused, "everyone says sniperwolf is a bot lol")
        self.say(a, alice, "sniperwolf hacker")
        self.assertEqual(live_clues.accusation_clues(a, accused), [])

    def test_needs_both_a_word_and_the_name(self):
        a, accused, (alice, bob, carol, dave) = self.setup()
        self.say(a, alice, "sniperwolf is good")
        self.say(a, bob, "this server has cheaters")
        self.say(a, carol, "the hacker again")  # "the" is an everyday word, not a part of a name
        self.say(a, dave, "bob is a bot")      # someone else
        self.assertEqual(live_clues.accusation_clues(a, accused), [])

    def test_shared_name_part_is_ambiguous(self):
        a, accused, (alice, bob, *_rest) = self.setup()
        a.add(70, "wolfgang")
        self.say(a, alice, "wolf hacks")
        self.say(a, bob, "wolf cheater")
        self.assertEqual(live_clues.accusation_clues(a, accused), [])


class BotTest(unittest.TestCase):
    def test_nothing_bot_like_no_clue(self):
        a = FakeApp()
        p = a.add(50, "Normal")
        a.match_chat += [(NOW, p.sid, p.name, "gg"), (NOW, p.sid, p.name, "gg"), (NOW, p.sid, p.name, "gg"),
                         (NOW, p.sid, p.name, "nice shot mate")]
        self.assertEqual(live_clues.bot_clues(a, p), [])

    def test_spam_link_and_name_changes_combined_and_capped(self):
        a = FakeApp()
        p = a.add(50, "Bot")
        for _ in range(3):
            a.match_chat.append((NOW, p.sid, p.name, "join my server for free items"))
        [c] = live_clues.bot_clues(a, p)
        self.assertEqual((c.key, c.lr), ("bot_behaviour", 2.0))
        a.match_chat.append((NOW, p.sid, p.name, "discord.gg/abcdef"))
        a.name_changes[p.sid] = ["a", "b", "c"]
        [c] = live_clues.bot_clues(a, p)
        self.assertEqual(c.lr, live_clues.BOT_MAX_LR)
        self.assertIn("posted a link", c.text)
        self.assertIn("changed name 3 times", c.text)

    def test_one_name_change(self):
        a = FakeApp()
        p = a.add(50, "Renamed")
        a.name_changes[p.sid] = ["Old"]
        [c] = live_clues.bot_clues(a, p)
        self.assertEqual(c.lr, 1.5)
        a.flags = {p.sid: [(2, "copied someone's name (Renamed)")]}  # cheat_score's bot_name covers it
        self.assertEqual(live_clues.bot_clues(a, p), [])

    def test_new_accounts_joined_together(self):
        a = FakeApp()
        p = a.add(50, "Fresh1", joined=NOW - 600)
        q = a.add(51, "Fresh2", joined=NOW - 598)
        a.add(52, "Elsewhere", joined=NOW - 100)
        for x in (p, q):
            x.summary = {"timecreated": time.time() - 5 * 86400}
        [c] = live_clues.bot_clues(a, p)
        # only what the group adds: the young age itself is cheat_score's experience clue
        self.assertEqual(live_clues.LR_NEW_GROUP, 1.5)
        self.assertEqual(c.lr, 1.5)
        self.assertIn("joined together", c.text)
        q.summary = {"timecreated": time.time() - 900 * 86400}  # the friend's account is old
        self.assertEqual(live_clues.bot_clues(a, p), [])


class HooksTest(unittest.TestCase):
    """The App collects chat, renames, spawns and kill times live, and forgets them per match."""

    def test_hooks_collect_and_new_match_clears(self):
        def g15(slot, n, alive):
            return [f"m_iAccountID[{slot}] integer ({n})", f"m_bConnected[{slot}] bool (true)",
                    f"m_iTeam[{slot}] integer (2)", f"m_bAlive[{slot}] bool ({'true' if alive else 'false'})"]

        def script(g):
            a = g.app
            feed = lambda lines: g.on_screen_thread(lambda: [a.handle_line(l) for l in lines])
            feed(["Hank :  dan is an aimbot"])
            feed(['#     3 "dan2"   [U:1:3]   10:05  50  0 active'])  # dan renamed
            feed(g15(1, 3, False) + [G15_DONE])
            feed(g15(1, 3, True) + [G15_DONE])  # dead -> alive: a spawn
            feed(["Hank killed dan2 with sniperrifle."])
            self.assertEqual(a.match_chat[0][1:], (HANK, "Hank", "dan is an aimbot"))
            self.assertEqual(a.name_changes, {DAN: ["dan"]})
            self.assertEqual(len(a.spawn_times[DAN]), 1)
            self.assertEqual([k[1:] for k in a.kill_times], [(HANK, DAN, "sniperrifle")])
            self.assertEqual(live_clues.spawn_kills(a, HANK), (1, 1, 1))
            [c] = live_clues.bot_clues(a, a.players[DAN])
            self.assertIn("changed name 1 time", c.text)
            feed(["Client reached server_spawn"])
            self.assertEqual((a.match_chat, a.name_changes, a.spawn_times, a.kill_times), ([], {}, {}, []))
            feed(["Hank :  hello", "Disconnect: left"])
            self.assertEqual(a.match_chat, [])
        Game().play(script)


if __name__ == "__main__":
    unittest.main()
