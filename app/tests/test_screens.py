"""The buttons, the Settings menu, the reasons under the buttons and the tokens window, in a real App."""
import os
import queue
import tempfile
import time
import tkinter as tk
import unittest

from helpers import Game, ME
import lookups
import screens


def click_free_popup(*args):
    """Instead of Menu.tk_popup, which waits on Windows until someone closes the menu."""


def shown_rows(a):
    """How many player rows both halves of the list show now."""
    return sum(1 for side in a.sides.values() for state in side.row_state
               if isinstance(state, tuple) and state[0] != "team")


class ScreensTest(unittest.TestCase):
    def setUp(self):
        self.real_popup, tk.Menu.tk_popup = tk.Menu.tk_popup, click_free_popup

    def tearDown(self):
        tk.Menu.tk_popup = self.real_popup

    def test_every_page_opens_and_is_remembered(self):
        def script(g):
            a = g.app
            for name in screens.PAGES:
                g.on_screen_thread(lambda: a.show_page(name))
                self.assertEqual(a.cfg["page"], name)
                for other, page in a.pages.items():
                    self.assertEqual(bool(g.on_screen_thread(page.winfo_manager)), other == name)
            g.on_screen_thread(lambda: a.show_page("Players"))
        Game().play(script)

    def test_the_settings_do_what_they_say(self):
        def script(g):
            a = g.app
            for button, key in ((a.ez_button, "ez_mode"), (a.announcer_button, "announcer"),
                                (a.translate_button, "translate_to_chat"), (a.beef_button, "country_beef_auto")):
                before = a.cfg[key]
                g.on_screen_thread(button.action)
                self.assertNotEqual(a.cfg[key], before, key)
                self.assertEqual(button.value.cget("text"), "ON" if a.cfg[key] else "OFF", key)
                g.on_screen_thread(button.action)
                self.assertEqual(a.cfg[key], before, key)
            self.assertEqual(a.beef_button.title.cget("text"), "Country kill score: Russia vs Ukraine")
            g.on_screen_thread(a.show_model_menu)
        Game().play(script)

    def test_ipv4_and_the_lobby_buttons_are_there(self):
        def script(g):
            a = g.app
            self.assertEqual({b.cget("text") for b in a.lobby_buttons}, {"Kill race", "Lobby summary"})
            self.assertEqual(set(a.buttons), {"kick", "mark", "history", "mute", "say", "stats", "friends", "ip"})
            self.assertNotIn("team_ip_key", a.cfg)  # F4 is gone; the Send fake IP button and !ip stay
            self.assertFalse(hasattr(a, "team_ips"))
            self.assertTrue(g.on_screen_thread(lambda: a.idle_button.winfo_toplevel() is a.root))
        Game().play(script)

    def test_clicking_a_player_opens_their_panel_on_the_right(self):
        def script(g):
            a = g.app
            g.on_screen_thread(lambda: a.set_visible(True))
            g.on_screen_thread(a.render)
            self.assertFalse(g.on_screen_thread(a.actions.winfo_manager))  # nobody selected: no panel
            key = next(k for k in screens.SIDES if any(a.sides[k].row_sids))
            row = next(i for i, sid in enumerate(a.sides[key].row_sids) if sid and sid != ME)
            sid = a.sides[key].row_sids[row]
            g.on_screen_thread(lambda: a.select_row(key, row))  # a plain left click
            time.sleep(0.4)
            self.assertTrue(g.on_screen_thread(a.actions.winfo_manager))
            self.assertEqual(a.player_title.cget("text"), a.players[sid].name)
            self.assertTrue(a.buttons["ip"].enabled)
            self.assertEqual(a.buttons["kick"].cget("text"), "Votekick")
            g.on_screen_thread(lambda: a.select_row(key, row))  # clicking them again closes it
            time.sleep(0.4)
            self.assertFalse(g.on_screen_thread(a.actions.winfo_manager))
        Game().play(script)

    def test_the_lock_can_be_picked_on_its_page(self):
        def script(g):
            a = g.app
            g.on_screen_thread(lambda: a.pick_lock("muted"))
            self.assertEqual(a.cfg["ai_lock"], "muted")
            self.assertEqual(a.lock_control.labels["muted"]._fill, screens.ACCENT)
            g.on_screen_thread(lambda: a.pick_lock(None))
            self.assertEqual(a.lock_control.labels["off"]._fill, screens.ACCENT)
        Game().play(script)

    def test_the_chips_filter_the_list_and_count_who_they_show(self):
        def script(g):
            a = g.app
            hank, dan = (next(sid for sid, p in a.players.items() if p.name == name) for name in ("Hank", "dan"))
            a.flags[hank] = [(3, "1 VAC ban (2d ago)"), (1, "new account")]
            a.flags[dan] = [(1, "only 12h in TF2")]
            a.reevaluate = lambda: None
            g.on_screen_thread(lambda: (a.set_visible(True), a.render()))

            def shown():
                return {a.players[sid].name for side in a.sides.values() for sid in side.row_sids if sid}
            labels = a.filter_control.labels
            self.assertEqual([labels[name].cget("text") for name, _ in screens.FILTERS],
                             ["Everyone", "Flagged 2", "Cheaters 1", "New accounts 1"])
            self.assertEqual(shown(), {"tomato", "Hank", "dan"})
            g.on_screen_thread(lambda: a.set_filter("cheaters"))
            self.assertEqual(shown(), {"tomato", "Hank"})  # you stay in the list
            self.assertEqual(a.cfg["player_filter"], "cheaters")
            g.on_screen_thread(lambda: a.set_filter("flagged"))
            self.assertEqual(shown(), {"tomato", "Hank", "dan"})
            g.on_screen_thread(lambda: a.set_filter("all"))
        Game().play(script)

    def test_the_search_box_finds_players_by_name(self):
        def script(g):
            a = g.app
            g.on_screen_thread(lambda: (a.set_visible(True), a.render()))

            def shown():
                return {a.players[sid].name for side in a.sides.values() for sid in side.row_sids if sid}
            g.on_screen_thread(lambda: a.set_search("  HaN "))
            self.assertEqual(shown(), {"Hank"})
            g.on_screen_thread(lambda: a.set_search("zzz"))
            self.assertEqual(shown(), set())
            self.assertEqual(a.empty_label.cget("text"), "Nobody here matches that.")
            g.on_screen_thread(lambda: a.set_search(""))
            self.assertEqual(shown(), {"tomato", "Hank", "dan"})
        Game().play(script)

    def test_players_are_grouped_by_team_and_empty_columns_hidden(self):
        def script(g):
            a = g.app
            for sid, team in zip(a.players, ("TF_GC_TEAM_DEFENDERS", "TF_GC_TEAM_DEFENDERS", "TF_GC_TEAM_INVADERS")):
                a.lobby_team[sid] = team
            g.on_screen_thread(lambda: a.set_visible(True))
            g.on_screen_thread(a.render)
            sides = g.on_screen_thread(lambda: a.team_sides(a.sorted_players()))
            self.assertEqual([len(sides[k][2]) for k in screens.SIDES], [2, 1])
            self.assertIn("YOUR TEAM", a.sides["mine"].title.cget("text"))
            self.assertIn("ENEMY TEAM", a.sides["enemy"].title.cget("text"))
            self.assertEqual(len([s for s in a.sides["enemy"].row_sids if s]), 1)
            self.assertIn("Duel", a.hidden_columns)  # no duels yet
            self.assertNotIn("Player", a.hidden_columns)
        Game().play(script)

    def test_the_window_can_be_dragged_to_any_size(self):
        def script(g):
            a = g.app
            g.on_screen_thread(lambda: a.set_visible(True))
            g.on_screen_thread(lambda: a.show_page("Players"))
            time.sleep(0.3)
            press = type("E", (), {"x_root": 0, "y_root": 0})
            g.on_screen_thread(lambda: a._resize_start(press))
            for size in ((340, 230), (900, 700), (500, 300)):
                drag = type("E", (), {"x_root": size[0] - a.resizing[2], "y_root": size[1] - a.resizing[3]})
                g.on_screen_thread(lambda: a._resize_move(drag))
                g.on_screen_thread(lambda: a.root.update())
                time.sleep(0.3)
                self.assertEqual((a.root.winfo_width(), a.root.winfo_height()), size)
                if size == (900, 700):  # big again after small: every player is back on screen
                    time.sleep(0.5)
                    self.assertEqual(shown_rows(a), len(a.players))
            g.on_screen_thread(lambda: a._resize_move(type("E", (), {"x_root": -9999, "y_root": -9999})))
            time.sleep(0.2)
            g.on_screen_thread(lambda: a.root.update())
            self.assertEqual((a.root.winfo_width(), a.root.winfo_height()), a.MIN_SIZE)
            self.assertTrue(g.on_screen_thread(a.table.winfo_manager))  # the list is still there
            g.on_screen_thread(a.fit_to_contents)
            g.on_screen_thread(lambda: a.root.update())
            self.assertFalse(a.sized())
            self.assertGreater(a.root.winfo_height(), a.MIN_SIZE[1])
        Game().play(script)

    def test_rows_show_an_avatar_a_health_bar_and_one_kd_column(self):
        def script(g):
            a = g.app
            other = next(sid for sid in a.players if sid != ME)
            a.board[other] = {"m_iScore": "12", "m_iDeaths": "9", "m_iHealth": "150", "m_bAlive": "true"}
            a.classes[other] = "Heavy"

            def cells():
                return dict(zip(screens.COLUMNS, g.on_screen_thread(lambda: a.row_cells(a.players[other]))))
            row = cells()
            self.assertEqual(row["K/D"][0], "12/9")
            self.assertEqual(row["HP"][0], "150")
            bar = row["HP"][2]
            self.assertEqual((bar.width(), bar.height()), screens.HP_BAR)
            self.assertIs(cells()["HP"][2], bar)  # drawn once, then reused
            self.assertIsNone(row["Player"][2])    # no avatar yet
            with tempfile.TemporaryDirectory() as folder:
                path = os.path.join(folder, "avatar.png")
                g.on_screen_thread(lambda: tk.PhotoImage(width=18, height=18).write(path, format="png"))
                g.on_screen_thread(lambda: a.handle_event(("avatar", other, path)))
            self.assertIs(cells()["Player"][2], a.avatar_images[other])
            g.on_screen_thread(lambda: (a.set_visible(True), a.render()))  # and the list draws with them
        Game().play(script)

    def test_avatars_only_come_from_steams_picture_server(self):
        events = queue.Queue()
        lookups.download_avatar(1, "https://example.com/abc123.jpg", events)
        lookups.download_avatar(1, "http://avatars.steamstatic.com/abc123.jpg", events)  # not https
        lookups.download_avatar(1, "https://evilsteamstatic.com/abc123.jpg", events)
        self.assertTrue(events.empty())

    def test_the_duels_page_shows_running_duels_and_stops_them(self):
        def script(g):
            a = g.app
            self.assertEqual(a.ai_button.title.cget("text"), "Duels")
            self.assertFalse(g.on_screen_thread(a.heavy_cards.winfo_manager))  # no HoovyGPT settings
            g.on_screen_thread(lambda: (a.set_visible(True), a.show_page("HoovyGPT")))  # a saved page from before
            self.assertEqual(a.cfg["page"], "Duels")
            self.assertEqual(a.duels_label.cget("text"), "No duels running.")
            g.say("dan", "!duel Hank", 0.8)
            self.assertTrue(a.chat_duels)
            g.on_screen_thread(a.render)
            self.assertEqual(a.duels_label.cget("text"), "dan 0-0 Hank")
            g.on_screen_thread(a.stop_duels_from_page)
            self.assertFalse(a.chat_duels)
            g.on_screen_thread(a.render)
            self.assertEqual(a.duels_label.cget("text"), "No duels running.")
            g.on_screen_thread(lambda: a.show_page("Players"))
        Game(heavy_talks=False, duels_on=True).play(script)

    def test_hoovygpts_settings_are_only_there_while_it_may_talk(self):
        def script(g):
            a = g.app
            self.assertEqual(a.ai_button.title.cget("text"), "HoovyGPT + Duels")
            self.assertTrue(g.on_screen_thread(a.heavy_cards.winfo_manager))
        Game(heavy_talks=True).play(script)

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
            g.on_screen_thread(lambda: (a.set_visible(True), a.render()))
            health = {name: (level, text) for name, level, text in g.on_screen_thread(a.feature_health)}
            self.assertEqual(health["Duels"], ("off", "off: switch them on on the Duels page"))
            self.assertEqual(health["!speak"], ("off", "off: switch it on on the Chat page"))
            self.assertEqual(health["Translator"][0], "warn")
            self.assertIn("Google resting until", health["Translator"][1])
            self.assertEqual(health["Cheat check"][0], "bad")
            light, label = a.health_rows["Cheat check"]
            self.assertEqual((light.cget("fg"), label.cget("text")), (screens.BAD, a.demo_state))
            for service in tf2_translator.TRANSLATORS:
                tf2_translator.resting_until[service] = time.time() + 600
            self.assertEqual(tf2_translator.translator_health()[0], "bad")
        Game().play(script)

    def test_players_are_not_remembered_across_matches(self):
        def script(g):
            a = g.app
            hank = next(sid for sid, p in a.players.items() if p.name == "Hank")
            g.on_screen_thread(lambda: (a.set_visible(True), a.select(hank)))
            time.sleep(0.4)
            self.assertFalse(hasattr(a, "seen"))
            self.assertFalse(hasattr(a, "seen_label"))
            self.assertNotIn("Player memory", screens.HEALTH_ROWS)
        Game().play(script)

    def test_a_strip_under_each_team_sums_it_up(self):
        def script(g):
            a = g.app
            sids = list(a.players)
            for sid, team in zip(sids, ("TF_GC_TEAM_DEFENDERS", "TF_GC_TEAM_DEFENDERS", "TF_GC_TEAM_INVADERS")):
                a.lobby_team[sid] = team
            a.classes.update({sids[0]: "Medic", sids[1]: "Medic", sids[2]: "Sniper"})
            a.players[sids[0]].hours, a.players[sids[1]].hours, a.players[sids[2]].hours = 1000, 2000, None
            a.flags[sids[2]] = [(1, "new account")]
            a.reevaluate = lambda: None
            g.on_screen_thread(lambda: (a.set_visible(True), a.render()))
            self.assertEqual(a.sides["mine"].strip.cget("text"), "2 Medic · average 1,500 hours")
            self.assertEqual(a.sides["enemy"].strip.cget("text"), "1 Sniper · 1 new account")
            self.assertTrue(g.on_screen_thread(a.sides["mine"].strip.winfo_manager))
            a.classes.clear()
            for sid in sids:
                a.players[sid].hours = None
            a.flags[sids[2]] = []
            g.on_screen_thread(a.render)
            self.assertFalse(g.on_screen_thread(a.sides["mine"].strip.winfo_manager))  # nothing known: no line
        Game().play(script)

    def test_columns_can_be_switched_on_and_off(self):
        def script(g):
            a = g.app
            g.on_screen_thread(lambda: a.set_visible(True))
            self.assertIn("Ctry", a.cfg["columns"])
            self.assertNotIn("Streak", a.cfg["columns"])  # off until you pick it
            g.on_screen_thread(lambda: a.toggle_column("Class"))
            self.assertNotIn("Class", a.cfg["columns"])
            self.assertIn("Class", a.hidden_columns)
            self.assertNotIn("Player", a.hidden_columns)  # the name always shows
            g.on_screen_thread(lambda: a.toggle_column("Class"))
            g.on_screen_thread(lambda: a.toggle_column("Streak"))
            self.assertEqual([c for c in a.cfg["columns"] if c in ("Class", "Streak")], ["Class", "Streak"])
            g.on_screen_thread(a.show_column_menu)  # the Columns button
            menu = a.column_menu
            ticked = {menu.entrycget(i, "label") for i in range(menu.index("end") + 1)
                      if a.column_vars[screens.PICKABLE_COLUMNS[i]].get()}
            self.assertIn("Streak", ticked)
            self.assertIn("Country", ticked)
            self.assertNotIn("Age", ticked)
        Game().play(script)

    def test_the_left_and_top_edges_resize_too(self):
        def script(g):
            a = g.app
            g.on_screen_thread(lambda: a.set_visible(True))
            g.on_screen_thread(lambda: a.show_page("Players"))
            time.sleep(0.3)

            def box():
                r = a.root
                return g.on_screen_thread(lambda: (r.winfo_x(), r.winfo_y(), r.winfo_width(), r.winfo_height()))

            def drag(mode, dx, dy):
                g.on_screen_thread(lambda: a._resize_start(type("E", (), {"x_root": 0, "y_root": 0})))
                g.on_screen_thread(lambda: a._resize_move(type("E", (), {"x_root": dx, "y_root": dy}), mode))
                time.sleep(0.2)
                g.on_screen_thread(lambda: (a._resize_end(None), a.root.update()))
                return box()

            drag("se", 300, 200)  # a set size to start from
            x, y, w, h = box()
            self.assertEqual(drag("w", -120, 0), (x - 120, y, w + 120, h))   # left edge out: right edge stays
            self.assertEqual(drag("n", 0, -60), (x - 120, y - 60, w + 120, h + 60))  # top edge up: bottom stays
            self.assertEqual(drag("nw", 120, 60), (x, y, w, h))              # the corner undoes both
            self.assertEqual(a.cfg["x"], x)  # where it is now is remembered
            x2, y2, w2, h2 = drag("w", 9999, 0)  # too far: it stops at its smallest, right edge still put
            self.assertEqual((w2, x2 + w2), (a.MIN_SIZE[0], x + w))
        Game().play(script)

    def test_maximize_fills_the_screen_and_goes_back(self):
        def script(g):
            a = g.app
            g.on_screen_thread(lambda: a.set_visible(True))
            area = (-5000, -5000, 900, 600)  # a pretend screen, off every real one: nothing shows
            real, screens.work_area = screens.work_area, lambda window: area
            self.addCleanup(setattr, screens, "work_area", real)
            before = g.on_screen_thread(lambda: (a.root.winfo_x(), a.root.winfo_y()))
            g.on_screen_thread(a.toggle_maximized)
            g.on_screen_thread(lambda: a.root.update())
            self.assertEqual(g.on_screen_thread(lambda: (a.root.winfo_x(), a.root.winfo_y(),
                                                         a.root.winfo_width(), a.root.winfo_height())), area)
            self.assertEqual(a.maximize_button.cget("text"), "")
            g.on_screen_thread(a.toggle_maximized)
            g.on_screen_thread(lambda: a.root.update())
            self.assertEqual(g.on_screen_thread(lambda: (a.root.winfo_x(), a.root.winfo_y())), before)
        Game().play(script)

    def test_long_flags_are_cut_short_in_the_list(self):
        text, _ = screens.short_cell("Flags", ("1 server ban: Exploiting/Teleporting spies into base (BlackWonder)  +1", "r"))
        self.assertLessEqual(len(text), screens.FLAGS_CELL_CHARS)
        self.assertTrue(text.endswith("…  +1"))
        self.assertEqual(screens.short_cell("Player", ("x" * 60, "r")), ("x" * 60, "r"))

    def test_a_small_window_shows_fewer_rows_and_scrolls(self):
        def script(g):
            a = g.app
            g.on_screen_thread(lambda: a.set_visible(True))
            g.on_screen_thread(lambda: a.show_page("Players"))
            a.cfg["scanner_width"], a.cfg["scanner_height"] = 500, 300
            g.on_screen_thread(a.show_body)
            for _ in range(4):
                g.on_screen_thread(lambda: (a.root.update(), a.render()))
                time.sleep(0.2)
            shown = shown_rows(a)
            self.assertGreaterEqual(shown, 1)
            self.assertLessEqual(shown, len(a.players))
        Game().play(script)

    def test_a_status_light_shows_how_a_connection_is_doing(self):
        for state, colour in (("connected", screens.GOOD), ("ok", screens.GOOD), ("24 cheaters known", screens.GOOD),
                              ("loading", screens.WAITING), ("not connected", screens.WAITING),
                              ("no key", screens.FAINT), ("wrong password", screens.BAD)):
            self.assertEqual(screens.status_colour(state), colour, state)

    def test_selecting_a_flagged_player_shows_why(self):
        def script(g):
            a = g.app
            flagged = next(sid for sid in a.players if sid != ME)
            a.flags[flagged] = [(3, "1 VAC ban (2d ago)")]
            a.reevaluate = lambda: None  # keep the flag above from being worked out again
            g.on_screen_thread(lambda: a.set_visible(True))  # a hidden list isn't drawn
            g.on_screen_thread(lambda: a.select(flagged))
            time.sleep(0.4)
            text = a.why_label.cget("text")
            self.assertIn("[proven] 1 VAC ban (2d ago)", text)
            self.assertTrue(g.on_screen_thread(a.why_label.winfo_manager))
            g.on_screen_thread(lambda: a.select(flagged))  # clicking again deselects
            time.sleep(0.4)
            self.assertEqual(a.why_label.cget("text"), "")
        Game().play(script)

    def test_tokens_window_is_a_normal_window_that_closes_with_its_x(self):
        def script(g):
            a, panel = g.app, g.app.token_panel
            self.assertEqual(panel.win.state(), "withdrawn")
            g.on_screen_thread(a.toggle_token_panel)
            time.sleep(0.2)
            self.assertEqual(panel.win.state(), "normal")
            self.assertFalse(panel.win.attributes("-topmost"))
            self.assertFalse(panel.win.overrideredirect())
            self.assertIn("TOKENS TODAY", panel.label.cget("text"))
            g.on_screen_thread(a.toggle_token_panel)  # what its X does
            time.sleep(0.2)
            self.assertEqual(panel.win.state(), "withdrawn")
            self.assertFalse(a.cfg["token_panel"])
        Game().play(script)


if __name__ == "__main__":
    unittest.main()
