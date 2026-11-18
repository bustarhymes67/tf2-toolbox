"""The translation chain: 1. Google, 2. DeepL (only with a key), 3. MyMemory. Every service is faked: nothing is sent to the internet."""
import io
import json
import os
import sys
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import tf2_translator as t  # noqa: E402


def too_many(code=429):
    return urllib.error.HTTPError("https://x", code, "too many", {}, io.BytesIO(b""))


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class ChainTest(unittest.TestCase):
    def setUp(self):
        self.old = t.TRANSLATORS, dict(t.KEYS)
        t.resting_until.clear()
        t.cache.clear()
        self.asked = []

    def fake(self, name, error=None, key=None):
        def service(text, target, source="auto"):
            self.asked.append(name)
            if error:
                raise error
            return f"{name}:{text}", "ru"
        service.__name__ = name
        if key:
            service.needs_key = key
        return service

    def tearDown(self):
        t.TRANSLATORS = self.old[0]
        t.KEYS.clear()
        t.KEYS.update(self.old[1])
        t.resting_until.clear()
        t.cache.clear()

    def test_the_order_is_google_deepl_mymemory(self):
        self.assertEqual([f.__name__ for f in self.old[0]], ["google", "deepl", "mymemory"])

    def test_google_answers_first(self):
        t.TRANSLATORS = [self.fake("google"), self.fake("deepl", key="deepl_api_key")]
        t.KEYS.update(deepl_api_key="k")
        self.assertEqual(t.translate("привет", "en"), ("google:привет", "ru"))
        self.assertEqual(self.asked, ["google"])

    def test_deepl_takes_over_when_google_rests(self):
        t.TRANSLATORS = [self.fake("google", error=too_many()), self.fake("deepl", key="deepl_api_key"),
                         self.fake("mymemory")]
        t.KEYS.update(deepl_api_key="k")
        self.assertEqual(t.translate("привет", "en")[0], "deepl:привет")
        self.assertEqual(self.asked, ["google", "deepl"])

    def test_mymemory_when_google_and_deepl_rest(self):
        t.TRANSLATORS = [self.fake("google", error=too_many()),
                         self.fake("deepl", error=too_many(456), key="deepl_api_key"), self.fake("mymemory")]
        t.KEYS.update(deepl_api_key="k")
        self.assertEqual(t.translate("привет", "en")[0], "mymemory:привет")
        self.assertEqual(self.asked, ["google", "deepl", "mymemory"])
        self.asked.clear()
        t.translate("пока", "en")  # both resting now: not asked again
        self.assertEqual(self.asked, ["mymemory"])
        state, text = t.translator_health()
        self.assertEqual(state, "warn")
        self.assertIn("Google, DeepL", text)

    def test_a_service_without_a_key_is_skipped(self):
        t.TRANSLATORS = [self.fake("google", error=too_many()), self.fake("deepl", key="deepl_api_key"),
                         self.fake("mymemory")]
        self.assertEqual(t.translate("привет", "en")[0], "mymemory:привет")
        self.assertEqual(self.asked, ["google", "mymemory"])


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.old = dict(t.KEYS)
        self.sent = []

    def tearDown(self):
        t.KEYS.clear()
        t.KEYS.update(self.old)

    def answer(self, body):
        def urlopen(req, timeout):
            self.sent.append(req)
            return FakeResponse(json.dumps(body).encode("utf-8"))
        return mock.patch.object(t.urllib.request, "urlopen", urlopen)

    def test_deepl_free_key_uses_the_free_address(self):
        t.KEYS.update(deepl_api_key="abc:fx")
        with self.answer({"translations": [{"detected_source_language": "RU", "text": "hello"}]}):
            self.assertEqual(t.deepl("привет", "en"), ("hello", "ru"))
        req = self.sent[0]
        self.assertTrue(req.full_url.startswith("https://api-free.deepl.com/v2/translate"))
        self.assertEqual(req.get_header("Authorization"), "DeepL-Auth-Key abc:fx")
        self.assertEqual(json.loads(req.data)["target_lang"], "EN-US")
        self.assertNotIn("source_lang", json.loads(req.data))

    def test_deepl_with_a_known_source(self):
        t.KEYS.update(deepl_api_key="pro")
        with self.answer({"translations": [{"detected_source_language": "TR", "text": "team bad"}]}):
            t.deepl("takım kötü", "en", "tr")
        self.assertTrue(self.sent[0].full_url.startswith("https://api.deepl.com/"))
        self.assertEqual(json.loads(self.sent[0].data)["source_lang"], "TR")


if __name__ == "__main__":
    unittest.main()
