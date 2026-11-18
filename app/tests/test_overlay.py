"""The translation overlay's Russian only / All languages buttons, what each lets through, and its
settings: the toolbox's translator_... ones, moved once from the old translator's config.json."""
import json
import os
import queue
import threading
import time
import tkinter as tk
import unittest

import helpers  # noqa: F401  (also points the settings files at a temp folder)
import settings
import tf2_translator


class LanguageModeTest(unittest.TestCase):
    def worker_sees(self, mode, lines):
        """What the translator asks Google about, for these chat lines, in this mode."""
        asked = []

        def fake(text, target):
            asked.append(text)
            return "translated", "xx"
        real, tf2_translator.translate_chat = tf2_translator.translate_chat, fake
        cfg = dict(settings.DEFAULTS, translator_languages=mode)
        q, results = queue.Queue(), queue.Queue()
        threading.Thread(target=tf2_translator.worker, args=(cfg, q, results), daemon=True).start()
        try:
            for line in lines:
                q.put(line)
            time.sleep(0.5)
        finally:
            tf2_translator.translate_chat = real
        return asked

    def test_russian_only_skips_every_other_language(self):
        lines = ["dan :  привет всем", "dan :  hola amigos que tal", "dan :  merhaba arkadaslar nasilsiniz"]
        self.assertEqual(self.worker_sees("russian", lines), ["привет всем"])
        self.assertEqual(len(self.worker_sees("all", lines)), 3)

    def test_the_buttons_switch_and_are_saved(self):
        root = tk.Tk()
        root.withdraw()
        real_on_screen, tf2_translator.on_screen = tf2_translator.on_screen, lambda x, y: True
        saved = []
        try:
            cfg = dict(settings.DEFAULTS, translator_x=-5000, translator_y=-5000)  # off every screen
            overlay = tf2_translator.Overlay(cfg, root, save=lambda c: saved.append(c["translator_languages"]))
            overlay.toggle()  # unlocked (F8): the buttons show
            root.update()
            tags = {t for item in overlay.canvas.find_all() for t in overlay.canvas.gettags(item)}
            self.assertLessEqual({"mode_russian", "mode_all"}, tags)
            overlay.set_languages("russian")
            self.assertEqual(cfg["translator_languages"], "russian")
            overlay.set_languages("all")
            self.assertEqual(saved, ["russian", "all"])  # saved each time
            overlay.toggle()  # locked again: where it is is kept
            self.assertEqual(cfg["translator_x"], overlay.root.winfo_x())
        finally:
            tf2_translator.on_screen = real_on_screen
            root.destroy()


class MovedSettingsTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(settings.OLD_TRANSLATOR_CONFIG_PATH.startswith(helpers._TEST_FILES))  # never your real file
        self.assertTrue(settings.CONFIG_PATH.startswith(helpers._TEST_FILES))
        self.real = settings.load_secrets
        settings.load_secrets = lambda: {"rcon_password": "x"}
        for path in (settings.CONFIG_PATH, settings.OLD_TRANSLATOR_CONFIG_PATH):
            if os.path.exists(path):
                os.remove(path)

    def tearDown(self):
        settings.load_secrets = self.real
        for path in (settings.CONFIG_PATH, settings.OLD_TRANSLATOR_CONFIG_PATH):
            if os.path.exists(path):
                os.remove(path)

    def test_the_old_translator_config_is_moved_once(self):
        with open(settings.OLD_TRANSLATOR_CONFIG_PATH, "w") as f:
            json.dump({"x": 111, "y": 222, "width": 700, "languages": "russian", "target_lang": "de",
                       "font_size": 15, "log_path": "ignored"}, f)
        real_save = settings.save_secrets
        settings.save_secrets = lambda values: None
        try:
            cfg = settings.load_config()
            self.assertEqual((cfg["translator_x"], cfg["translator_y"], cfg["translator_width"]), (111, 222, 700))
            self.assertEqual((cfg["translator_languages"], cfg["translator_target_lang"]), ("russian", "de"))
            self.assertEqual(cfg["translator_font_size"], 15)
            self.assertEqual(cfg["translator_toggle_key"], "F8")  # not in the old file: the default
            self.assertNotIn("width", cfg)
            self.assertEqual(json.load(open(settings.CONFIG_PATH))["translator_x"], 111)  # saved
            # Changed here afterwards, the old file no longer counts.
            cfg["translator_x"] = 5
            settings.save_config(cfg)
            self.assertEqual(settings.load_config()["translator_x"], 5)
            self.assertTrue(os.path.exists(settings.OLD_TRANSLATOR_CONFIG_PATH))  # your file stays
        finally:
            settings.save_secrets = real_save

    def test_without_an_old_file_the_defaults(self):
        cfg = settings.load_config()
        self.assertEqual(cfg["translator_languages"], "all")
        self.assertEqual(cfg["translator_toggle_key"], "F8")


if __name__ == "__main__":
    unittest.main()
