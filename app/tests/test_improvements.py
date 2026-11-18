"""This round's changes: the Summary line in words, ping with weak finds, Votekick on the Cheat
check tab, skipping unchanged demos, rejoining after an idle kick, ai_log's size and saving keys."""
import contextlib
import json
import os
import tempfile
import threading
import time
import unittest
from collections import Counter

import helpers
from helpers import ME, Game
import ai
import chat
import demo_check
import settings
from player_flags import Player

DAN = ME + 2  # in Game's status: dan is an ally? Team isn't known without a scoreboard.


def player(name, hours, days, bans=None):
    p = Player(1, "[U:1:1]", 1, name, 600, 0)
    p.hours, p.summary, p.bans = hours, {"timecreated": time.time() - days * 86400 - 3600}, bans or {}
    return p


class DuelsStayOnTest(unittest.TestCase):
    def test_the_button_is_remembered_across_restarts(self):
        g = Game(heavy_talks=False, duels_on=True)
        self.assertTrue(g.app.ai_on)  # on from the start: duels work right after a restart

        def script(g):
            g.on_screen_thread(g.app.toggle_ai)
            self.assertFalse(g.app.cfg["duels_on"])
            g.on_screen_thread(g.app.toggle_ai)
            self.assertTrue(g.app.cfg["duels_on"])
            g.say("dan", "!duel Hank", 0.8)
            self.assertTrue(g.app.chat_duels)
        g.play(script)

    def test_with_heavy_talking_it_still_starts_off(self):
        g = Game(heavy_talks=True, duels_on=True)
        self.assertFalse(g.app.ai_on)
        g.play(lambda g: None)


class CritTextTest(unittest.TestCase):
    def test_summary_and_stats_say_the_same(self):
        from player_flags import crit_flag, crit_text
        flag = crit_flag((10, 10), {"crit_min_kills": 8})[1]
        line = chat.chat_line(player("Hector", None, 800), "RED", [(4, flag)])
        self.assertIn(crit_text((10, 10)), line)
        self.assertEqual(crit_text((10, 10)), "10/10 random-crit kills (100%), 1 in 1M by luck")
        self.assertEqual(crit_text((12, 3)), "3/12 random-crit kills (25%)")  # luck explains it: no odds


class EveryLanguageTest(unittest.TestCase):
    def test_every_language_but_english_and_slang(self):
        import queue, tf2_translator
        answers = {"hola amigos": ("hello friends", "es"), "bonjour tout le monde": ("hello everyone", "fr"),
                   "nice shot": ("nice shot", "en"), "ez": ("no", "eu"), "gg ez": ("this is it", "hu"),
                   "bruh": ("bruh", "id"), "1v1 me": ("1v1 me", "es"), "привет": ("hi", "ru")}
        old = tf2_translator.translate_chat
        tf2_translator.translate_chat = lambda msg, target: answers[msg]
        try:
            lines, results = queue.Queue(), queue.Queue()
            cfg = dict(tf2_translator.DEFAULTS)
            threading.Thread(target=tf2_translator.worker, args=(cfg, lines, results), daemon=True).start()
            for msg in answers:
                lines.put(f"dan :  {msg}")
            time.sleep(0.5)
            shown = [results.get_nowait()["text"] for _ in range(results.qsize())]
        finally:
            tf2_translator.translate_chat = old
        self.assertEqual(shown, ["hello friends", "hello everyone", "hi"])

    def test_plain_english_isnt_sent_to_google(self):
        from tf2_translator import looks_english
        for msg in ("nice shot", "spy is crocket", "sentry up", "uber ready", "kick him hes cheating", "?",
                    ":)", "gg ez", "why isnt it working", "the bot is broken"):
            self.assertTrue(looks_english(msg), msg)
        for msg in ("hola amigos", "bonjour tout le monde", "wie geht's", "jak się masz", "ciao ragazzi", "obrigado",
                    "как дела", "naber kanka", "como estas", "ik ben er"):
            self.assertFalse(looks_english(msg), msg)

    def test_translate_any_falls_back_to_mymemory_from_english(self):
        import tf2_translator
        asked = []

        def resting(text, target):
            raise RuntimeError("every translation service is resting")
        old = tf2_translator.translate_chat, tf2_translator.mymemory
        tf2_translator.translate_chat = resting
        tf2_translator.mymemory = lambda text, target, source: asked.append(source) or ("привет", source)
        try:
            self.assertEqual(tf2_translator.translate_any("hello", "ru"), ("привет", "en"))
            self.assertEqual(tf2_translator.translate_any("как дела", "de")[1], "ru")
            with self.assertRaises(RuntimeError):
                tf2_translator.translate_any("hello", "en")
        finally:
            tf2_translator.translate_chat, tf2_translator.mymemory = old
        self.assertEqual(asked, ["en", "ru"])


