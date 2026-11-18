"""The cheater score (cheat_score.py): rate tests that respect sample size, Bayes in log-odds, bands,
proof, clues that lower the odds, no double counting, and the Players page showing the breakdown."""
import json
import math
import os
import time
import unittest
from collections import Counter
from types import SimpleNamespace

from helpers import Game, ME
import cheat_score as cs
from game_log import STEAM64_BASE
from player_flags import Player
from settings import DEFAULTS
import web_players
import web_state

SID = STEAM64_BASE + 50


class FakeApp:
    """Just what the clue sources read."""

    def __init__(self, **kw):
        self.me, self.cfg = ME, dict(DEFAULTS)
        self.lists, self.marks, self.flags = {}, {}, {}
        self.kills, self.crits, self.weapons, self.demo = {}, {}, {}, Counter()
        self.__dict__.update(kw)

    def demo_checks_of(self, sid):
        return self.demo


def player(**kw):
    p = Player(SID, "[U:1:50]", 50, "someone", 0, 0)
    for k, v in kw.items():
        setattr(p, k, v)
    return p


class OwnSources(unittest.TestCase):
    """Only cheat_score's own clue sources (other modules register theirs too, which need a real App)."""

    def setUp(self):
        self.saved = list(cs.CLUE_SOURCES)
        cs.CLUE_SOURCES[:] = list(cs.BUILTIN_SOURCES)

    def tearDown(self):
        cs.CLUE_SOURCES[:] = self.saved


def keys(sc):
    return {c.key: c.lr for c in sc.clues}


class RateTests(OwnSources):
    def test_three_of_three_headshots_never_moves_the_odds(self):
        sc = cs.score(FakeApp(kills={SID: [3, 3]}), player())
        self.assertNotIn("hs_rate", keys(sc))
        self.assertAlmostEqual(sc.prob, cs.PRIOR)
        self.assertEqual(sc.band, "Clean")

    def test_nine_of_nine_is_still_below_the_minimum_sample(self):
        self.assertNotIn("hs_rate", keys(cs.score(FakeApp(kills={SID: [9, 9]}), player())))

    def test_twenty_four_of_twenty_six_headshots_does(self):
        sc = cs.score(FakeApp(kills={SID: [26, 24]}), player())
        clue = next(c for c in sc.clues if c.key == "hs_rate")
        self.assertEqual(clue.lr, 30.0)  # the cap
        self.assertIn("24/26", clue.text)
        self.assertIn("by luck", clue.why)
        self.assertGreater(sc.prob, 0.4)

    def test_a_normal_snipers_rate_moves_nothing(self):
        self.assertNotIn("hs_rate", keys(cs.score(FakeApp(kills={SID: [20, 11]}), player())))

    def test_tail_lr_curve(self):
        self.assertEqual(cs.tail_lr(0.2), 1.0)
        self.assertEqual(cs.tail_lr(0.05), 1.0)
        self.assertAlmostEqual(cs.tail_lr(0.01), 5.0)
        self.assertEqual(cs.tail_lr(1e-9), 30.0)
        # smooth: rarer luck never gives a smaller LR
        lrs = [cs.tail_lr(10 ** -x) for x in range(0, 10)]
        self.assertEqual(lrs, sorted(lrs))

    def test_bow_kills_use_the_bows_honest_rate(self):
        app = FakeApp(weapons={SID: Counter({"tf_projectile_arrow": 10})})
        self.assertAlmostEqual(cs.honest_hs_rate(app, player()), cs.HONEST_HS_BOW)
        app.weapons[SID]["sniperrifle"] = 10
        self.assertAlmostEqual(cs.honest_hs_rate(app, player()), (cs.HONEST_HS_BOW + cs.HONEST_HS_RIFLE) / 2)

    def test_random_crits(self):
        self.assertNotIn("crit_rate", keys(cs.score(FakeApp(crits={SID: [12, 3]}), player())))
        self.assertNotIn("crit_rate", keys(cs.score(FakeApp(crits={SID: [5, 5]}), player())))  # too few kills
        self.assertEqual(keys(cs.score(FakeApp(crits={SID: [12, 12]}), player()))["crit_rate"], 30.0)


