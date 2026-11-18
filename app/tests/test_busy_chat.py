"""A real App in a busy chat, with a fake model: these take a while, as they wait for the real spam limit."""
import time
import unittest

import ai
from helpers import Game
from ai import AI_REMINDER, AI_SYSTEM


class BusyChatTest(unittest.TestCase):
    def test_nothing_piles_up_and_the_newest_line_is_answered(self):
        def script(g):
            for i in range(20):
                g.say("Hank" if i % 2 else "dan", f"message {i}", 1)
                if i % 5 == 0:
                    g.lines.put(f"tomato :  my own line {i}")
            for _ in range(250):
                if not (g.app.ai_reply or g.app.ai_waiting or g.app.ai_asking):
                    break
                time.sleep(0.1)
            self.assertFalse(g.app.ai_reply or g.app.ai_waiting or g.app.ai_asking)
            self.assertLess(len(g.model.asked), 12)  # not one free answer per message
            self.assertGreaterEqual(len(g.said()), 2)
            newest = int(g.model.asked[-1].rsplit(" ", 1)[-1])
            self.assertGreaterEqual(newest, 15)
        Game().play(script)

    def test_map_and_reminder_go_with_the_question(self):
        def script(g):
            g.lines.put("map     : ctf_2fort at: 0 x, 0 y, 0 z")
            g.say("dan", "hello", 1)
            self.assertEqual(g.model.last_system, AI_SYSTEM)
            text = " ".join(g.model.last_parts)
            self.assertIn(AI_REMINDER, text)
            self.assertIn("ctf_2fort", text)
        Game().play(script)

    def test_the_real_scoreboard_goes_with_a_message(self):
        def script(g):
            sid = g.app.sid_by_name("dan")
            g.app.board[sid] = {"m_iScore": "7", "m_iDeaths": "3"}
            real_roll, ai.secrets.randbelow = ai.secrets.randbelow, lambda n: 1  # no full roast facts
            try:
                g.say("dan", "how many have i killed", 0.6)
            finally:
                ai.secrets.randbelow = real_roll
            self.assertIn("dan: 7 kills, 3 deaths", " ".join(g.model.last_parts))
        Game().play(script)

    def test_a_message_about_something_else_gets_no_scores(self):
        def script(g):
            g.app.board[g.app.sid_by_name("dan")] = {"m_iScore": "7", "m_iDeaths": "3"}
            g.say("dan", "this map is so boring", 0.6)
            text = " ".join(g.model.last_parts)
            self.assertNotIn("7 kills", text)
            self.assertIn(ai.AI_NO_SCORES, text)
        Game().play(script)

    def test_a_roast_gets_the_scores(self):
        def script(g):
            g.app.board[g.app.sid_by_name("dan")] = {"m_iScore": "7", "m_iDeaths": "3"}
            g.say("dan", "hoovy roast me", 0.6)
            self.assertIn("7 kills, 3 deaths", " ".join(g.model.last_parts))
        Game().play(script)

    def test_only_the_last_own_lines_go_back(self):
        def script(g):
            for i in range(ai.AI_OWN_LINES + 3):
                g.app.chat_log.append((time.time(), f"HoovyGPT (you): own line {i}", True))
                g.app.chat_log.append((time.time(), f"dan: their line {i}", False))
            text = g.on_screen_thread(g.app.chat_context)
            self.assertEqual(text.count("own line"), ai.AI_OWN_LINES)
            self.assertIn(f"own line {ai.AI_OWN_LINES + 2}", text)
            self.assertEqual(text.count("their line"), ai.AI_OWN_LINES + 3)
        Game().play(script)

    def test_a_question_is_only_kept_when_it_was_asked_for(self):
        def script(g):
            g.model.answer = "Is good. Does keyboard need funeral?"
            real_roll, ai.secrets.randbelow = ai.secrets.randbelow, lambda n: 11  # no question this time
            try:
                g.say("dan", "hello", 1)
                self.assertTrue(g.said()[-1].endswith("Is good."), g.said())
                ai.secrets.randbelow = lambda n: 1  # a question this time
                g.say("dan", "hello again", 4)
                self.assertTrue(g.said()[-1].endswith("funeral?"), g.said())
            finally:
                ai.secrets.randbelow = real_roll
        Game().play(script)

    def test_without_a_scoreboard_heavy_is_told_so(self):
        def script(g):
            g.app.board.clear()
            real_roll, ai.secrets.randbelow = ai.secrets.randbelow, lambda n: 1
            try:
                g.say("dan", "how many have i killed", 0.6)
            finally:
                ai.secrets.randbelow = real_roll
            self.assertIn(ai.AI_NO_SCORES, " ".join(g.model.last_parts))
        Game().play(script)

    def test_an_old_reply_is_thrown_away(self):
        def script(g):
            real_wait = g.app.chat_limit.wait
            g.app.chat_limit.wait = lambda at=None: 0.3  # the spam limit stays closed
            time.sleep(0.5)
            g.say("dan", "old news", 1)
            self.assertTrue(g.app.ai_reply)
            g.app.ai_reply_at -= 100  # pretend it has waited long enough
            time.sleep(0.6)
            self.assertFalse(g.app.ai_reply)
            g.app.chat_limit.wait = real_wait
            time.sleep(1)
            self.assertFalse([line for line in g.said() if "Heavy agrees" in line])
        Game().play(script)

    def test_muting_drops_what_is_waiting(self):
        def script(g):
            g.app.chat_limit.wait = lambda at=None: 0.3
            time.sleep(0.5)
            g.say("dan", "will be muted", 1)
            g.say("Hank", "second one", 0.3)
            self.assertTrue(g.app.ai_reply and g.app.ai_waiting)
            g.say("dan", "!badbot", 0.5)
            self.assertTrue(g.app.ai_muted)
            self.assertFalse(g.app.ai_reply or g.app.ai_waiting)
        Game().play(script)

    def test_a_crash_in_the_model_does_not_block_the_next_question(self):
        def script(g):
            g.model.crash_next = True
            g.say("dan", "crash now", 1)
            self.assertFalse(g.app.ai_asking)
            g.say("Hank", "are you alive", 8)
            self.assertTrue([line for line in g.said() if "Heavy agrees" in line])
        Game().play(script)


class MergedTranslationsTest(unittest.TestCase):
    def test_waiting_translations_go_out_as_one_line(self):
        def script(g):
            a = g.app
            a.chat_limit.tier1, a.chat_limit.tier2 = 1.0, 0.2  # the allowance is used up: lines must wait
            a.chat_limit.attempted = a.chat_limit.talked = time.time()
            g.on_screen_thread(lambda: [a.announce_chat(t) for t in ("A said: hi", "B said: gg", "C said: nice")])
            deadline = time.time() + 30
            while time.time() < deadline and not g.said():
                time.sleep(0.2)
            self.assertEqual(g.said(), ["A said: hi | B said: gg | C said: nice"])  # one line, not three
            g.on_screen_thread(lambda: a.announce_chat("Hank killed dan"))  # anything else stays its own line
            self.assertFalse(any("killed" in line and "said" in line for line in g.said()))
        Game().play(script)


if __name__ == "__main__":
    unittest.main()