class NamesStayTest(unittest.TestCase):
    def test_player_names_are_not_translated(self):
        from tf2_translator import hide_names, show_names
        hidden, found = hide_names("Tomato and tom nice shot", {"tomato", "tom"})
        self.assertEqual(hidden, "90731 and 90732 nice shot")
        self.assertEqual(show_names("90731 y 90732 buen tiro", found), "Tomato y tom buen tiro")
        self.assertEqual(hide_names("tomatox", {"tomato"})[1], {})  # part of a longer word: left alone

    def test_the_worker_keeps_names_and_skips_lines_of_only_names(self):
        import queue
        import tf2_translator
        asked = []

        def fake(text, target):
            asked.append(text)
            return text.replace("privet", "hi"), "ru"
        real, tf2_translator.translate_chat = tf2_translator.translate_chat, fake
        tf2_translator.KEEP_NAMES = {"tomato"}
        lines, results = queue.Queue(), queue.Queue()
        threading.Thread(target=tf2_translator.worker, args=(dict(tf2_translator.DEFAULTS, target_lang="en"), lines, results),
                         daemon=True).start()
        try:
            lines.put("dan :  tomato")         # only a name: nothing to translate
            lines.put("dan :  tomato gg")      # a name and English slang: nothing either
            lines.put("dan :  privet tomato")  # foreign: translated, the name kept
            entry = results.get(timeout=5)
            self.assertEqual(entry["text"], "hi tomato")
            self.assertEqual(asked, ["privet 90731"])
            self.assertTrue(results.empty())
        finally:
            tf2_translator.KEEP_NAMES = set()
            tf2_translator.translate_chat = real


