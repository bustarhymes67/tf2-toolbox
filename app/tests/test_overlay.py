"""The translation overlay's Russian only / All languages buttons, and what each lets through."""
import queue
import threading
import time
import tkinter as tk
import unittest

import helpers  # noqa: F401  (also points the overlay's settings file at a temp folder)
import tf2_translator


class LanguageModeTest(unittest.TestCase):
    def worker_sees(self, mode, lines):
        """What the translator asks Google about, for these chat lines, in this mode."""
        asked = []

        def fake(text, target):
            asked.append(text)
            return "translated", "xx"
        real, tf2_translator.translate_chat = tf2_translator.translate_chat, fake
        cfg = dict(tf2_translator.DEFAULTS, languages=mode)
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
        self.assertTrue(tf2_translator.CONFIG_PATH.startswith(helpers._TEST_FILES))  # never your real settings
        root = tk.Tk()
        root.withdraw()
        real_on_screen, tf2_translator.on_screen = tf2_translator.on_screen, lambda x, y: True
        try:
            cfg = dict(tf2_translator.DEFAULTS, x=-5000, y=-5000)  # off every screen
            overlay = tf2_translator.Overlay(cfg, root)
            overlay.toggle()  # unlocked (F8): the buttons show
            root.update()
            tags = {t for item in overlay.canvas.find_all() for t in overlay.canvas.gettags(item)}
            self.assertLessEqual({"mode_russian", "mode_all"}, tags)
            overlay.set_languages("russian")
            self.assertEqual(cfg["languages"], "russian")
            self.assertEqual(tf2_translator.load_config()["languages"], "russian")  # saved
            overlay.set_languages("all")
            self.assertEqual(tf2_translator.load_config()["languages"], "all")
        finally:
            tf2_translator.on_screen = real_on_screen
            root.destroy()

    def test_the_old_switch_becomes_russian_only(self):
        with open(tf2_translator.CONFIG_PATH, "w") as f:
            f.write('{"only_cyrillic": true}')
        cfg = tf2_translator.load_config()
        self.assertEqual(cfg["languages"], "russian")
        self.assertNotIn("only_cyrillic", cfg)


if __name__ == "__main__":
    unittest.main()