class CombineTests(OwnSources):
    def test_log_odds_combination(self):
        prior_odds = cs.PRIOR / (1 - cs.PRIOR)
        p = cs.combine(cs.PRIOR, [40, 12, 0.5])
        self.assertAlmostEqual(p / (1 - p), prior_odds * 240)
        self.assertAlmostEqual(cs.combine(cs.PRIOR, []), cs.PRIOR)
        self.assertAlmostEqual(cs.combine(cs.PRIOR, [4, 0.25]), cs.PRIOR)  # cancel out
        self.assertAlmostEqual(cs.from_log_odds(cs.log_odds(0.8)), 0.8)
        self.assertGreater(cs.combine(cs.PRIOR, [1e6] * 10), 0.999)  # no overflow

    def test_bands(self):
        self.assertEqual(cs.band_of(0.03), "Clean")
        self.assertEqual(cs.band_of(0.10), "Watch")
        self.assertEqual(cs.band_of(0.349), "Watch")
        self.assertEqual(cs.band_of(0.35), "Suspicious")
        self.assertEqual(cs.band_of(0.70), "Likely")
        self.assertEqual(cs.band_of(0.05, proof=True), "Proven")

    def test_proof_only_from_strong_demo_checks(self):
        app = FakeApp(demo=Counter({"nocrex/oob_pitch": 3}))
        sc = cs.score(app, player())
        self.assertEqual(sc.band, "Proven")
        self.assertTrue(sc.proof)
        # Lots of weak checks: never Proven, and high ping shrinks them
        app = FakeApp(demo=Counter({"angle_history": 40}))
        sc = cs.score(app, player())
        self.assertNotEqual(sc.band, "Proven")
        self.assertEqual(keys(sc)["demo_weak"], cs.DEMO_WEAK_MAX)
        self.assertLess(keys(cs.score(app, player(ping=300)))["demo_weak"], 2.5)
        self.assertAlmostEqual(keys(cs.score(FakeApp(demo=Counter({"doubletap": 2})), player()))["demo_weak"], 2.0)

    def test_high_hours_and_an_old_account_lower_the_odds(self):
        old = time.time() - 9 * 365 * 86400
        sc = cs.score(FakeApp(), player(hours=1800, summary={"timecreated": old, "communityvisibilitystate": 3,
                                                             "profilestate": 1}))
        self.assertLess(keys(sc)["experience"], 1)
        self.assertLess(sc.prob, cs.PRIOR)
        new = cs.score(FakeApp(), player(hours=40, summary={"timecreated": time.time() - 10 * 86400,
                                                            "communityvisibilitystate": 3, "profilestate": 1}))
        self.assertGreater(keys(new)["experience"], 1)
        self.assertLessEqual(keys(new)["experience"], cs.EXPERIENCE_RANGE[1])  # one clue, not two multiplied freely

    def test_lists_are_one_clue_growing_with_the_number_of_lists(self):
        def lr(n):
            app = FakeApp(lists={SID: {"attributes": {"cheater"}, "sources": [f"list {i}" for i in range(n)]}})
            sc = cs.score(app, player())
            self.assertEqual([c.key for c in sc.clues], ["lists"])  # not one clue per list
            return sc.clues[0].lr
        self.assertLess(lr(1), lr(2))
        self.assertLess(lr(2), lr(3))
        self.assertEqual(lr(3), lr(6))
        racist = FakeApp(lists={SID: {"attributes": {"racist"}, "sources": ["a", "b"]}})
        self.assertEqual(cs.score(racist, player()).clues, [])

    def test_same_key_from_two_sources_counts_once(self):
        extra = cs.register(lambda app, p: [cs.Clue("lists", 2.0, "other source", "test")])
        try:
            app = FakeApp(lists={SID: {"attributes": {"cheater"}, "sources": ["a"]}})
            sc = cs.score(app, player())
            self.assertEqual([(c.key, c.lr) for c in sc.clues], [("lists", 2.0)])  # the later one wins
        finally:
            cs.CLUE_SOURCES.remove(extra)

    def test_a_broken_source_does_not_break_the_score(self):
        def broken(app, p):
            raise ValueError("on purpose (this is the test)")
        cs.register(broken)
        try:
            self.assertEqual(cs.score(FakeApp(marks={str(SID): {"reason": "cheater"}}), player()).band, "Likely")
        finally:
            cs.CLUE_SOURCES.remove(broken)

    def test_clues_sorted_by_impact_and_you_have_none(self):
        app = FakeApp(lists={SID: {"attributes": {"cheater"}, "sources": ["a", "b"]}}, kills={SID: [26, 24]},
                      flags={SID: [(2, "friends with flagged x")]})
        sc = cs.score(app, player())
        self.assertEqual([c.key for c in sc.clues], ["lists", "hs_rate", "friends"])
        self.assertEqual(cs.score(app, player(sid=ME)).clues, [])

    def test_cheaters_rule_includes_the_old_rule_and_likely(self):
        app = FakeApp(flags={SID: [(3, "Steam community banned")]})
        self.assertTrue(cs.is_cheater(app, player()))  # old rule, though the score is low
        app = FakeApp(lists={SID: {"attributes": {"cheater"}, "sources": ["a", "b", "c"]}})
        self.assertTrue(cs.is_cheater(app, player()))
        self.assertFalse(cs.is_cheater(FakeApp(), player()))

    def test_breakdown_words(self):
        app = FakeApp(lists={SID: {"attributes": {"cheater"}, "sources": ["a", "b"]}}, kills={SID: [26, 24]})
        b = cs.breakdown(cs.score(app, player()))
        self.assertEqual(b["start"], "Start: 3% of casual players cheat (odds 1 : 32)")
        self.assertEqual([r["lr"] for r in b["rows"]], ["×40", "×30"])
        self.assertEqual(b["band"], "Likely")
        self.assertEqual(b["words"], "LIKELY CHEATER")
        self.assertTrue(b["end"].startswith("= odds 37 : 1"))
        self.assertIn("LIKELY CHEATER", cs.explain(cs.score(app, player())))
        self.assertEqual(cs.lr_text(0.5), "×0.5")
        self.assertEqual(cs.lr_text(2.5), "×2.5")