class TranslateCommandTest(unittest.TestCase):
    def test_languages_by_name_code_and_start(self):
        from tf2_translator import language_code
        for word, code in (("russian", "ru"), ("Turkish", "tr"), ("german", "de"), ("DE", "de"), ("rus", "ru"),
                           ("русский", "ru"), ("chinese", "zh-CN"), ("zh", "zh-CN"), ("klingon", None),
                           ("po", None), ("s", None)):
            self.assertEqual(language_code(word), code, word)

    def test_check_says_a_players_summary(self):
        def script(g):
            a = g.app
            hank = a.sid_by_name("Hank")
            a.flags[hank] = [(3, "1 VAC ban (36d ago)")]
            a.reevaluate = lambda: None
            a.classes[hank] = "Sniper"
            a.players[hank].summary = {"loccountrycode": "RU"}
            a.kills[hank] = [10, 9]
            g.say("dan", "!who han", 0.2)  # part of a name, any case
            deadline = time.time() + 15
            while time.time() < deadline and len(g.said()) < 2:
                time.sleep(0.2)
            self.assertEqual(g.said(), ["Hank (Russia) | VAC banned 36 days ago", "Hank | Sniper | 9/10 headshots (90%)"])  # summary with their country, then stats
            self.assertEqual(a.chat_text(a.players[hank]), "Hank | VAC banned 36 days ago")  # the Summary button: as before
            self.assertEqual(a.chat_text(a.players[a.sid_by_name("dan")], country=True),
                             a.chat_text(a.players[a.sid_by_name("dan")]))  # no country set: nothing added
            self.assertIn("VAC banned 36 days ago", g.said()[0])
            a.classes.pop(hank), a.kills.pop(hank)  # nothing known this match: just the summary
            time.sleep(0.5)
            def said(text):  # TF2's spam limit makes later lines wait their turn
                deadline = time.time() + 20
                while time.time() < deadline and not any(text in line for line in g.sent):
                    time.sleep(0.2)
                return any(text in line for line in g.sent)
            g.say("(TEAM) dan", "!who Hank")
            self.assertTrue(said('say_team "Hank'))
            g.say("dan", "!who zzz")
            self.assertTrue(said("[WHO] nobody here is called 'zzz'"))
            g.say("dan", "!who a")  # in "Hank", "dan" and "tomato"
            self.assertTrue(said("Type more of the name"))
            time.sleep(0.5)
            g.on_screen_thread(a.toggle_who_command)
            before = list(g.said())
            g.say("dan", "!who Hank", 0.6)
            self.assertEqual(g.said(), before)  # switched off: no answer
            self.assertFalse(a.cfg["who_command"])  # the !who pill on the Chat page
        Game().play(script)

    def test_a_muted_players_speak_is_ignored(self):
        asked = []

        def fake(text, target):
            asked.append(text)
            return f"<{target}> {text}", "en"
        undo = helpers.patch_everywhere("translate_any", fake)

        def script(g):
            a = g.app
            dan = a.sid_by_name("dan")
            g.on_screen_thread(lambda: (a.select(dan), a.toggle_speak_mute()))
            self.assertEqual(a.cfg["speak_muted"], [dan])
            self.assertEqual(a.buttons["mute"].cget("text"), "Unmute !speak")
            self.assertEqual(a.speak_mutes_button.value.cget("text"), "1 muted")
            g.say("dan", "!speak russian spam", 0.5)
            g.say("Hank", "!speak russian hello", 0.6)
            self.assertEqual(asked, ["hello"])  # only the one who isn't muted
            g.on_screen_thread(a.toggle_speak_mute)  # the same button: Unmute
            self.assertEqual(a.cfg["speak_muted"], [])
            g.say("dan", "!speak russian back", 0.6)
            self.assertEqual(asked, ["hello", "back"])
            g.on_screen_thread(a.toggle_speak_mute)
            g.on_screen_thread(a.unmute_all_speak)  # the card on the Chat page
            self.assertEqual(a.cfg["speak_muted"], [])
            self.assertEqual(settings.DEFAULTS["speak_muted"], [])
        try:
            Game().play(script)
        finally:
            undo()

    def test_translate_says_it_and_the_switch_stops_it(self):
        asked = []

        def fake(text, target):
            asked.append((text, target))
            return f"<{target}> {text}", "en"
        undo = helpers.patch_everywhere("translate_any", fake)

        def script(g):
            a = g.app
            g.say("dan", "!speak russian good game everyone", 0.6)
            self.assertEqual(asked, [("good game everyone", "ru")])
            self.assertIn("dan said: <ru> good game everyone", g.said())
            g.say("(TEAM) Hank", "!speak de nice shot", 0.6)
            self.assertIn('say_team "Hank said: <de> nice shot"', g.sent)
            g.say("dan", "!translate russian old command", 0.4)  # the old name does nothing now
            g.say("dan", "!speak klingon hello", 0.4)  # unknown language: nothing in chat
            self.assertEqual(len(asked), 2)
            g.on_screen_thread(a.toggle_translate_command)  # the !speak pill on the Chat page
            time.sleep(0.3)
            self.assertFalse(a.cfg["translate_command"])
            before = list(g.said())
            g.say("dan", "!speak turkish spam spam", 0.5)
            self.assertEqual(g.said(), before)
            self.assertEqual(len(asked), 2)
            g.on_screen_thread(a.toggle_translate_command)  # the !speak pill on the Chat page
            time.sleep(0.3)
            g.say("dan", "!speak turkish back on", 0.6)
            self.assertIn("dan said: <tr> back on", g.said())
        try:
            Game().play(script)
        finally:
            undo()


class SummaryLineTest(unittest.TestCase):
    def test_clean_player_in_words(self):
        self.assertEqual(chat.chat_line(player("Hank", 1240, 1100), "RED", []),
                         "Hank (RED) | clean: no bans, not on any cheater list | 1,240 hours in TF2, account 3 years old")

    def test_new_account_in_days(self):
        self.assertEqual(chat.chat_line(player("xX", 12, 36), "BLU", [(1, "new account"), (1, "Steam level 0")]),
                         "xX (BLU) | Steam level 0 | 12 hours in TF2, account 36 days old")

    def test_bans_and_live_stats_in_words(self):
        line = chat.chat_line(player("Spy Guy", None, 800, {"NumberOfVACBans": 1}), "BLU",
                              [(3, "1 VAC ban (36d ago)"), (3, "on 3 lists (cheater)"),
                               (4, "70% crit kills (14/20), possible crit hack")])
        self.assertEqual(line, "Spy Guy (BLU) | 14/20 random-crit kills (70%), 1 in 34k by luck | on 3 cheater lists | "
                               "VAC banned 36 days ago")

    def test_several_bans(self):
        line = chat.chat_line(player("x", 10, 5, {"NumberOfVACBans": 2}), "RED", [(3, "2 VAC ban + 1 game ban (1d ago)")])
        self.assertEqual(line, "x (RED) | 2 VAC bans + 1 game ban, last 1 day ago")

    def test_a_long_name_still_fits(self):
        line = chat.chat_line(player("Тестовый очень длинное имя игрока", 52000, 4000), "RED", [])
        self.assertTrue(chat.fits(line, chat.CHAT_LIMIT), line)
        self.assertIn("52,000 hours in TF2", line)


