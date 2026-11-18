"""What the App does behind the web window's pages (screens.ScreensMixin): pages, settings, the player
list's chips, search, sorting, columns and teams, the selected player, the Status page's checks."""
import queue
import time
import unittest

from helpers import Game, ME
import lookups
import screens


def shown(a):
    """The names the player list shows now (chip and search applied), as the web Players page does."""
    players = [p for p in a.sorted_players() if p.sid == a.me or a.matches_filter(p, a.cfg["player_filter"])]
    return {p.name for p in players if not a.search or a.search in p.name.casefold()}


class ScreensTest(unittest.TestCase):
    def test_every_page_opens_and_is_remembered(self):
        def script(g):
            a = g.app
            for name in screens.PAGES:
                g.on_screen_thread(lambda: a.show_page(name))
                self.assertEqual(a.cfg["page"], name)
            g.on_screen_thread(lambda: a.show_page("HoovyGPT"))  # a saved page from before
            self.assertEqual(a.cfg["page"], "Duels")
            g.on_screen_thread(lambda: a.show_page("Nonsense"))
            self.assertEqual(a.cfg["page"], "Players")
        Game().play(script)

    def test_the_settings_do_what_they_say(self):
        def script(g):
            a = g.app
            for method, key in ((a.toggle_ez_mode, "ez_mode"), (a.toggle_announcer, "announcer"),
                                (a.toggle_translate_to_chat, "translate_to_chat"),
                                (a.toggle_country_beef, "country_beef_auto"), (a.toggle_idle_rejoin, "idle_rejoin"),
                                (a.toggle_demo_check, "demo_check"), (a.toggle_demo_keep, "demo_keep_only_cheaters"),
                                (a.toggle_record_only_flagged, "record_only_flagged"), (a.toggle_hud, "hud"),
                                (a.toggle_who_command, "who_command"), (a.toggle_translate_command, "translate_command")):
                before = a.cfg[key]
                g.on_screen_thread(method)
                self.assertNotEqual(a.cfg[key], before, key)
                g.on_screen_thread(method)
                self.assertEqual(a.cfg[key], before, key)
            g.on_screen_thread(lambda: a.toggle_info_command("top"))
            self.assertFalse(a.cfg["info_commands"]["top"])
            g.on_screen_thread(lambda: a.pick_model("auto"))
            self.assertEqual(a.cfg["ai_model"], "auto")
        Game().play(script)

    def test_the_players_buttons_are_all_there(self):
        keys = {key for _, entries in screens.PLAYER_ACTIONS for key, _, _ in entries}
        self.assertEqual(keys, {"kick", "mark", "history", "mute", "say", "stats", "friends", "ip"})

        def script(g):
            a = g.app
            for _, entries in screens.PLAYER_ACTIONS:
                for _, _, method in entries:
                    self.assertTrue(callable(getattr(a, method)), method)
            self.assertNotIn("team_ip_key", a.cfg)  # F4 is gone; the Send fake IP button and !ip stay
            self.assertFalse(hasattr(a, "team_ips"))
        Game().play(script)

    def test_clicking_a_player_selects_them_and_again_closes_it(self):
        def script(g):
            a = g.app
            other = next(sid for sid in a.players if sid != ME)
            g.on_screen_thread(lambda: a.select(other))
            self.assertEqual(a.selected, other)
            self.assertIn("ip", a.applicable(a.players[other]))
            g.on_screen_thread(lambda: a.select(other))
            self.assertIsNone(a.selected)
        Game().play(script)

    def test_the_lock_can_be_picked(self):
        def script(g):
            a = g.app
            g.on_screen_thread(lambda: a.pick_lock("muted"))
            self.assertEqual(a.cfg["ai_lock"], "muted")
            g.on_screen_thread(lambda: a.pick_lock(None))
            self.assertIsNone(a.cfg["ai_lock"])
        Game().play(script)

    def test_the_chips_filter_the_list(self):
        def script(g):
            a = g.app
            hank, dan = (next(sid for sid, p in a.players.items() if p.name == name) for name in ("Hank", "dan"))
            a.reevaluate = lambda: None
            a.flags[hank] = [(3, "1 VAC ban (2d ago)"), (1, "new account")]
            a.flags[dan] = [(1, "only 12h in TF2")]
            others = [p for p in a.players.values() if p.sid != ME]
            counts = {name: sum(a.matches_filter(p, name) for p in others) for name, _ in screens.FILTERS[1:]}
            self.assertEqual(counts, {"flagged": 2, "cheaters": 1, "new": 1})
            self.assertEqual(shown(a), {"tomato", "Hank", "dan"})
            g.on_screen_thread(lambda: a.set_filter("cheaters"))
            self.assertEqual(shown(a), {"tomato", "Hank"})  # you stay in the list
            self.assertEqual(a.cfg["player_filter"], "cheaters")
            g.on_screen_thread(lambda: a.set_filter("all"))
        Game().play(script)

    def test_an_unknown_saved_chip_becomes_everyone(self):
        def script(g):
            self.assertEqual(g.app.cfg["player_filter"], "all")
        Game(player_filter="gone").play(script)

    def test_the_search_box_finds_players_by_name(self):
        def script(g):
            a = g.app
            g.on_screen_thread(lambda: a.set_search("  HaN "))
            self.assertEqual(a.search, "han")
            self.assertEqual(shown(a), {"Hank"})
            g.on_screen_thread(lambda: a.set_search(""))
            self.assertEqual(shown(a), {"tomato", "Hank", "dan"})
        Game().play(script)

    def test_sorting_goes_natural_reversed_then_default(self):
        def script(g):
            a = g.app
            g.on_screen_thread(lambda: a.sort_by("Player"))
            self.assertEqual((a.sort_column, a.sort_descending), ("Player", False))
            self.assertEqual([p.name for p in a.sorted_players()], ["dan", "Hank", "tomato"])
            g.on_screen_thread(lambda: a.sort_by("Player"))
            self.assertEqual((a.sort_column, a.sort_descending), ("Player", True))
            g.on_screen_thread(lambda: a.sort_by("Player"))
            self.assertIsNone(a.sort_column)
        Game().play(script)

    def test_players_are_grouped_by_team(self):
        def script(g):
            a = g.app
            for sid, team in zip(a.players, ("TF_GC_TEAM_DEFENDERS", "TF_GC_TEAM_DEFENDERS", "TF_GC_TEAM_INVADERS")):
                a.lobby_team[sid] = team
            sides = g.on_screen_thread(lambda: a.team_sides(a.sorted_players()))
            self.assertEqual([len(sides[k][2]) for k in ("mine", "enemy")], [2, 1])
            self.assertIn("YOUR TEAM", sides["mine"][0])
            self.assertIn("ENEMY TEAM", sides["enemy"][0])
        Game().play(script)

    def test_rows_have_one_kd_column_and_the_health(self):
        def script(g):
            a = g.app
            other = next(sid for sid in a.players if sid != ME)
            a.board[other] = {"m_iScore": "12", "m_iDeaths": "9", "m_iHealth": "150", "m_bAlive": "true"}
            a.classes[other] = "Heavy"
            row = dict(zip(screens.COLUMNS, g.on_screen_thread(lambda: a.row_cells(a.players[other]))))
            self.assertEqual(row["K/D"][0], "12/9")
            self.assertEqual(row["HP"][0], "150")
            self.assertTrue(all(len(cell) == 2 for cell in row.values()))  # (text, colour): no Tk pictures
        Game().play(script)

    def test_avatars_only_come_from_steams_picture_server(self):
        events = queue.Queue()
        lookups.download_avatar(1, "https://example.com/abc123.jpg", events)
        lookups.download_avatar(1, "http://avatars.steamstatic.com/abc123.jpg", events)  # not https
        lookups.download_avatar(1, "https://evilsteamstatic.com/abc123.jpg", events)
        self.assertTrue(events.empty())

    def test_stop_all_duels(self):
        def script(g):
            a = g.app
            self.assertEqual(a.duel_entries(), [])
            g.say("dan", "!duel Hank", 0.8)
            self.assertTrue(a.chat_duels)
            self.assertEqual(a.duel_entries(), ["dan 0-0 Hank"])
            g.on_screen_thread(a.stop_duels_from_page)
            self.assertFalse(a.chat_duels)
        Game(heavy_talks=False, duels_on=True).play(script)

    def test_duels_come_back_on_after_a_restart_unless_heavy_may_talk(self):
        def script(g):
            self.assertTrue(g.app.cfg["duels_on"])
        Game(heavy_talks=False, duels_on=True).play(script)

    def test_the_status_page_says_what_works_and_what_doesnt(self):
        import tf2_translator

        def script(g):
            a = g.app
            health = {name: (level, text) for name, level, text in g.on_screen_thread(a.feature_health)}
            self.assertEqual(set(health), set(screens.HEALTH_ROWS))
            self.assertEqual(health["Duels"][0], "ok")
            self.assertEqual(health["Translator"], ("ok", "working"))
            a.ai_on = False
            a.cfg["translate_command"] = False
            a.demo_state = "tools/demo-analysis.exe is missing"
            tf2_translator.resting_until[tf2_translator.google] = time.time() + 600
            self.addCleanup(tf2_translator.resting_until.clear)
            health = {name: (level, text) for name, level, text in g.on_screen_thread(a.feature_health)}
            self.assertEqual(health["Duels"], ("off", "off: switch them on on the Duels page"))
            self.assertEqual(health["!speak"], ("off", "off: switch it on on the Chat page"))
            self.assertEqual(health["Translator"][0], "warn")
            self.assertIn("Google resting until", health["Translator"][1])
            self.assertEqual(health["Cheat check"][0], "bad")
            for service in tf2_translator.TRANSLATORS:
                tf2_translator.resting_until[service] = time.time() + 600
            self.assertEqual(tf2_translator.translator_health()[0], "bad")
        Game().play(script)

    def test_players_are_not_remembered_across_matches(self):
        def script(g):
            a = g.app
            self.assertFalse(hasattr(a, "seen"))
            self.assertNotIn("Player memory", screens.HEALTH_ROWS)
        Game().play(script)

    def test_a_strip_under_each_team_sums_it_up(self):
        def script(g):
            a = g.app
            sids = list(a.players)
            a.classes.update({sids[0]: "Medic", sids[1]: "Medic", sids[2]: "Sniper"})
            a.players[sids[0]].hours, a.players[sids[1]].hours, a.players[sids[2]].hours = 1000, 2000, None
            a.flags[sids[2]] = [(1, "new account")]
            a.reevaluate = lambda: None
            self.assertEqual(a.team_strip([a.players[s] for s in sids[:2]]), "2 Medic · average 1,500 hours")
            self.assertEqual(a.team_strip([a.players[sids[2]]]), "1 Sniper · 1 new account")
            a.classes.clear()
            a.players[sids[0]].hours = None
            self.assertEqual(a.team_strip([a.players[sids[0]]]), "")
        Game().play(script)

    def test_columns_can_be_switched_on_and_off(self):
        def script(g):
            a = g.app
            self.assertIn("Ctry", a.cfg["columns"])
            self.assertNotIn("Streak", a.cfg["columns"])  # off until you pick it
            g.on_screen_thread(lambda: a.toggle_column("Class"))
            self.assertNotIn("Class", a.cfg["columns"])
            g.on_screen_thread(lambda: a.toggle_column("Class"))
            g.on_screen_thread(lambda: a.toggle_column("Streak"))
            self.assertEqual([c for c in a.cfg["columns"] if c in ("Class", "Streak")], ["Class", "Streak"])
        Game().play(script)

    def test_long_flags_are_cut_short_in_the_list(self):
        text, _ = screens.short_cell("Flags", ("1 server ban: Exploiting/Teleporting spies into base (BlackWonder)  +1", "r"))
        self.assertLessEqual(len(text), screens.FLAGS_CELL_CHARS)
        self.assertTrue(text.endswith("…  +1"))
        self.assertEqual(screens.short_cell("Player", ("x" * 60, "r")), ("x" * 60, "r"))

    def test_a_status_light_shows_how_a_connection_is_doing(self):
        for state, colour in (("connected", screens.GOOD), ("ok", screens.GOOD), ("24 cheaters known", screens.GOOD),
                              ("loading", screens.WAITING), ("not connected", screens.WAITING),
                              ("no key", screens.FAINT), ("wrong password", screens.BAD)):
            self.assertEqual(screens.status_colour(state), colour, state)

    def test_feedback_shows_and_goes(self):
        def script(g):
            a = g.app
            g.on_screen_thread(lambda: a.notify("Copied"))
            self.assertEqual(a.feedback, "Copied")
            time.sleep(3.3)
            self.assertEqual(a.feedback, "")
        Game().play(script)

    def test_no_tk_main_window(self):
        def script(g):
            a = g.app
            self.assertEqual(g.on_screen_thread(a.root.state), "withdrawn")
            for gone in ("sides", "tabs", "pages", "token_panel", "ai_button", "model_button"):
                self.assertFalse(hasattr(a, gone), gone)
        Game().play(script)


if __name__ == "__main__":
    unittest.main()
