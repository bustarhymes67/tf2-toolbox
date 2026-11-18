"""The web window's Chat, Status and Help pages (web_chat_status_help.py): their state and clicks,
on a real App kept off-screen."""
import json
import unittest

from helpers import Game
from info_commands import INFO_COMMANDS
import screens
import web_state  # noqa: F401  (registers the pages and actions)
from web_chat_status_help import chat_state, help_state, status_state
from web_state import run_action


class WebChatStatusHelpTest(unittest.TestCase):
    def test_chat_page(self):
        def script(g):
            a = g.app

            def state():
                s = g.on_screen_thread(lambda: chat_state(a))
                json.dumps(s)  # the page gets it as JSON
                return s

            def act(*args):
                g.on_screen_thread(lambda: run_action(a, args[0], args[1:]))

            s = state()
            titles = [x["title"] for x in s["settings"]]
            self.assertEqual(titles[0], "Announcer: first blood, gardens, humiliations, rage-quits")
            self.assertIn("Country kill score: Russia vs Ukraine", titles)
            self.assertEqual(s["examples"].keys(), screens.CHAT_EXAMPLES.keys())
            self.assertEqual(s["preview_delay"], screens.PREVIEW_DELAY)
            self.assertTrue(all(x["example"] in s["examples"] for x in s["settings"]))
            for key, setting in (("announcer", "announcer"), ("ez", "ez_mode"), ("translate", "translate_to_chat"),
                                 ("beef", "country_beef_auto"), ("idle", "idle_rejoin")):
                was = a.cfg[setting]
                act("chat_toggle", key)
                self.assertEqual(a.cfg[setting], not was, key)
                self.assertEqual(next(x["on"] for x in state()["settings"] if x["key"] == key), not was)
            # The pills: !who, !speak, then every info command.
            ids = [c["id"] for c in s["commands"]]
            self.assertEqual(ids, ["who", "speak"] + [f"info:{c}" for c in INFO_COMMANDS])
            self.assertEqual(s["commands"][2]["usage"], ["!check", "<name>"])
            act("chat_command", "who")
            self.assertFalse(a.cfg["who_command"])
            act("chat_command", "speak")
            self.assertFalse(a.cfg["translate_command"])
            act("chat_command", "info:top")
            self.assertFalse(a.cfg["info_commands"]["top"])
            self.assertFalse(next(c["on"] for c in state()["commands"] if c["id"] == "info:top"))
            # !speak mutes: the count, and a click unmutes everyone.
            a.cfg["speak_muted"] = [123, 456]
            self.assertEqual(state()["muted"], 2)
            act("unmute_all_speak")
            self.assertEqual(state()["muted"], 0)
            a.chat_sent.append("FIRST BLOOD: 'Klaus' killed 'Ivan'")
            self.assertEqual(state()["posts"][-1], "FIRST BLOOD: 'Klaus' killed 'Ivan'")
            self.assertEqual((state()["sent"], state()["refused"]), (a.chat_sent_count, a.chat_refused_count))
        Game().play(script)

    def test_status_and_help_pages(self):
        def script(g):
            a = g.app
            s = g.on_screen_thread(lambda: status_state(a))
            json.dumps(s)
            self.assertEqual([c["name"] for c in s["connections"]], ["TF2", "Steam", "History", "Lists"])
            self.assertEqual([c["label"] for c in s["connections"]], ["TF2", "Steam", "Bans", "Cheater lists"])
            self.assertEqual([h["name"] for h in s["health"]], list(screens.HEALTH_ROWS))
            self.assertNotIn("keys", s)  # the keys are on the Help page, the Mini HUD on Players
            hud = a.cfg["hud"]
            g.on_screen_thread(lambda: run_action(a, "hud_toggle", []))
            self.assertEqual(a.cfg["hud"], not hud)
            g.on_screen_thread(lambda: run_action(a, "hud_move", []))
            self.assertTrue(a.hud.moving)
            g.on_screen_thread(lambda: run_action(a, "hud_move", []))  # Done
            self.assertFalse(a.hud.moving)

            h = g.on_screen_thread(lambda: help_state(a))
            json.dumps(h)
            cards = {c["id"]: c for c in h["cards"]}
            self.assertEqual([r["usage"][0] for r in cards["keys"]["rows"]], [a.cfg["toggle_key"], "F8"])
            self.assertEqual(cards["info"]["rows"], [])  # they are on the Chat page now
            self.assertEqual(cards["info"]["link"]["page"], "Chat")
            self.assertIn("Example: !speak russian hello", cards["speak"]["rows"][0]["about"])
            self.assertEqual(len(cards["duels"]["rows"]), len(screens.DUEL_COMMANDS))
        Game().play(script)


if __name__ == "__main__":
    unittest.main()
