"""!stats, !mystats and !roast (info_commands.py), with made-up players and made-up Steam stats:
no real network (the Steam lookup is replaced), no real files."""
import time
import unittest
from collections import Counter

from helpers import Game
import info_commands
import lookups
from info_commands import big, mystats_lines

FAKE_STATS = {("Scout", "accum", "iplaytime"): 3_600_000, ("Soldier", "accum", "iplaytime"): 1_800_000,
              ("Scout", "accum", "inumberofkills"): 150_000, ("Soldier", "accum", "inumberofkills"): 32_000,
              ("Scout", "accum", "idominations"): 9_000,
              ("Soldier", "max", "inumberofkills"): 23, ("Heavy", "max", "idamagedealt"): 4812,
              ("Spy", "max", "ibackstabs"): 9}


def wait_for(g, test, seconds=20):
    deadline = time.time() + seconds
    while time.time() < deadline and not test():
        time.sleep(0.2)


class FunCommandsTest(unittest.TestCase):
    def test_big_numbers_are_short(self):
        self.assertEqual([big(n) for n in (950, 4812, 182_000, 1_250_000)], ["950", "4.8k", "182k", "1.2M"])

    def test_mystats_is_two_short_lines(self):
        lines = mystats_lines("Hank", FAKE_STATS)
        self.assertEqual(lines, ["Hank | 1,500 h, 182k kills, 9k dominations, mains Scout (67%)",
                                 "Hank | best life: 23 kills (Soldier), 4.8k dmg (Heavy), 9 stabs"])
        for line in mystats_lines("x" * 40, {**FAKE_STATS, **{(c, "max", "ipointsscored"): 99 for c in lookups.TF2_CLASSES}}):
            self.assertLessEqual(len(line.encode()), info_commands.CHAT_LIMIT)
        self.assertEqual(mystats_lines("Hank", {}), ["[MYSTATS] Hank | Steam has no TF2 stats for them"])

    def test_steam_stats_are_read_per_class_without_mvm(self):
        answer = {"playerstats": {"stats": [{"name": "Scout.accum.iNumberOfKills", "value": 5},
                                            {"name": "Scout.mvm.accum.iNumberOfKills", "value": 99},
                                            {"name": "Spy.max.iBackstabs", "value": 3}]}}
        real = lookups.steam_get
        lookups.steam_get = lambda *a, **k: answer
        try:
            self.assertEqual(lookups.tf2_stats("key", 1), {("Scout", "accum", "inumberofkills"): 5,
                                                            ("Spy", "max", "ibackstabs"): 3})
        finally:
            lookups.steam_get = real

    def test_mystats_answers_whoever_typed_it(self):
        def script(g):
            a = g.app
            a.cfg["steam_api_key"] = "made-up"
            asked = []

            def fake_lookup(key, sid, say, events):
                asked.append(sid)
                events.put(("mystats", sid, say, FAKE_STATS if len(asked) == 1 else "private"))
            info_commands.tf2_stats_lookup, real = fake_lookup, info_commands.tf2_stats_lookup
            try:
                g.say("Hank", "!mystats")
                wait_for(g, lambda: any("best life" in line for line in g.said()))
                self.assertIn("Hank | best life: 23 kills (Soldier), 4.8k dmg (Heavy), 9 stabs", g.said())
                self.assertEqual(asked, [a.sid_by_name("Hank")])
                g.say("Hank", "!mystats")  # again right away: no cooldown (kept 10 minutes: no new lookup)
                wait_for(g, lambda: g.said().count("Hank | best life: 23 kills (Soldier), 4.8k dmg (Heavy), 9 stabs") == 2)
                self.assertEqual(g.said().count("Hank | best life: 23 kills (Soldier), 4.8k dmg (Heavy), 9 stabs"), 2)
                self.assertEqual(asked, [a.sid_by_name("Hank")])
                g.say("dan", "!mystats")
                wait_for(g, lambda: any("private" in line for line in g.said()))
                self.assertIn("[MYSTATS] dan | TF2 stats are private (Steam profile: Game details)", g.said())
                g.say("dan", "!mystats toma")  # somebody else's, by part of their name
                wait_for(g, lambda: any(line.startswith("[MYSTATS] tomato") for line in g.said()))
                self.assertEqual(asked[-1], a.sid_by_name("tomato"))
                self.assertIn("[MYSTATS] tomato | TF2 stats are private (Steam profile: Game details)", g.said())
                g.say("dan", "!mystats zzz")
                wait_for(g, lambda: "[MYSTATS] nobody here is called 'zzz'" in g.said())
                self.assertIn("[MYSTATS] nobody here is called 'zzz'", g.said())
            finally:
                info_commands.tf2_stats_lookup = real
        Game().play(script)

    def test_stats_counts_backstabs_and_headshots_from_the_feed(self):
        def script(g):
            a = g.app
            for line in ("Hank killed dan with knife. (crit)", "Hank killed dan with sniperrifle. (crit)",
                         "Hank killed dan with sniperrifle."):
                g.on_screen_thread(lambda line=line: a.handle_line(line))
            dan = a.sid_by_name("dan")
            self.assertEqual(a.stab_kills[a.sid_by_name("Hank")], 1)
            self.assertEqual(a.death_kinds[dan], Counter(backstab=1, headshot=1))
            self.assertIn("1 headshot, 1 backstab", a.stats_line())
            g.on_screen_thread(lambda: a.handle_line("Client reached server_spawn."))  # a new map: gone
            self.assertEqual((dict(a.stab_kills), a.death_kinds), ({}, {}))
        Game().play(script)

    def test_roast_uses_the_real_match(self):
        def script(g):
            a = g.app
            a.reevaluate = lambda: None
            me, hank, dan = (a.sid_by_name(n) for n in ("tomato", "Hank", "dan"))
            a.board = {dan: {"m_iTeam": "2", "m_iScore": "0", "m_iDeaths": "9"},
                       hank: {"m_iTeam": "3", "m_iScore": "15", "m_iDeaths": "2"},
                       me: {"m_iTeam": "2", "m_iScore": "4", "m_iDeaths": "5"}}
            a.pair_kills[(hank, dan)] = 6
            a.classes[dan] = "Spy"
            roasts = a.roasts(a.players[dan])
            self.assertIn("Hank 6 dan 0. dan is a free daily for Hank", roasts)
            self.assertIn("dan 0 kills. playing on peaceful mode", roasts)
            self.assertIn("dan is 0-9. dogwater. absolute dogwater. uninstall.", roasts)
            self.assertIn("dan, spy with 0 stabs. bro's a 125hp tourist", roasts)
            self.assertFalse(any("cheat scan" in line for line in roasts))
            self.assertIn(a.roasts(a.players[hank])[0], ("Hank 15-2 in casual. bro tryharding like there's prize money",))
            self.assertEqual(a.roasts(a.players[me]), ["tomato 4-5. aggressively mid", "tomato 4-5. background npc, no dialogue"])
            # The rotation: random among everything that fits, never one of the last 6 again.
            said = [a.roast_line(a.players[dan]) for _ in range(len(roasts))]
            self.assertEqual(len(set(said[:6])), 6, said)
            seen = {a.roast_line(a.players[dan]) for _ in range(6)}
            self.assertGreater(len(seen), 1)  # not the same line every time
            for line in seen:
                self.assertLessEqual(len(line.encode()), info_commands.CHAT_LIMIT)

            g.say("Hank", "!roast da")
            wait_for(g, lambda: any(line.startswith("[ROAST] ") for line in g.said()))
            self.assertTrue(any("dan" in line for line in g.said() if line.startswith("[ROAST] ")))
            g.say("dan", "!roast me")
            wait_for(g, lambda: len([line for line in g.said() if line.startswith("[ROAST] ")]) >= 2)
            g.say("dan", "!roast me")  # right away again: no cooldown
            wait_for(g, lambda: len([line for line in g.said() if line.startswith("[ROAST] ")]) >= 3)
            self.assertGreaterEqual(len([line for line in g.said() if line.startswith("[ROAST] ")]), 3)
        Game().play(script)


if __name__ == "__main__":
    unittest.main()