class PolishTests(OwnSources):
    def extra(self, *clues):
        cs.register(lambda app, p: list(clues))  # tearDown puts the sources back

    def test_small_clues_are_one_line_and_still_multiply_to_the_result(self):
        self.extra(cs.Clue("lists_x", 20.0, "big", "w"), cs.Clue("a", 1.04, "tiny up", "w"),
                   cs.Clue("b", 0.9, "tiny down", "w"), cs.Clue("c", 1.1, "edge", "w"), cs.Clue("d", 0.5, "down", "w"))
        sc = cs.score(FakeApp(), player())
        b = cs.breakdown(sc)
        texts = [r["text"] for r in b["rows"]]
        self.assertEqual(texts[:2], ["big", "down"])
        self.assertEqual(texts[2], "+ 3 small clues (×0.9–×1.1 each)")
        self.assertNotIn("tiny up", texts)
        self.assertEqual(b["rows"][2]["lr"], cs.lr_text(1.04 * 0.9 * 1.1))
        self.assertIn("tiny up", b["rows"][2]["why"])
        product = 20.0 * 0.5 * 1.04 * 0.9 * 1.1
        self.assertAlmostEqual(sc.odds, cs.to_odds(cs.PRIOR) * product)
        # none small: no extra line; one small: "1 small clue"
        self.assertIsNone(cs.small_row([cs.Clue("x", 2.0, "t", "w")]))
        self.assertEqual(cs.small_row([cs.Clue("x", 1.05, "t", "w")])["text"], "+ 1 small clue (×0.9–×1.1 each)")
        self.assertIsNone(cs.small_row([cs.Clue("x", 1.05, "t", "w", proof=True)]))

    def test_why_flagged_keeps_flag_rows_but_no_tiny_score_rows(self):
        self.extra(cs.Clue("kill_rate", 1.04, "1.8 kills/min", "w"), cs.Clue("bot_behaviour", 1.05, "bot-like", "w"),
                   cs.Clue("hs_rate", 1.06, "24/26 Sniper headshots", "w"), cs.Clue("spawn_kills", 3.0, "spawn", "w"))
        app = FakeApp(flags={SID: [(2, "92% headshots")]})
        reasons = web_players.reasons_json(app, player(), cs.score(app, player()))
        texts = [r["text"] for r in reasons]
        self.assertEqual(texts[0], "92% headshots")  # the flag row stays, with its (small) multiplier
        self.assertEqual(reasons[0]["lr"], "×1.06")
        self.assertIn("spawn", texts)
        self.assertNotIn("1.8 kills/min", texts)
        self.assertNotIn("bot-like", texts)
        small = reasons[-1]
        self.assertEqual(small["text"], "+ 2 small clues (×0.9–×1.1 each)")
        self.assertEqual(small["lr"], cs.lr_text(1.04 * 1.05))

    def test_nocrex_weak_checks_and_demo_aim_clues_overlap(self):
        app = FakeApp(demo=Counter({"angle_history": 4}))  # demo_weak x3
        alone = keys(cs.score(app, player()))["demo_weak"]
        self.assertAlmostEqual(alone, 3.0)
        # aim group bigger (x2 x x4 = x8): the weak checks count as their square root
        self.extra(cs.Clue("demo_aim_lock", 2.0, "lock", "w", source="demo"),
                   cs.Clue("demo_fast_acquire", 4.0, "fast", "w", source="demo"))
        k = keys(cs.score(app, player()))
        self.assertAlmostEqual(k["demo_weak"], math.sqrt(3.0))
        self.assertEqual((k["demo_aim_lock"], k["demo_fast_acquire"]), (2.0, 4.0))
        self.assertIn("square root", next(c for c in cs.score(app, player()).clues if c.key == "demo_weak").why)

    def test_overlap_shrinks_the_smaller_group_only_when_both_are_up(self):
        clue = lambda key, lr: cs.Clue(key, lr, key, "w")
        out = {c.key: c.lr for c in cs.demo_overlap([clue("demo_weak", 6.0), clue("demo_aim_lock", 4.0)])}
        self.assertEqual(out["demo_weak"], 6.0)
        self.assertAlmostEqual(out["demo_aim_lock"], 2.0)
        # the "human aim" hint (x0.9) isn't a group that fires: nothing shrinks
        out = {c.key: c.lr for c in cs.demo_overlap([clue("demo_weak", 6.0), clue("demo_aim_lock", 0.9)])}
        self.assertEqual(out, {"demo_weak": 6.0, "demo_aim_lock": 0.9})
        out = {c.key: c.lr for c in cs.demo_overlap([clue("demo_fast_acquire", 5.0)])}
        self.assertEqual(out, {"demo_fast_acquire": 5.0})
        # proof clues are never shrunk
        proof = cs.Clue("demo_oob_pitch", 1000.0, "p", "w", proof=True)
        self.assertIn(proof, cs.demo_overlap([proof, clue("demo_weak", 2.0), clue("demo_aim_lock", 4.0)]))

    def test_players_page_gives_names_room_and_lets_flags_shrink(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, "web", "pages", "players.js"), encoding="utf-8") as f:
            js = f.read()
        with open(os.path.join(here, "web", "pages", "players.css"), encoding="utf-8") as f:
            css = f.read()
        self.assertIn("PLAYER_MIN = 190", js)
        self.assertIn("return `${band}${c.tag", js)  # the band chip before the stamp: it stays when narrow
        self.assertIn('c === "Flags" ? 0', js)  # FLAGS takes what is left
        self.assertIn('title="${esc(c.t)}"', js)  # the full name on hover
        self.assertIn(".pl-pw .pn{min-width:0;overflow:hidden;text-overflow:ellipsis", css)