class KeyTest(unittest.TestCase):
    def test_named_keys(self):
        from tf2_translator import key_to_vk
        self.assertEqual(key_to_vk("End"), 0x23)
        self.assertEqual(key_to_vk("Scroll Lock"), 0x91)
        self.assertEqual(key_to_vk("F12"), 0x7B)

    def test_removed_keys_are_dropped_from_a_saved_config(self):
        with temp_settings():
            open(settings.CONFIG_PATH, "w").write(
                '{"report_key": "End", "votekick_reply_key": "F11", "rcon_password": "x"}')
            cfg = settings.load_config()
            self.assertNotIn("report_key", cfg)
            self.assertNotIn("votekick_reply_key", cfg)


class PingTest(unittest.TestCase):
    def test_high_ping_is_named_with_weak_finds(self):
        flags = demo_check.demo_flags(Counter({"doubletap": 6}), ping=461)
        self.assertEqual(flags, [(1, "demo check: 6 double taps (ping 461 ms: lag alone can cause these)")])

    def test_normal_ping_says_nothing(self):
        self.assertEqual(demo_check.demo_flags(Counter({"doubletap": 6}), ping=60), [(1, "demo check: 6 double taps")])

    def test_details_show_the_ping(self):
        det = {"tick": 100, "algorithm": "doubletap", "player": 5, "data": {}}
        text = demo_check.detection_details(det, {5: "x"}, {}, {5: 461})
        self.assertIn('"ping": "461 ms (lag alone can cause these)"', text)
        strong = demo_check.detection_details(dict(det, algorithm="nocrex/oob_pitch"), {5: "x"}, {}, {5: 461})
        self.assertIn('"ping": "461 ms"', strong)  # lag can't cause the strong ones


class AiLogTest(unittest.TestCase):
    def test_the_log_keeps_its_newest_lines(self):
        with tempfile.TemporaryDirectory() as folder:
            real = ai.AI_LOG_PATH, ai.AI_LOG_MAX_BYTES, ai.AI_LOG_KEEP_LINES
            ai.AI_LOG_PATH, ai.AI_LOG_MAX_BYTES, ai.AI_LOG_KEEP_LINES = os.path.join(folder, "ai_log.txt"), 2000, 10
            try:
                for i in range(100):
                    ai.log_ai(time.time(), f"model-{i}", "answered", [])
                lines = open(ai.AI_LOG_PATH, encoding="utf-8").read().splitlines()
            finally:
                ai.AI_LOG_PATH, ai.AI_LOG_MAX_BYTES, ai.AI_LOG_KEEP_LINES = real
            self.assertLessEqual(len(lines), 40)
            self.assertIn("model-99", lines[-1])


@contextlib.contextmanager
def temp_settings():
    """The settings file and the secrets file in a folder of their own, so a test never touches the real ones."""
    with tempfile.TemporaryDirectory() as folder:
        real = settings.CONFIG_PATH, settings.SECRETS_PATH
        settings.CONFIG_PATH = os.path.join(folder, "project", "scanner_config.json")
        settings.SECRETS_PATH = os.path.join(folder, "secrets", ".env")
        os.makedirs(os.path.dirname(settings.CONFIG_PATH))
        try:
            yield folder
        finally:
            settings.CONFIG_PATH, settings.SECRETS_PATH = real


