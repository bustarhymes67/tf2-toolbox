"""Explaining why a player is flagged, and how sure that is."""
import unittest

import helpers  # noqa: F401  (sets up the import path)
from player_flags import explain_flags, flag_why


class FlagWhyTest(unittest.TestCase):
    def level(self, text, severity=2):
        return flag_why(severity, text)[0]

    def test_levels(self):
        for text, level in (
            ("marked by you as cheater", "yours"),
            ("on 3 lists (cheater)", "strong"),
            ("on joekiller's list (cheater)", "medium"),
            ("on rgl list (racist)", "info"),
            ("on SteamRep list (suspicious)", "weak"),
            ("copied someone's name (bot)", "strong"),
            ("1 VAC ban (200d ago)", "proven"),
            ("1 game ban (20d ago)", "proven"),
            ("1 VAC ban + 1 game ban (5d ago)", "proven"),
            ("Steam community banned", "weak"),
            ("trade banned", "info"),
            ("2 server bans: Aimbot (Skial)", "medium"),
            ("1 server ban: mic spam (Skial)", "weak"),
            ("1 server ban", "weak"),
            ("70% crit kills (14/20), possible crit hack", "strong"),
            ("45 headshots in one life (Sniper record)", "medium"),
            ("90% headshots (18/20 sniper kills)", "medium"),
            ("secondhand cheater (friends with x)", "weak"),
            ("friends with flagged x", "weak"),
            ("friends with 2 known cheaters", "weak"),
            ("new account", "weak"),
            ("profile never set up", "weak"),
            ("Steam level 0", "weak"),
            ("likely limited account (level 0, no friends)", "weak"),
            ("only 12h in TF2", "weak"),
            ("3 profile comments say cheat", "weak"),
            ("bio says hack", "weak"),
        ):
            self.assertEqual(self.level(text), level, text)

    def test_every_known_flag_has_a_reason(self):
        for text in ("1 VAC ban (2d ago)", "new account", "on 2 lists (cheater)"):
            self.assertTrue(flag_why(2, text)[1], text)

    def test_severity_0_is_only_information(self):
        self.assertEqual(self.level("40% headshots (2/5 sniper kills)", 0), "info")
        self.assertEqual(self.level("private profile", 0), "info")

    def test_explain_lists_every_flag(self):
        text = explain_flags([(3, "1 VAC ban (2d ago)"), (1, "new account")])
        self.assertIn("[proven] 1 VAC ban (2d ago): ", text)
        self.assertIn("[weak] new account: ", text)

    def test_no_flags_no_text(self):
        self.assertEqual(explain_flags([]), "")


if __name__ == "__main__":
    unittest.main()
