"""Keys saved while the scanner runs work without a restart, and the Help page lists every command."""
import os
import time
import unittest
from unittest import mock

from helpers import Game
import settings
import tf2_lobby_scanner

STEAM = "0123456789ABCDEF0123456789ABCDEF"


def texts(widget):
    """Every label text under a widget."""
    found = []
    for child in widget.winfo_children():
        try:
            found.append(child.cget("text"))
        except Exception:
            pass
        found += texts(child)
    return found


class LiveKeysTest(unittest.TestCase):
    def test_a_key_saved_while_running_is_used_at_once(self):
        def script(g):
            a = g.app
            self.assertEqual(a.api_state, "no key")
            with open(settings.SECRETS_PATH, "w", encoding="utf-8") as f:
                f.write(f"STEAM_API_KEY={STEAM}\n")  # a test file, not yours (helpers.py)
            asked = []
            with mock.patch.object(tf2_lobby_scanner, "load_secrets", lambda: {"steam_api_key": STEAM}), \
                    mock.patch.object(a.lookups, "put", asked.append):
                g.on_screen_thread(lambda: a.reload_keys(now=time.time() + 60))
            self.assertEqual(a.cfg["steam_api_key"], STEAM)
            self.assertEqual(a.api_state, "ok")
            self.assertEqual(set(asked), set(a.players))  # everyone here is looked up with the new key
            self.assertTrue(any("New key found: steam" in t for _, t, _ in a.toast.items))
            # Nothing changed since: no second look-up round.
            asked.clear()
            with mock.patch.object(tf2_lobby_scanner, "load_secrets", lambda: {"steam_api_key": STEAM}), \
                    mock.patch.object(a.lookups, "put", asked.append):
                g.on_screen_thread(lambda: a.reload_keys(now=time.time() + 120))
            self.assertEqual(asked, [])
        Game(steam_api_key="", steamhistory_api_key="").play(script)

    def test_the_test_never_touches_your_real_key_file(self):
        self.assertNotEqual(settings.SECRETS_PATH,
                            os.path.join(os.path.expanduser("~"), ".secrets", "tf2translator", ".env"))


class HelpPageTest(unittest.TestCase):
    def test_every_command_is_on_the_help_page(self):
        def script(g):
            a = g.app
            g.on_screen_thread(lambda: (a.set_visible(True), a.show_page("Help")))
            shown = g.on_screen_thread(lambda: texts(a.pages["Help"]))
            for command in ("!who <name>", "!check <name>", "!medic", "!top", "!kd <name>", "!hours <name>",
                            "!cheaters", "!ip <name>", "!help", "!speak <language> <message>", "!badbot",
                            "!goodbot", "!duel <name>", "!duel scores", "F9", "F8"):
                self.assertIn(command, shown)
            self.assertNotIn("F4", shown)
            self.assertNotIn("Home", shown)  # !speak is switched on the Chat page now
        Game().play(script)



class ChatPreviewTest(unittest.TestCase):
    def test_hovering_a_card_plays_what_it_posts(self):
        import screens
        def script(g):
            a = g.app
            g.on_screen_thread(lambda: (a.set_visible(True), a.show_page("Chat")))
            card = a.beef_button
            self.assertIsNotNone(card.preview)
            self.assertIsNone(a.speak_mutes_button.preview)  # a list, nothing to play
            g.on_screen_thread(card._enter)
            time.sleep(screens.PREVIEW_DELAY / 1000 + len(screens.CHAT_EXAMPLES["beef"]) * screens.PREVIEW_STEP / 1000 + 0.5)
            shown = g.on_screen_thread(lambda: texts(card.preview.win) if card.preview.win else [])
            self.assertIn("'Ivan' (RU) killed 'Taras' (UA) | Russia 1 - 0 Ukraine. Za pobedu!", shown)
            g.on_screen_thread(card.preview.hide)
            self.assertIsNone(card.preview.win)
        Game().play(script)


if __name__ == "__main__":
    unittest.main()
