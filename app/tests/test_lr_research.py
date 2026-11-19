"""The cheater score's researched likelihood ratios (LR_RESEARCH, 2026-11-19): the prior setting, the
smooth account curves and their group damping, list families and fading, bans, friends by share,
profile words against chat accusations."""
import math
import time
import unittest
from collections import Counter

from helpers import ME
import cheat_score as cs
from game_log import STEAM64_BASE
from player_flags import Player
from settings import DEFAULTS

SID = STEAM64_BASE + 70
NOW = 1_800_000_000  # a fixed "now" (2027) so the ages don't drift
YEAR = 365.25 * 86400


class FakeApp:
    def __init__(self, **kw):
        self.me, self.cfg = ME, dict(DEFAULTS)
        self.lists, self.marks, self.flags, self.players = {}, {}, {}, {}
        self.kills, self.crits, self.weapons = {}, {}, {}
        self.cheater_ids = set()
        self.__dict__.update(kw)

    def demo_checks_of(self, sid):
        return Counter()


def player(**kw):
    p = Player(SID, "[U:1:70]", 70, "someone", 0, 0)
    for k, v in kw.items():
        setattr(p, k, v)
    return p


class OwnSources(unittest.TestCase):
    def setUp(self):
        self.saved = list(cs.CLUE_SOURCES)
        cs.CLUE_SOURCES[:] = list(cs.BUILTIN_SOURCES)

    def tearDown(self):
        cs.CLUE_SOURCES[:] = self.saved


class PriorTests(OwnSources):
    def test_the_prior_is_a_setting(self):
        self.assertEqual(DEFAULTS["cheat_prior"], 0.02)
        self.assertEqual(cs.PRIOR, 0.02)
        self.assertAlmostEqual(cs.score(FakeApp(), player()).prob, 0.02)
        app = FakeApp()
        app.cfg["cheat_prior"] = 0.04
        sc = cs.score(app, player())
        self.assertAlmostEqual(sc.prob, 0.04)
        self.assertTrue(cs.breakdown(sc)["start"].startswith("Start: 4% of casual players cheat"))
        for bad in ("lots", None, -1, float("nan")):
            app.cfg["cheat_prior"] = bad
            self.assertTrue(cs.PRIOR_RANGE[0] <= cs.prior_of(app) <= cs.PRIOR_RANGE[1], bad)


