"""The mini HUD over the game (hud.py), in a real App kept off-screen."""
import unittest

from helpers import Game
import hud


class HudTest(unittest.TestCase):
    def test_lineup_medic_and_spies(self):
        def script(g):
            a = g.app
            me, hank, dan = (a.sid_by_name(n) for n in ("tomato", "Hank", "dan"))
            a.reevaluate = lambda: None  # keeps the scoreboard set here
            a.board = {me: {"m_iTeam": "2", "m_bAlive": "true"}, dan: {"m_iTeam": "3", "m_bAlive": "true"},
                       hank: {"m_iTeam": "3", "m_bAlive": "true"}}
            a.classes.update({dan: "Medic", hank: "Spy"})

            def text():
                return "".join(t for t, _ in g.on_screen_thread(a.hud_parts))
            first = text()
            self.assertTrue(first.startswith("BLU  1 Medic 1 Spy"), first)
            self.assertIn("Medic alive", first)
            self.assertIn("Spies 1 (1 alive)", first)
            a.board[dan]["m_bAlive"] = "false"  # their Medic dies
            self.assertIn("MEDIC DOWN - PUSH", text())
            self.assertIn("MEDIC DOWN - PUSH", text())  # and it stays for a few seconds
            a.classes[hank] = "Medic"  # a second Medic
            self.assertIn("(now 2 Medic)", text())
            self.assertNotIn("Back:", text())  # no players remembered from earlier matches
            g.on_screen_thread(lambda: a.hud_tick())
            self.assertTrue(a.hud.shown)  # drawn
            g.on_screen_thread(a.toggle_hud)
            self.assertFalse(a.cfg["hud"])
            self.assertEqual(a.hud.shown, ())  # switched off: nothing drawn
            self.assertEqual(a.hud_button.value.cget("text"), "OFF")
        Game().play(script)

    def test_it_can_be_moved_and_keeps_its_place(self):
        def script(g):
            a = g.app
            self.assertEqual(g.on_screen_thread(a.hud.where), (-5000, -3800))  # the tests keep it off-screen
            g.on_screen_thread(a.toggle_hud_move)
            self.assertTrue(a.hud.moving)
            self.assertEqual(a.hud_move_button.value.cget("text"), "Done")
            self.assertTrue(a.hud.shown)  # something to grab while moving, even with no match
            press = type("E", (), {"x_root": 0, "y_root": 0})
            drag = type("E", (), {"x_root": 40, "y_root": 25})
            g.on_screen_thread(lambda: (a.hud._drag_start(press), a.hud._drag_move(drag), a.root.update()))
            g.on_screen_thread(a.toggle_hud_move)  # Done
            self.assertFalse(a.hud.moving)
            self.assertEqual((a.cfg["hud_x"], a.cfg["hud_y"]), (-4960, -3775))
            self.assertEqual(g.on_screen_thread(lambda: hud.default_place(a.root))[1] > 0, True)
        Game().play(script)

    def test_nothing_shows_before_the_teams_are_known(self):
        def script(g):
            self.assertEqual(g.on_screen_thread(g.app.hud_parts), [])
        Game().play(script)


if __name__ == "__main__":
    unittest.main()