class SaveConfigTest(unittest.TestCase):
    def test_a_groq_key_pasted_in_meanwhile_is_kept(self):
        with temp_settings():
            settings.save_config({"groq_api_key": "pasted"})
            cfg = {"groq_api_key": ""}
            settings.save_config(cfg)
            self.assertEqual(cfg["groq_api_key"], "pasted")

    def test_keys_move_out_of_the_project_folder(self):
        with temp_settings():
            open(settings.CONFIG_PATH, "w").write('{"steam_api_key": "x", "rcon_password": "x", "page": "Status"}')
            cfg = settings.load_config()
            self.assertEqual((cfg["steam_api_key"], cfg["rcon_password"], cfg["page"]), ("x", "x", "Status"))
            in_project = json.load(open(settings.CONFIG_PATH))
            self.assertFalse(set(settings.SECRET_KEYS) & set(in_project))  # none left in the project folder
            self.assertEqual(in_project["page"], "Status")
            lines = open(settings.SECRETS_PATH).read().splitlines()
            self.assertIn("STEAM_API_KEY=x", lines)
            self.assertIn("RCON_PASSWORD=x", lines)
            self.assertEqual(settings.load_config()["steam_api_key"], "x")  # read back from the secrets file

    def test_the_renamed_commands_keep_their_switches(self):
        with temp_settings():
            open(settings.CONFIG_PATH, "w").write(
                '{"check_command": false, "info_commands": {"status": false, "top": true}}')
            cfg = settings.load_config()
            self.assertFalse(cfg["who_command"])      # the old !check is !who now
            self.assertFalse(cfg["info_commands"]["check"])  # the old !status is !check now
            self.assertNotIn("status", cfg["info_commands"])
            self.assertTrue(cfg["info_commands"]["ip"])  # one that came later: on

    def test_the_old_flagged_only_switch_becomes_the_flagged_chip(self):
        with temp_settings():
            open(settings.CONFIG_PATH, "w").write('{"flagged_only": true, "columns": ["Kills", "Deaths", "Flags"]}')
            cfg = settings.load_config()
            self.assertEqual(cfg["player_filter"], "flagged")
            self.assertNotIn("flagged_only", cfg)
            self.assertEqual(cfg["columns"], ["K/D", "Flags"])

    def test_other_lines_in_the_secrets_file_are_kept(self):
        with temp_settings():
            os.makedirs(os.path.dirname(settings.SECRETS_PATH))
            open(settings.SECRETS_PATH, "w").write("# mine\nOTHER=1\nGROQ_API_KEY=x\n")
            cfg = settings.load_config()
            self.assertEqual(cfg["groq_api_key"], "x")
            self.assertTrue(cfg["rcon_password"])  # made the first time, and saved next to it
            lines = open(settings.SECRETS_PATH).read().splitlines()
            self.assertEqual(lines[:2], ["# mine", "OTHER=1"])
            self.assertIn("GROQ_API_KEY=x", lines)


class SkipUnchangedDemoTest(unittest.TestCase):
    def test_an_unchanged_demo_is_not_checked_again(self):
        with tempfile.TemporaryDirectory() as folder:
            dem = os.path.join(folder, "2026-11-06_00-30-00.dem")
            open(dem, "wb").write(b"x" * 100)
            runs = []
            real = demo_check.run_tool, demo_check.DEMO_CHECK_SECONDS, demo_check.DEMO_TOOL
            demo_check.run_tool = lambda path: runs.append(path) or {"detections": [], "duration": 10}
            demo_check.DEMO_CHECK_SECONDS, demo_check.DEMO_TOOL = 0.05, dem  # any file that exists
            events = __import__("queue").Queue()
            cfg = dict(settings.DEFAULTS, demos_dir=folder, demo_check=True)
            try:
                threading.Thread(target=demo_check.demo_worker, args=(cfg, events), daemon=True).start()
                time.sleep(0.5)
                self.assertEqual(len(runs), 1)
                with open(dem, "ab") as f:
                    f.write(b"more")
                time.sleep(0.5)
                self.assertEqual(len(runs), 2)
            finally:
                cfg["demo_check"] = False  # the thread idles from here on
                time.sleep(0.2)
                demo_check.run_tool, demo_check.DEMO_CHECK_SECONDS, demo_check.DEMO_TOOL = real