class AccountTests(OwnSources):
    def test_age_curve_is_smooth_monotonic_and_clamped(self):
        # LR_RESEARCH s4: 90 d x5.3, 180 d x3.1, 1 y x1.7, 2 y x1, 5 y x0.48, 10 y x0.28, 13 y+ x0.25
        for days, want in ((90, 5.3), (180, 3.1), (365, 1.7), (730, 1.0), (1825, 0.48), (3650, 0.28)):
            self.assertAlmostEqual(cs.age_lr(days), want, delta=0.05, msg=days)
        self.assertEqual(cs.age_lr(7), 6.0)
        self.assertEqual(cs.age_lr(0), 6.0)
        self.assertEqual(cs.age_lr(20 * 365), 0.25)
        ages = [cs.age_lr(d) for d in range(0, 8000, 7)]
        self.assertEqual(ages, sorted(ages, reverse=True))  # older never raises the odds

    def test_hours_curve(self):
        # LR_RESEARCH s5: 0 h x3.5, 10 h x3.1, 100 h x1.7, 500 h x1, 1,000 h x0.79, 3,000 h x0.54, 10,000 h x0.5
        for hours, want in ((0, 3.5), (10, 3.1), (100, 1.7), (500, 1.0), (1000, 0.79), (3000, 0.54), (10000, 0.5)):
            self.assertAlmostEqual(cs.hours_lr(hours), want, delta=0.03, msg=hours)
        lrs = [cs.hours_lr(h) for h in range(0, 12000, 50)]
        self.assertEqual(lrs, sorted(lrs, reverse=True))

    def test_group_damping(self):
        # LR_RESEARCH s7: 6 * 2.9**0.5 * 2**0.25 = x12 -> x8 (cap); 0.30 * 0.49**0.5 = x0.21
        self.assertEqual(cs.account_lr([6.0, 2.9, 2.0]), 8.0)
        self.assertAlmostEqual(cs.account_lr([0.30, 0.49]), 0.30 * 0.49 ** 0.5, places=6)
        self.assertAlmostEqual(cs.account_lr([2.0, 4.0]), 4.0 * 2.0 ** 0.5)  # the biggest in full, whatever the order
        self.assertAlmostEqual(cs.account_lr([4.0, 2.0, 2.0, 2.0]), 4.0 * 2 ** 0.5 * 2 ** 0.25 * 2 ** 0.125)
        self.assertAlmostEqual(cs.account_lr([3.0, 0.5]), 1.5)  # opposite directions both count in full
        self.assertEqual(cs.account_lr([0.1, 0.1, 0.1]), 0.2)  # the floor
        self.assertEqual(cs.account_lr([]), 1.0)
        self.assertEqual(cs.account_lr([1.0, 1.0]), 1.0)

    def test_one_account_clue_lists_its_parts(self):
        p = player(hours=4000, level=30, friends={1, 2},
                   summary={"timecreated": NOW - 9 * YEAR, "communityvisibilitystate": 3, "profilestate": 1})
        clue, = cs.account_clues(FakeApp(), p, now=NOW)
        self.assertEqual(clue.key, "account")
        self.assertAlmostEqual(clue.lr, cs.account_lr([cs.age_lr(9 * 365.25), cs.hours_lr(4000)]))
        self.assertLess(clue.lr, 0.25)
        self.assertEqual(clue.text, f"9-year-old account {cs.lr_text(cs.age_lr(9 * 365.25))}; "
                                    f"4,000 hours {cs.lr_text(cs.hours_lr(4000))}")
        self.assertIn("half strength", clue.why)
        # a 3-week-old limited account with 15 hours: up, capped at x8
        p = player(hours=15, level=0, friends=set(),
                   summary={"timecreated": NOW - 21 * 86400, "communityvisibilitystate": 3, "profilestate": 1})
        clue, = cs.account_clues(FakeApp(), p, now=NOW)
        self.assertEqual(clue.lr, 8.0)
        self.assertTrue(clue.text.startswith("21-day-old account ×6"))
        self.assertIn("limited account", clue.text)

    def test_hidden_hours_and_profile_values(self):
        p = player(hours=None, summary={"timecreated": NOW - 2 * 365 * 86400, "communityvisibilitystate": 1})
        clue, = cs.account_clues(FakeApp(), p, now=NOW)  # 2 years (x1) and private (x1.1): hours hidden = x1
        self.assertNotIn("hours", clue.text)
        self.assertAlmostEqual(clue.lr, 1.1, places=2)
        self.assertEqual(cs.PROFILE_LR, {"private": 1.1, "never set up": 1.8, "limited": 2.0, "level 0": 1.5})
        self.assertEqual(cs.account_clues(FakeApp(), player(hours=500), now=NOW), [])  # x1: nothing to show

    def test_account_flags_point_at_the_account_clue(self):
        app = FakeApp(flags={SID: [(1, "new account"), (1, "only 40h in TF2"), (0, "private profile")]})
        p = player(hours=40, summary={"timecreated": time.time() - 30 * 86400, "communityvisibilitystate": 1})
        sc = cs.score(app, p)
        for _, text in app.flags[SID]:
            self.assertEqual(cs.flag_clue(text, sc.clues).key, "account", text)
        self.assertEqual([c.key for c in sc.clues], ["account"])


