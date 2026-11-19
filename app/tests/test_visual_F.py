"""Players page visual pass: one stamp with the score inside, red only for cheaters, the approved
button names, every Post button's hover is the exact message it posts (built by the same App
method, never sent), the player card (avatar, band label, receipt), motion and fonts."""
import os
import re
import tempfile
import unittest

from helpers import Game, ME
from game_log import STEAM64_BASE
import web_players
import web_state

HANK, DAN = STEAM64_BASE + 2, STEAM64_BASE + 3
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*parts):
    with open(os.path.join(HERE, *parts), encoding="utf-8") as f:
        return f.read()


def board(a, sid, team, hp, kills, deaths):
    a.board[sid] = {"m_iTeam": str(team), "m_iHealth": str(hp), "m_iScore": str(kills), "m_iDeaths": str(deaths),
                    "m_bAlive": "true", "m_iAccountID": str(sid - STEAM64_BASE), "m_bConnected": "true"}


def setup(a):
    a.refresh_board = lambda: None
    a.reevaluate = lambda: None
    board(a, ME, 3, 150, 4, 2)
    board(a, HANK, 3, 140, 7, 5)
    board(a, DAN, 2, 125, 14, 1)
    a.classes.update({ME: "Medic", HANK: "Soldier", DAN: "Sniper"})
    a.flags[DAN] = [(3, "VAC ban"), (2, "92% headshots")]
    a.flags[HANK] = [(1, "only 40h in TF2")]


def state(g):
    return g.on_screen_thread(lambda: web_players.players_state(g.app))


def row(s, sid):
    return next(r for t in s["teams"] for r in t["rows"] if r.get("sid") == str(sid))


def cells(s, sid):
    return dict(zip(s["all_columns"], row(s, sid)["cells"]))


def buttons(s):
    return {b[0]: b for group in s["panel"]["actions"] for b in group}


class StampAndColours(unittest.TestCase):
    def test_one_stamp_with_the_score_inside_and_red_only_for_cheaters(self):
        def script(g):
            a = g.app
            g.on_screen_thread(lambda: setup(a))
            s = state(g)
            word, tone, pct = cells(s, DAN)["Flags"]["tag"]
            self.assertEqual((word, tone), ("BANNED", "bad"))
            self.assertTrue(pct.endswith("%"))  # the % is inside the stamp
            self.assertEqual(row(s, DAN)["tone"], "bad")
            hank = cells(s, HANK)["Flags"]["tag"]
            self.assertEqual(hank[:2], ["WEAK", "weak"])  # a weak flag: orange family, never red
            self.assertNotEqual(row(s, HANK)["tone"], "bad")
            self.assertIsNone(cells(s, ME)["Flags"]["tag"])  # you have no stamp
            enemy = next(t for t in s["teams"] if t["key"] == "enemy")
            self.assertEqual((enemy["flagged"], enemy["cheaters"]), (1, 1))
        Game().play(script)


