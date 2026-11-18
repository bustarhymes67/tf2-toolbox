"""Reading TF2's output. The map line is copied from a real console.log."""
import unittest

import helpers  # noqa: F401  (sets up the import path)
from game_log import KILL_RE, MAP_RE, STATUS_RE, to_steam64


class GameLogTest(unittest.TestCase):
    def test_map_from_status_and_from_loading(self):
        self.assertEqual(MAP_RE.match("map     : ctf_2fort at: 0 x, 0 y, 0 z")[1], "ctf_2fort")
        self.assertEqual(MAP_RE.match("Map: pl_badwater")[1], "pl_badwater")

    def test_a_player_called_map_is_not_a_map(self):
        self.assertIsNone(MAP_RE.match("map :  hello there"))

    def test_kill_line(self):
        m = KILL_RE.match("Hank killed dan with tf_projectile_rocket. (crit)")
        self.assertEqual((m["killer"], m["victim"], m["weapon"], bool(m["crit"])),
                         ("Hank", "dan", "tf_projectile_rocket", True))

    def test_status_line(self):
        m = STATUS_RE.search('#     7 "dan"   [U:1:42]   10:00  50  0 active')
        self.assertEqual((m["userid"], m["name"]), ("7", "dan"))
        self.assertEqual(to_steam64(m["sid"]), 76561197960265728 + 42)


if __name__ == "__main__":
    unittest.main()