class ListTests(OwnSources):
    URLS = {"TF2BD official": "https://raw.githubusercontent.com/PazerOP/tf2_bot_detector/master/x.json",
            "@Trusted": "https://trusted.roto.lol/v1/steamids",
            "Milenko's": "https://raw.githubusercontent.com/incontestableness/milenko-lists/master/x.json",
            "joekiller's": "https://raw.githubusercontent.com/joekiller/joekiller-list/main/x.json",
            "qfoxb's": "https://raw.githubusercontent.com/qfoxb/tf2bd-lists/main/x.json",
            "SteamRep scammer": "https://raw.githubusercontent.com/Newport1/Tf2BD_My_lists/main/playerlist.steamrep.json"}

    def listed(self, *names, attrs=("cheater",), seen=None):
        by = {n: {"urls": [self.URLS[n]], "attributes": set(attrs if n != "SteamRep scammer" else ("suspicious",)),
                  "time": seen or 0} for n in names}
        all_attrs = set().union(*(b["attributes"] for b in by.values()))
        return FakeApp(lists={SID: {"attributes": all_attrs, "sources": list(names), "by_source": by}})

    def lr(self, *names, **kw):
        clue, = cs.list_clues(self.listed(*names, **kw), player(), now=NOW)
        return clue

    def test_families(self):
        self.assertEqual(cs.list_family(self.URLS["TF2BD official"]), "pazer")
        self.assertEqual(cs.list_family("https://raw.githubusercontent.com/SisterHailey/tf2bd2/main/x.json"), "pazer")
        self.assertEqual(cs.list_family("@Trusted"), "roto")
        self.assertEqual(cs.list_family("Some new list"), "some new list")  # a list we don't know: its own family
        self.assertEqual(cs.independent_lists({"roto"}), 1)
        self.assertEqual(cs.independent_lists({"roto", "pazer"}), 1)  # the aggregator copied the official list
        self.assertEqual(cs.independent_lists({"roto", "milenko"}), 1)
        self.assertEqual(cs.independent_lists({"pazer", "joekiller", "roto"}), 2)
        self.assertEqual(cs.independent_lists(set()), 0)

    def test_lists_count_independent_families(self):
        self.assertEqual(self.lr("TF2BD official").lr, 30.0)
        one = self.lr("TF2BD official", "@Trusted", "Milenko's")  # three files, one judgement
        self.assertEqual(one.lr, 30.0)
        self.assertTrue(one.text.startswith("on 3 cheater lists"))
        self.assertIn("count as 1 independent list", one.why)
        self.assertEqual(self.lr("TF2BD official", "joekiller's").lr, 100.0)
        self.assertEqual(self.lr("TF2BD official", "joekiller's", "qfoxb's", "@Trusted").lr, 200.0)
        # a SteamRep "suspicious" entry next to a cheater list isn't a second cheater list
        self.assertEqual(self.lr("TF2BD official", "SteamRep scammer").lr, 30.0)

    def test_suspicious_only_is_weak(self):
        clue = self.lr("SteamRep scammer")
        self.assertEqual(clue.lr, 1.3)
        self.assertIn("as suspicious", clue.text)

    def test_entries_fade_with_a_three_year_half_life(self):
        fresh = self.lr("TF2BD official", seen=NOW - 10 * 86400).lr
        three = self.lr("TF2BD official", seen=NOW - 3 * YEAR)
        six = self.lr("TF2BD official", seen=NOW - 6 * YEAR).lr
        self.assertAlmostEqual(fresh, 30.0, delta=0.3)
        self.assertAlmostEqual(three.lr, 1 + 29 * 0.5, places=3)
        self.assertAlmostEqual(six, 1 + 29 * 0.25, places=3)
        self.assertIn("3 years ago", three.why)
        self.assertEqual(self.lr("Milenko's").lr, 30.0)  # no date on the list: no fading
        self.assertAlmostEqual(cs.fade(30, 5.3, 3), 9.52, places=2)  # the report's "2021 entry in 2026: ~x10"

    def test_old_list_data_without_per_list_details_still_works(self):
        app = FakeApp(lists={SID: {"attributes": {"cheater"}, "sources": ["TF2BD official", "joekiller's"]}})
        self.assertEqual(cs.score(app, player()).clues[0].lr, 100.0)


class BanTests(OwnSources):
    def test_ban_curve(self):
        # LR_RESEARCH s3: 0 d x8, 1 y x5.2, 3 y x2.6, 6 y x1.5 (floor)
        for days, want in ((0, 8.0), (365, 5.25), (3 * 365, 2.56), (6 * 365, 1.5), (20 * 365, 1.5)):
            self.assertAlmostEqual(cs.ban_lr(days), want, delta=0.02, msg=days)
        self.assertAlmostEqual(cs.ban_lr(3 * 365, 2), cs.ban_lr(3 * 365) * 1.25)
        self.assertEqual(cs.ban_lr(0, 2), 10.0)
        self.assertEqual(cs.ban_lr(0, 3), 12.0)  # the cap
        lrs = [cs.ban_lr(d) for d in range(0, 5000, 30)]
        self.assertEqual(lrs, sorted(lrs, reverse=True))

    def test_ban_clue_and_community_ban(self):
        p = player(bans={"NumberOfVACBans": 1, "NumberOfGameBans": 0, "DaysSinceLastBan": 400, "CommunityBanned": True})
        k = {c.key: c for c in cs.ban_clues(FakeApp(), p)}
        self.assertAlmostEqual(k["bans"].lr, cs.ban_lr(400))
        self.assertEqual(k["bans"].text, "1 VAC ban, last 1 year ago")
        self.assertEqual(k["community_ban"].lr, 1.3)

    def test_a_cheat_ban_on_a_server_is_proof_at_any_age(self):
        same = [{"Server": "Skial #1", "Reason": "aimbot"}, {"Server": "Skial #4", "Reason": "cheating"}]
        clue, = cs.ban_clues(FakeApp(), player(sourcebans=same))
        self.assertTrue(clue.proof)
        self.assertEqual(clue.lr, 1000.0)
        self.assertTrue(clue.text.startswith("banned for cheating by 1 server community"))
        for reason in ("wallhack", "ESP", "triggerbot", "hacking"):
            old = [{"Server": "Skial", "Reason": reason, "BanTimestamp": str(int(NOW - 8 * YEAR))}]
            clue, = cs.ban_clues(FakeApp(), player(sourcebans=old), now=NOW)
            self.assertTrue(clue.proof, reason)  # 8 years old: still proof
            self.assertEqual(cs.band_of(0.01, clue.proof), "Proven")
        other, = cs.ban_clues(FakeApp(), player(sourcebans=[{"Server": "x", "Reason": "mic spam"}]))
        self.assertEqual(other.lr, 1.1)
        self.assertFalse(other.proof)