class WebStateTests(unittest.TestCase):
    def test_players_page_has_the_band_and_the_breakdown(self):
        dan = STEAM64_BASE + 3

        def script(g):
            a = g.app

            def arrange():
                a.refresh_board = lambda: None
                a.reevaluate = lambda: None
                for sid, team in ((ME, 3), (STEAM64_BASE + 2, 3), (dan, 2)):
                    a.board[sid] = {"m_iTeam": str(team), "m_iHealth": "125", "m_iScore": "1", "m_iDeaths": "1",
                                    "m_bAlive": "true", "m_iAccountID": str(sid - STEAM64_BASE), "m_bConnected": "true"}
                a.lists = {dan: {"attributes": {"cheater"}, "sources": ["one", "two"]}}
                a.kills[dan] = [26, 24]
                a.flags[dan] = [(3, "on 2 lists (cheater)"), (2, "92% headshots (24/26 sniper kills)")]
                a.players[dan].hours = 1800
                a.select(dan)
            g.on_screen_thread(arrange)
            s = g.on_screen_thread(lambda: web_players.players_state(a))
            json.dumps(s)
            row = next(r for t in s["teams"] for r in t["rows"] if r.get("sid") == str(dan))
            self.assertEqual(row["score"]["band"], "Likely")
            self.assertEqual(row["score"]["short"], "LIKELY")
            rows_ = {r["key"]: r for r in row["score"]["rows"]}
            self.assertLessEqual({"lists", "hs_rate", "experience"}, set(rows_))
            self.assertTrue(rows_["lists"]["text"].startswith("on 2 cheater lists"))
            self.assertEqual(row["score"]["rows"][0]["key"], "lists")  # the biggest first
            me = next(r for t in s["teams"] for r in t["rows"] if r.get("sid") == str(ME))
            self.assertIsNone(me["score"])
            p = s["panel"]
            self.assertEqual(p["score"]["words"], "LIKELY CHEATER")
            lrs = {r["text"]: r["lr"] for r in p["reasons"]}
            self.assertEqual(lrs["on 2 lists (cheater)"], "×40")
            self.assertEqual(lrs["92% headshots (24/26 sniper kills)"], "×30")
            self.assertEqual(lrs["1,800 hours"], "×0.7")  # a clue no flag shows: added under the flags
            counts = {f["key"]: f["n"] for f in s["filters"]}
            self.assertEqual(counts["cheaters"], 1)
            # The Cheaters chip: the score alone (no red flag) is enough
            g.on_screen_thread(lambda: a.flags.__setitem__(dan, [(2, "on 2 lists (cheater)")]))
            g.on_screen_thread(lambda: a.set_filter("cheaters"))
            s = g.on_screen_thread(lambda: web_players.players_state(a))
            self.assertIn(str(dan), {r.get("sid") for t in s["teams"] for r in t["rows"]})
            # The Tk filter and the sidebar badge use the same rule, also with no flag at all
            g.on_screen_thread(lambda: a.flags.__setitem__(dan, []))
            self.assertTrue(g.on_screen_thread(lambda: a.matches_filter(a.players[dan], "cheaters")))
            self.assertFalse(g.on_screen_thread(lambda: a.matches_filter(a.players[STEAM64_BASE + 2], "cheaters")))
            self.assertEqual(g.on_screen_thread(lambda: web_state.header(a))["badges"]["Players"], 1)
            g.on_screen_thread(lambda: a.lists.clear())
            self.assertIsNone(g.on_screen_thread(lambda: web_state.header(a))["badges"]["Players"])
            self.assertFalse(g.on_screen_thread(lambda: a.matches_filter(a.players[dan], "cheaters")))
        Game().play(script)


if __name__ == "__main__":
    unittest.main()
