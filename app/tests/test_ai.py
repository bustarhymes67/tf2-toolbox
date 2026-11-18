"""HoovyGPT's counting and text handling, without asking any model."""
import json
import os
import tempfile
import time
import unittest

import helpers  # noqa: F401  (sets up the import path)
import ai


class WithoutLastQuestionTest(unittest.TestCase):
    def test_the_question_at_the_end_goes(self):
        self.assertEqual(ai.without_last_question("Stock is honest. Does Sniper get bored?"), "Stock is honest.")
        self.assertEqual(ai.without_last_question("Heavy is warm! Does love fit? Why hug screen?"), "Heavy is warm!")

    def test_only_a_question_stays(self):
        self.assertEqual(ai.without_last_question("Why are you so small?"), "Why are you so small?")

    def test_a_question_before_the_end_stays(self):
        answer = "Why are you so small? Heavy will never know."
        self.assertEqual(ai.without_last_question(answer), answer)


class ScoreWordsTest(unittest.TestCase):
    def test_score_questions(self):
        for message in ("how many have I killed", "whats my k/d", "my score?", "сколько я убил", "hoeveel kills heb ik"):
            self.assertTrue(ai.AI_SCORE_WORDS.search(message), message)

    def test_other_messages(self):
        for message in ("hi hoovy", "gg", "this map is so boring", "skill issue", "whats the best medigun"):
            self.assertFalse(ai.AI_SCORE_WORDS.search(message), message)


class AddressAskerTest(unittest.TestCase):
    def test_the_name_goes_in_front(self):
        self.assertEqual(ai.address_asker("Is good word.", "dan"), "dan, Is good word.")

    def test_their_own_greeting_is_replaced(self):
        for answer, asker in (
            ("Pancake man 92, alright is good word.", "The pancake man 92"),
            ("The pancake man 92, alright is good word.", "The pancake man 92"),
            ("pancake man: alright is good word.", "The pancake man 92"),
            ("Biscuit, alright is good word.", "-Biscuit-"),
            ("-Biscuit-, alright is good word.", "-Biscuit-"),
        ):
            self.assertEqual(ai.address_asker(answer, asker), f"{asker}, alright is good word.")

    def test_a_name_later_in_the_line_is_enough(self):
        answer = "Heavy sees The pancake man 92 is lost."
        self.assertEqual(ai.address_asker(answer, "The pancake man 92"), answer)

    def test_other_openings_stay(self):
        self.assertEqual(ai.address_asker("Good, Heavy likes this.", "dan"), "dan, Good, Heavy likes this.")
        self.assertEqual(ai.address_asker("Man is small.", "The pancake man 92"), "The pancake man 92, Man is small.")

    def test_a_name_without_letters_still_works(self):
        self.assertEqual(ai.address_asker("Is good.", "***"), "***, Is good.")


class QuotaTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.folder.name, "quota.json")
        self.quota = ai.AIQuota(self.path)

    def tearDown(self):
        self.folder.cleanup()

    def test_gemini_answers_and_tokens_add_up_and_are_saved(self):
        self.quota.gemini_answered("gemini-3.5-flash-lite", 1800)
        self.quota.gemini_answered("gemini-3.5-flash-lite", 200)
        self.assertEqual(self.quota.left("gemini-3.5-flash-lite"), 498)
        self.assertEqual(self.quota.tokens["gemini-3.5-flash-lite"], 2000)
        self.assertEqual(self.quota.last_tokens["gemini-3.5-flash-lite"], 200)
        self.assertEqual(json.load(open(self.path))["tokens"]["gemini-3.5-flash-lite"], 2000)

    def test_answering_clears_being_out(self):
        self.quota.gemini_out("gemini-3.6-flash", 20)
        self.assertEqual(self.quota.left("gemini-3.6-flash"), 0)
        self.quota.gemini_answered("gemini-3.6-flash", 10)
        self.assertEqual(self.quota.left("gemini-3.6-flash"), 19)

    def test_groq_tokens_come_back_over_time(self):
        self.quota.groq_headers("m", {"x-ratelimit-remaining-tokens": "6000", "x-ratelimit-limit-tokens": "8000",
                                      "x-ratelimit-reset-tokens": "1s", "x-ratelimit-remaining-requests": "999",
                                      "x-ratelimit-limit-requests": "1000", "x-ratelimit-reset-requests": "1m"})
        first = self.quota.tokens_left("m")
        time.sleep(0.3)
        self.assertGreater(self.quota.tokens_left("m"), first)
        time.sleep(0.8)
        self.assertEqual(self.quota.tokens_left("m"), 8000)

    def test_gemini_has_no_tokens_left(self):
        self.assertIsNone(self.quota.tokens_left("gemini-3.5-flash-lite"))

    def test_gemini_minute_limits_are_counted_here(self):
        self.assertEqual(self.quota.gemini_minute_left("gemini-3.5-flash-lite"), (15, 250_000))
        for _ in range(15):
            self.quota.gemini_answered("gemini-3.5-flash-lite", 2000)
        self.assertEqual(self.quota.gemini_minute_left("gemini-3.5-flash-lite"), (0, 220_000))
        self.assertTrue(self.quota.minute_full("gemini-3.5-flash-lite"))
        self.quota.recent["gemini-3.5-flash-lite"] = [(time.time() - 61, 2000)]  # a minute later
        self.assertEqual(self.quota.gemini_minute_left("gemini-3.5-flash-lite"), (15, 250_000))
        self.assertIsNone(self.quota.gemini_minute_left("openai/gpt-oss-120b"))

    def test_flash_lite_31_has_a_daily_limit(self):
        self.assertEqual(self.quota.daily_limit("gemini-3.1-flash-lite"), 500)

    def test_groq_reset_times(self):
        self.assertAlmostEqual(ai.groq_seconds("2m59.56s"), 179.56)
        self.assertAlmostEqual(ai.groq_seconds("134ms"), 0.134)
        self.assertEqual(ai.groq_seconds("1h2m"), 3720)


class TokenTableTest(unittest.TestCase):
    def test_every_model_has_a_row_and_the_first_is_marked(self):
        first = ai.AI_MODELS[0][1]
        text = ai.token_table(first)
        for _, model in ai.AI_MODELS:
            self.assertIn(model, text)
        self.assertTrue(any(line.startswith(">") and first in line for line in text.split("\n")))


class PromptTest(unittest.TestCase):
    def test_the_prompt_file_has_both_parts(self):
        self.assertIn("HoovyGPT", ai.AI_SYSTEM)
        self.assertIn("Heavy", ai.AI_REMINDER)
        self.assertNotIn("=====", ai.AI_SYSTEM + ai.AI_REMINDER)

    def test_a_reply_that_is_too_long_is_not_an_answer(self):
        turn = ai.ai_question_turn("dan: hi")
        self.assertEqual(ai.usable_reply("x" * (ai.AI_MAX_REPLY + 1), [turn]), "")
        self.assertEqual(ai.usable_reply("dan: Is good.", [turn]), "Is good.")


if __name__ == "__main__":
    unittest.main()
