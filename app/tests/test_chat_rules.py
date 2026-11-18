"""The chat rules that don't need a window: the spam limit, splitting lines, and fake addresses."""
import ipaddress
import random
import unittest

import helpers  # noqa: F401  (sets up the import path)
from chat import CHAT_LIMIT, ChatLimit, fake_ipv4, fits, split_chat


class ServerLimit:
    """TF2's own spam check, from CBasePlayer::CanPlayerTalk in Valve's source-sdk-2013. It's a separate
    copy from ChatLimit on purpose, so the scanner's model of the server is checked against the server."""

    def __init__(self, at):
        self.talked = self.attempted = at
        self.tier1, self.tier2 = 1.0, 10.0

    def try_line(self, at):
        elapsed = at - self.attempted
        self.attempted = at
        per_msg = 3.0 - min(0.0, self.tier1)
        self.tier1 = min(4.0, self.tier1 + max(0.0, elapsed / per_msg))
        self.tier2 = min(30.0, self.tier2 + max(0.0, elapsed / 10.0))
        ok = at - self.talked >= 0.66 and self.tier1 > 1.0 and self.tier2 > 1.0
        self.tier1 = max(-2.5, self.tier1 - 1.0)
        if self.tier1 > 0:
            self.tier2 = max(0.0, self.tier2 - 1.0)
        if ok:
            self.talked = at
        return ok


class ChatLimitTest(unittest.TestCase):
    def test_no_line_is_refused_with_lag(self):
        rng = random.Random(7)
        for _ in range(100):
            at = 1000.0
            limit, server = ChatLimit(), ServerLimit(at)
            limit.talked = limit.attempted = at
            for _ in range(60):
                at += limit.wait(at) + 0.02
                limit.note(at)
                self.assertTrue(server.try_line(at + rng.uniform(0, 0.1)))

    def test_a_burst_goes_about_as_fast_as_allowed(self):
        at = 1000.0
        limit = ChatLimit()
        limit.talked = limit.attempted = at
        for _ in range(11):
            at += limit.wait(at)
            limit.note(at)
        self.assertLess(at - 1000.0, 40)

    def test_your_own_line_uses_up_the_allowance_too(self):
        limit = ChatLimit()
        limit.talked = limit.attempted = 1000.0
        before = limit.wait(1000.0)
        limit.note(1000.0)
        self.assertGreater(limit.wait(1000.0), before)


class SplitChatTest(unittest.TestCase):
    def test_every_part_fits_and_nothing_is_lost(self):
        text = "word " * 60
        parts = split_chat(text.strip(), CHAT_LIMIT, 5)
        self.assertTrue(all(fits(p, CHAT_LIMIT) for p in parts))
        self.assertEqual(" ".join(parts), text.strip())

    def test_counts_bytes_not_letters(self):
        parts = split_chat("щ" * 100, CHAT_LIMIT, 2)
        self.assertTrue(all(fits(p, CHAT_LIMIT) for p in parts))

    def test_stops_at_max_parts(self):
        self.assertEqual(len(split_chat("word " * 200, CHAT_LIMIT, 2)), 2)


class FakeIpTest(unittest.TestCase):
    def test_never_a_real_address(self):
        for _ in range(5000):
            self.assertFalse(ipaddress.ip_address(fake_ipv4()).is_global)

    def test_addresses_jump_around(self):
        ips = [fake_ipv4() for _ in range(2000)]
        self.assertFalse([ip for ip in ips if ip.startswith(("192.", "172."))])
        starts = [ip.split(".")[:2] for ip in ips]
        self.assertTrue(all(a != b for a, b in zip(starts, starts[1:])))  # never the same start twice in a row
        self.assertGreaterEqual(len({ip.split(".")[0] for ip in ips}), 15)  # 10, 100, 169, 198, 203, 240-254


if __name__ == "__main__":
    unittest.main()