class AppTest(unittest.TestCase):
    def test_after_an_idle_kick_nothing_is_typed(self):
        def script(g):  # only the retry 10 s before the kick is left (retry_before_idle_kick)
            g.lines.put("tomato has been idle for too long and has been kicked")
            g.lines.put("Disconnect: Kicked due to inactivity.")
            time.sleep(0.6)
            self.assertNotIn("retry", g.sent)
        Game(idle_rejoin=True).play(script)

    def test_without_the_setting_nothing_happens(self):
        def script(g):
            g.lines.put("Disconnect: Kicked due to inactivity.")
            time.sleep(0.6)
            self.assertNotIn("retry", g.sent)
        Game().play(script)

    def test_someone_else_idle_kicked_is_no_reason(self):
        def script(g):
            g.lines.put("dan has been idle for too long and has been kicked")
            time.sleep(0.6)
            self.assertNotIn("retry", g.sent)
        Game(idle_rejoin=True).play(script)

    def test_chat_lines_go_to_the_translator_and_nothing_else(self):
        def script(g):
            g.app.translator_lines = __import__("queue").Queue()
            g.lines.put("dan :  привет")
            g.lines.put("tomato killed dan with scattergun.")
            g.lines.put("tomato :  dan said: hi")  # your own lines (the scanner's posts) cost requests
            time.sleep(0.5)
            sent = list(g.app.translator_lines.queue)
            self.assertIn("dan :  привет", sent)
            self.assertNotIn("tomato :  dan said: hi", sent)
            self.assertNotIn("tomato killed dan with scattergun.", sent)  # kills aren't chat
        Game().play(script)

    def test_the_button_says_nothing_and_duels_work_without_a_key(self):
        undo = helpers.patch_everywhere("load_json", lambda path, default: {})
        def script(g):
            a = g.app
            a.ai_on = False
            g.on_screen_thread(a.toggle_ai)
            time.sleep(0.5)
            self.assertTrue(a.ai_on)
            self.assertEqual(g.said(), [])  # no greeting
            g.say("dan", "hello heavy", 0.5)
            self.assertEqual(g.model.asked, [])  # no AI without a key
            g.say("dan", "!badbot", 0.5)
            self.assertEqual(g.said(), [])  # no "Heavy goes quiet"
            g.say("dan", "!duel Hank", 0.8)
            self.assertTrue(a.chat_duels, g.said())
            g.on_screen_thread(a.toggle_ai)
            self.assertFalse(a.ai_on)
            self.assertEqual(a.chat_duels, [])
        try:
            Game(gemini_api_key="", groq_api_key="").play(script)
        finally:
            undo()

    def test_with_heavy_off_working_keys_change_nothing(self):
        def script(g):
            a = g.app
            a.ai_on = False
            checked = []
            a.check_ai_keys = checked.append
            g.on_screen_thread(a.toggle_ai)
            time.sleep(0.3)
            self.assertTrue(a.ai_on)
            self.assertEqual(checked, [])  # the keys aren't even tried
            for line in ("hello heavy", "!badbot", "!goodbot", "!help"):
                g.say("dan", line, 0.4)
            self.assertEqual(g.model.asked, [])
            self.assertEqual(g.said(), [])
            g.say("dan", "!duel Hank", 0.8)
            self.assertTrue(a.chat_duels)
        Game(heavy_talks=False).play(script)

    def test_no_chat_line_mentions_the_bot_commands(self):
        self.assertFalse(hasattr(chat, "VOTEKICK_REPLY"))  # F11's reply is gone
        self.assertNotIn("!help", chat.ANNOUNCER_ANNOUNCEMENT)
        self.assertFalse(hasattr(chat, "HELP_TEXT"))

    def test_with_a_key_the_button_is_silent_too(self):
        def script(g):
            a = g.app
            a.ai_on = False
            a.check_ai_keys = lambda keys: None  # not online
            g.on_screen_thread(a.toggle_ai)
            time.sleep(0.5)
            self.assertTrue(a.ai_on)
            self.assertEqual(g.said(), [])
        Game().play(script)

    def test_votekick_from_the_cheat_check_tab(self):
        def script(g):
            g.app.demo_picked_sid = DAN
            g.app.team_of = lambda p: "ALLY"
            g.on_screen_thread(g.app.votekick_demo_player)
            time.sleep(0.2)
            self.assertIn('callvote kick "3 cheating"', g.sent)
            g.app.team_of = lambda p: "ENEMY"
            g.on_screen_thread(g.app.votekick_demo_player)
            time.sleep(0.2)
            self.assertEqual(g.sent.count('callvote kick "3 cheating"'), 1)  # no second vote on an enemy
        Game().play(script)


if __name__ == "__main__":
    unittest.main()