class FriendTests(OwnSources):
    def test_friends_by_share(self):
        self.assertEqual(cs.friends_lr(0, 100), 1.0)
        self.assertEqual(cs.friends_lr(1, 100), 1.8)
        self.assertEqual(cs.friends_lr(10, 100), 3.0)
        self.assertEqual(cs.friends_lr(5, 10), 6.0)
        self.assertEqual(cs.friends_lr(3, None), 1.8)  # hidden friend list: only "any"

    def test_friend_clue_counts_flagged_friends(self):
        cheats = {STEAM64_BASE + 900 + i for i in range(3)}
        friends = cheats | {STEAM64_BASE + 1000 + i for i in range(17)}  # 3 of 20 = 15%
        app = FakeApp(cheater_ids=cheats, flags={SID: [(2, "friends with 3 known cheaters: a, b…")]})
        clue, = cs.friend_clues(app, player(friends=friends))
        self.assertEqual(clue.lr, 3.0)
        self.assertIn("(3 of 20 friends)", clue.text)
        app.flags[SID] = [(2, "friends with flagged x")]  # friend list unknown
        clue, = cs.friend_clues(FakeApp(flags=app.flags), player())
        self.assertEqual(clue.lr, 1.8)


class WordsTests(OwnSources):
    def test_profile_words_capped_at_three(self):
        pr = {"comment_hits": 5, "comment_words": ["cheat"], "bio_words": ["hack"]}
        clue, = cs.profile_word_clues(FakeApp(), player(profile=pr))
        self.assertEqual(clue.lr, 2.0 * 1.3)
        self.assertLessEqual(clue.lr, cs.WORDS_MAX)
        one, = cs.profile_word_clues(FakeApp(), player(profile={"comment_hits": 1, "comment_words": ["cheat"],
                                                                 "bio_words": []}))
        self.assertEqual(one.lr, 1.3)

    def test_profile_words_and_chat_accusations_overlap(self):
        cs.register(lambda app, p: [cs.Clue("chat_accused", 2.5, "called a cheater in chat by 3 different players", "w")])
        pr = {"comment_hits": 2, "comment_words": ["cheat"], "bio_words": []}
        k = {c.key: c for c in cs.score(FakeApp(), player(profile=pr)).clues}
        self.assertEqual(k["chat_accused"].lr, 2.5)
        self.assertAlmostEqual(k["profile_words"].lr, math.sqrt(1.5))
        self.assertIn("half strength", k["profile_words"].why)


class KeptTests(OwnSources):
    def test_kept_values(self):
        self.assertEqual((cs.BOT_NAME_LR, cs.MARK_LR, cs.DEMO_PROOF_LR), (30.0, 150.0, 1000.0))
        import live_clues
        self.assertEqual(live_clues.ACCUSE_LR, {2: 1.5, 3: 2.5})
        self.assertEqual(live_clues.KILL_RATE_MAX_LR, 5.0)
        self.assertFalse(hasattr(cs, "tail_lr"))  # the old 1/(20 p) rule is gone

    def test_bow_uses_a_lower_honest_rate(self):
        self.assertAlmostEqual(cs.HONEST_HS_BOW, 0.60)
        app = FakeApp(weapons={SID: Counter({"tf_projectile_arrow": 12})}, kills={SID: [12, 10]})
        bow = {c.key: c.lr for c in cs.score(app, player()).clues}["hs_rate"]
        self.assertGreater(bow, cs.hs_lr(10, 12))  # 10/12 says more with a bow than with a rifle


if __name__ == "__main__":
    unittest.main()