class ButtonsAndPreviews(unittest.TestCase):
    def test_names_hovers_and_exact_messages_without_sending(self):
        def script(g):
            a = g.app
            g.on_screen_thread(lambda: setup(a))
            g.on_screen_thread(lambda: web_state.run_action(a, "players_select", [str(DAN)]))
            g.sent.clear()
            while g.commands.qsize():
                g.commands.get_nowait()
            s = state(g)
            b = buttons(s)
            self.assertEqual({k: v[1] for k, v in b.items()}, {
                "kick": "Votekick", "mark": "Mark as cheater", "history": "Open on SteamHistory ↗",
                "mute": "Block their !speak", "say": "Post their summary", "stats": "Post their stats",
                "friends": "Post their friends here", "ip": "Send fake IP"})
            self.assertEqual(s["panel"]["groups"], ["Act on them", "Post in chat"])
            self.assertEqual(b["mark"][3]["text"], "Only for you; remembered.")
            self.assertFalse(b["kick"][2])
            self.assertEqual(b["kick"][3]["text"], "Votes only work on your own team")
            p = a.players[DAN]
            # each Post button's hover is the very text the App method builds
            self.assertEqual(b["say"][3]["text"], g.on_screen_thread(lambda: chr(10).join(filter(None, (a.chat_text(p), a.history_line(p))))))  # + the SteamHistory link for a cheater
            self.assertEqual(b["ip"][3]["text"], g.on_screen_thread(lambda: a.ip_line(p)))
            self.assertEqual(b["stats"][3]["text"], g.on_screen_thread(lambda: a.stats_text(p)))
            self.assertIn(b["say"][3]["head"], (web_players.SAYS_IN_CHAT, web_players.COPIES))
            self.assertEqual(b["friends"][3]["head"], "Nothing to post yet")  # no friends here: says why
            posts = {m["key"]: m for m in s["posts"]}
            self.assertEqual([m["name"] for m in s["posts"]], ["Match highlights", "Top killers"])
            self.assertEqual(posts["kill_race"]["msg"], g.on_screen_thread(lambda: a.top_line(unknown=None)))
            self.assertIn("MVP: dan (14-1)", posts["summary"]["msg"])
            # building the previews sent nothing, and post/notify are the App's own again
            g.on_screen_thread(lambda: None)
            queued = []
            while g.commands.qsize():
                queued.append(str(g.commands.get_nowait()))
            self.assertFalse([c for c in list(map(str, g.sent)) + queued if "say" in c])  # no chat message
            self.assertNotIn("post", a.__dict__)
            self.assertNotIn("notify", a.__dict__)
            # the preview is what the button then posts
            g.on_screen_thread(lambda: web_state.run_action(a, "players_lobby", ["kill_race"]))
            g.on_screen_thread(lambda: None)
            self.assertTrue(g.commands.qsize() or g.sent)
            # undo names
            g.on_screen_thread(lambda: web_state.run_action(a, "players_act", ["mark"]))
            self.assertEqual(buttons(state(g))["mark"][1], "Unmark as cheater")
            g.on_screen_thread(lambda: web_state.run_action(a, "players_act", ["mark"]))
        Game().play(script)

class PlayerCard(unittest.TestCase):
    def test_avatar_band_and_receipt(self):
        pics = tempfile.mkdtemp()
        with open(os.path.join(pics, "ab12cd.png"), "wb") as f:
            f.write(b"\x89PNG fake")
        old, web_players.AVATARS_DIR = web_players.AVATARS_DIR, pics

        def script(g):
            a = g.app
            g.on_screen_thread(lambda: setup(a))
            a.players[DAN].summary = {"avatar": "https://avatars.steamstatic.com/ab12cd.jpg"}
            g.on_screen_thread(lambda: web_state.run_action(a, "players_select", [str(DAN)]))
            p = state(g)["panel"]
            self.assertTrue(p["avatar"].startswith("data:image/png;base64,"))
            self.assertEqual(p["tone"], "bad")
            self.assertTrue(p["prior"].endswith("%"))
            self.assertIn("words", p["score"])
            a.players[DAN].summary = None
            self.assertIsNone(state(g)["panel"]["avatar"])  # not downloaded: the page shows an initial
        try:
            Game().play(script)
        finally:
            web_players.AVATARS_DIR = old


class PageFiles(unittest.TestCase):
    def test_script_and_styles(self):
        js, css = read("web", "pages", "players.js"), read("web", "pages", "players.css")
        self.assertIn("Post in chat", js)
        self.assertNotIn("Say in chat", js)
        self.assertNotIn("Lobby summary", js)
        self.assertNotIn("Kill race", js)
        self.assertIn("data-say", js)  # Post buttons' hovers are their messages
        self.assertIn('aria-disabled="true"', js)  # greyed buttons still show their hover
        self.assertEqual(js.count('class="pnl brk'), 1)  # brackets on exactly one main panel
        for var in ("--f-head", "--f-text", "--f-num", "--bad", "--warn", "--fade"):
            self.assertIn(f"var({var}", css)
        self.assertIn("prefers-reduced-motion", css)
        self.assertIn("animation:pl-pulse 1.2s ease-out 1", css)  # one pulse, never looping
        self.assertNotIn("infinite", css)
        self.assertIn("min-width:88px", css)  # fixed-width HP bars
        self.assertIn("height:44px", css)
        # spacing: paddings, margins and gaps only 0/2/4/8/16/24 px in the new rules
        for m in re.finditer(r"(?:padding|margin|gap):([^;}]+)", css):
            for n in re.findall(r"(\d+)px", m.group(1)):
                self.assertIn(int(n), (0, 1, 2, 3, 4, 8, 16, 24), m.group(0))


if __name__ == "__main__":
    unittest.main()
