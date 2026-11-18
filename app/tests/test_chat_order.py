"""The order chat lines go out in, and noticing lines the server refused. A real App, with a fake model."""
import time
import unittest

from helpers import Game
import chat


class ChatOrderTest(unittest.TestCase):
    def test_you_then_heavy_then_announcements(self):
        def script(g):
            real_wait = g.app.chat_limit.wait
            g.app.chat_limit.wait = lambda at=None: 0.2  # hold everything back while it all queues up
            time.sleep(0.4)
            g.say("dan", "hello", 0.5)  # Heavy's reply is now waiting
            self.assertTrue(g.app.ai_reply)
            g.on_screen_thread(lambda: g.app.announce_chat("announcement"))
            g.on_screen_thread(lambda: g.app.queue_chat("my action"))
            g.app.chat_limit.wait = lambda at=None: 0.0
            time.sleep(1)
            g.app.chat_limit.wait = real_wait
            order = [line for line in g.said() if line.startswith(("my action", "announcement")) or "Heavy agrees" in line]
            self.assertEqual(len(order), 3, order)
            self.assertEqual(order[0], "my action")
            self.assertIn("Heavy agrees", order[1])
            self.assertEqual(order[2], "announcement")
        Game().play(script)

    def test_an_old_announcement_is_dropped(self):
        def script(g):
            g.app.chat_limit.wait = lambda at=None: 0.2
            time.sleep(0.4)
            g.app.announce_queue.append((time.time() - chat.ANNOUNCE_MAX_AGE - 1, "say", "too late"))
            g.on_screen_thread(g.app.send_next_chat)
            time.sleep(0.5)
            self.assertFalse(g.app.announce_queue)
            self.assertNotIn("too late", g.said())
        Game().play(script)

    def test_buttons_wait_for_the_spam_limit_too(self):
        def script(g):
            g.app.chat_limit.wait = lambda at=None: 0.3
            time.sleep(0.4)
            g.on_screen_thread(lambda: g.app.post("from a button"))
            time.sleep(0.1)
            self.assertNotIn("from a button", g.said())
            self.assertTrue(g.app.chat_queue)
        Game().play(script)


class RefusedChatTest(unittest.TestCase):
    def setUp(self):
        self.real_path, self.written = chat.CHAT_REFUSED_PATH, []
        chat.CHAT_REFUSED_PATH = chat.os.devnull
        self.real_wait, chat.CHAT_ECHO_WAIT = chat.CHAT_ECHO_WAIT, 0.6

    def tearDown(self):
        chat.CHAT_REFUSED_PATH, chat.CHAT_ECHO_WAIT = self.real_path, self.real_wait

    def test_a_line_that_comes_back_is_not_refused(self):
        def script(g):
            g.on_screen_thread(lambda: g.app.queue_chat("this one comes back"))
            time.sleep(4)
            self.assertIn("this one comes back", g.said())
            self.assertEqual(g.app.chat_refused_count, 0)
            self.assertFalse(g.app.chat_unconfirmed)
        Game().play(script)

    def test_a_line_that_never_comes_back_is_counted_and_slows_chat_down(self):
        def script(g):
            g.on_screen_thread(lambda: g.app.queue_chat("this one disappears"))
            time.sleep(4)
            self.assertIn("this one disappears", g.said())
            self.assertEqual(g.app.chat_refused_count, 1)
            self.assertGreater(g.app.chat_limit.wait(), 0)
        Game(echo=False).play(script)

    def test_without_a_server_nothing_counts_as_refused(self):
        def script(g):
            g.app.players.clear()
            g.on_screen_thread(lambda: g.app.queue_chat("nobody here"))
            time.sleep(4)
            self.assertEqual(g.app.chat_refused_count, 0, (list(g.app.players), g.said()))
        Game(echo=False).play(script)


if __name__ == "__main__":
    unittest.main()
