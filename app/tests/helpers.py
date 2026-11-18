"""Shared by the tests: a real App with fake surroundings, so nothing reaches TF2, your settings or an AI."""
import os
import queue
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ai
import chat
import duels
import game_log
import hud
import info_commands
import lookups
import player_flags
import screens
import settings
import tf2_lobby_scanner
import tf2_translator

# Every module that imports a function the tests replace: one left out keeps the real one, which is how a
# test once wrote its fake settings over your real keys and settings (info_commands.save_config).
MODULES = (settings, game_log, player_flags, lookups, chat, duels, info_commands, hud, ai, screens, tf2_lobby_scanner)

# And in case one is still missed: while the tests run, the settings and secrets files are files in a
# folder of their own, never yours. Set once, when the tests load this file.
_TEST_FILES = tempfile.mkdtemp(prefix="tf2scanner-tests-")
settings.CONFIG_PATH = os.path.join(_TEST_FILES, "scanner_config.json")
settings.SECRETS_PATH = os.path.join(_TEST_FILES, "secrets.env")
settings.OLD_TRANSLATOR_CONFIG_PATH = os.path.join(_TEST_FILES, "config.json")  # the translator's old settings too
ME = game_log.STEAM64_BASE + 1  # tomato, userid 1 in STATUS


def patch_everywhere(name, value):
    """Replaces a function in every module that imported it, and returns how to undo that."""
    old = {m: getattr(m, name) for m in MODULES if hasattr(m, name)}
    assert old, name
    for m in old:
        setattr(m, name, value)
    return lambda: [setattr(m, name, v) for m, v in old.items()]


class FakeModel:
    """Stands in for ai_answer: answers after a delay, and notes what it was asked."""

    def __init__(self, delay=0.1, answer="Is good. Heavy agrees."):
        self.delay, self.answer, self.asked, self.crash_next = delay, answer, [], False

    def __call__(self, keys, system, contents, models=None):
        self.asked.append(contents[-1]["parts"][0]["text"])
        self.last_system, self.last_parts = system, [p["text"] for p in contents[-1]["parts"]]
        time.sleep(self.delay)
        if self.crash_next:
            self.crash_next = False
            raise ValueError("model crash on purpose (this is the test, not a failure)")
        return self.answer


class Game:
    """A scanner in a match with Hank and dan, run on the main thread by play(script). The script runs
    in its own thread, as chat arrives over time; TF2 echoing the scanner's lines back is simulated."""

    STATUS = ["# userid name                uniqueid            connected ping loss state"] + [
        f'#     {a} "{n}"   [U:1:{a}]   10:00  50  0 active' for a, n in ((1, "tomato"), (2, "Hank"), (3, "dan"))]

    def __init__(self, echo=True, **settings_changes):
        self.undo = [patch_everywhere("save_config", lambda cfg: None),
                     patch_everywhere("my_steamid", lambda: ME),
                     # Keeps the window at -5000, off every screen, instead of moving it back onto one.
                     patch_everywhere("on_a_screen", lambda x, y: True),
                     # A test never reads your real keys.
                     patch_everywhere("load_secrets", lambda: {}),
                     # The old player-memory files that main() deletes: never your real ones.
                     patch_everywhere("SEEN_PATH", None),
                     patch_everywhere("FAKE_IPS_PATH", None)]
        self.model = FakeModel()
        self.undo.append(patch_everywhere("ai_answer", self.model))
        self.echo, self.sent = echo, []
        self.lines, self.events, self.toggles, self.commands, self.lookups = (queue.Queue() for _ in range(5))
        cfg = dict(settings.DEFAULTS, rcon_password="x", x=-5000, y=-5000, hud_x=-5000, hud_y=-3800, ez_mode=False,
                   announcer=False, country_beef_auto=False, gemini_api_key="k", groq_api_key="k", ai_model="auto",
                   heavy_talks=True)
        cfg.update(settings_changes)
        self.app = tf2_lobby_scanner.App(cfg, self.lines, self.events, self.toggles, self.commands, self.lookups,
                                         history=self.STATUS)
        self.app.toast.win.geometry("+-5000+-4000")
        self.app.hud.win.geometry("+-5000+-3800")  # the mini HUD too: never over your screen
        self.error = None

    def _watch_commands(self):
        while True:
            for command in list(self.commands.queue)[len(self.sent):]:
                self.sent.append(command)
                if self.echo and command.startswith(("say ", "say_team ")):
                    self.lines.put("tomato :  " + command.split(' "', 1)[1][:-1])
            time.sleep(0.02)

    def said(self):
        """The chat lines sent so far."""
        return [c.split(' "', 1)[1][:-1] for c in self.sent if c.startswith(("say ", "say_team "))]

    def say(self, name, message, wait=0.0):
        self.lines.put(f"{name} :  {message}")
        time.sleep(wait)

    def on_screen_thread(self, function):
        """Runs function on the Tk thread and waits for it, as Tk isn't safe from other threads."""
        done = threading.Event()
        result = []
        self.app.root.after(0, lambda: (result.append(function()), done.set()))
        assert done.wait(10)
        return result[0]

    def connect(self):
        """Connects and switches HoovyGPT on, with a full spam allowance."""
        self.events.put(("rcon", "connected"))
        time.sleep(0.3)
        self.app.chat_limit.tier1, self.app.chat_limit.tier2 = 4.0, 30.0
        self.app.chat_limit.talked = self.app.chat_limit.attempted = time.time() - 5
        self.app.ai_on = True  # not through the button: that would try the fake keys online
        time.sleep(0.3)
        self.sent.clear()
        self.commands.queue.clear()
        self.app.chat_unconfirmed.clear()  # the tests start counting from here
        self.app.chat_refused_count = 0

    def play(self, script):
        """Starts the app, runs script(self) next to it, closes the app, and re-raises what the script raised."""
        def run():
            try:
                time.sleep(0.5)
                self.connect()
                script(self)
            except BaseException as e:
                self.error = e
            finally:
                self.app.root.after(0, self.app.root.destroy)
        threading.Thread(target=self._watch_commands, daemon=True).start()
        threading.Thread(target=run, daemon=True).start()
        try:
            self.app.run()
        finally:
            for undo in self.undo:
                undo()
        if self.error:
            raise self.error
