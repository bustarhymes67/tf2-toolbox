"""The setup wizard, run against a fake Steam config with scripted answers: never your real Steam,
browser, keys or network."""
import builtins
import hashlib
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import settings  # noqa: E402
import tf2_setup  # noqa: E402

VDF = '''"UserLocalConfigStore"
{
\t"Software"
\t{
\t\t"Valve"
\t\t{
\t\t\t"Steam"
\t\t\t{
\t\t\t\t"apps"
\t\t\t\t{
\t\t\t\t\t"440"
\t\t\t\t\t{
\t\t\t\t\t\t"LaunchOptions"\t\t"-novid"
\t\t\t\t\t}
\t\t\t\t}
\t\t\t}
\t\t}
\t}
}
'''
GEMINI = "AIza" + "x" * 35
GROQ = "gsk_" + "y" * 40
STEAM = "0123456789ABCDEF0123456789ABCDEF"
DEEPL = "12345678-abcd-4bcd-8bcd-123456789abc:fx"


class FakeDownload(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class SetupWizardTest(unittest.TestCase):
    def run_wizard(self, answers, argv=(), download=b"the real program", scanner_on=False, **cfg_changes):
        tmp = tempfile.mkdtemp()
        vdf = os.path.join(tmp, "localconfig.vdf")
        with open(vdf, "w", encoding="utf-8") as f:
            f.write(VDF)
        cfg = dict(settings.DEFAULTS, rcon_password="abc123", **cfg_changes)
        saved, opened, started = [], [], []
        answers = iter(answers)
        tool = os.path.join(tmp, "tools", "demo-analysis.exe")
        patches = [
            mock.patch.object(builtins, "input", lambda prompt="": next(answers)),
            mock.patch.object(tf2_setup.scanner, "load_config", lambda: cfg),
            mock.patch.object(tf2_setup.scanner, "save_config", lambda c: saved.append(dict(c))),
            mock.patch.object(tf2_setup, "steam_running", lambda: False),
            mock.patch.object(tf2_setup, "scanner_running", lambda: scanner_on),
            mock.patch.object(tf2_setup, "config_files", lambda: [vdf]),
            mock.patch.object(tf2_setup.webbrowser, "open", opened.append),
            mock.patch.object(tf2_setup.urllib.request, "urlopen", lambda url, timeout: FakeDownload(download)),
            mock.patch.object(tf2_setup, "DEMO_TOOL", tool),
            mock.patch.object(tf2_setup, "DEMO_TOOL_SHA256", hashlib.sha256(b"the real program").hexdigest()),
            mock.patch.object(tf2_setup.os, "startfile", started.append, create=True),
            mock.patch.object(tf2_setup.subprocess, "Popen", lambda args: started.append(args)),
            mock.patch.object(sys, "argv", ["tf2_setup.py", *argv]),
        ]
        for p in patches:
            p.start()
        try:
            out = io.StringIO()
            with redirect_stdout(out):
                tf2_setup.main()
        finally:
            for p in patches:
                p.stop()
        with open(vdf, encoding="utf-8") as f:
            options = [line for line in f if "LaunchOptions" in line][0]
        return cfg, options, opened, started, os.path.exists(tool), out.getvalue()

    def test_everything_yes(self):
        cfg, options, opened, started, tool, out = self.run_wizard(
            ["",            # set up the cheat check: Y
             "", STEAM,     # Steam key: open page, paste
             "", "",        # steamhistory: open page, skip
             "", GEMINI,    # Gemini (asked without a yes/no first)
             "", GROQ,      # Groq
             "", DEEPL,     # DeepL
             ""])           # start TF2 and the scanner: Y
        self.assertTrue(tool)
        self.assertIn("-novid", options)  # your own options stay
        self.assertIn("-condebug", options)
        self.assertIn("+ds_enable 0", options)  # record_only_flagged: TF2 records when the scanner says ds_record
        self.assertNotIn("+ds_enable 2", options)
        self.assertEqual((cfg["steam_api_key"], cfg["steamhistory_api_key"]), (STEAM, ""))
        self.assertEqual((cfg["gemini_api_key"], cfg["groq_api_key"]), (GEMINI, GROQ))
        self.assertTrue(cfg["heavy_talks"])
        self.assertEqual(cfg["deepl_api_key"], DEEPL)
        self.assertTrue(cfg["demo_check"])
        self.assertEqual(opened, ["https://steamcommunity.com/dev/apikey", "https://steamhistory.net/account#developer",
                                  "https://aistudio.google.com/api-keys", "https://console.groq.com/keys",
                                  "https://www.deepl.com/pro-api"])
        self.assertIn("steam://rungameid/440", started)
        self.assertNotIn("abc123", out)  # the RCON password is never shown

    def test_everything_no(self):
        cfg, options, opened, started, tool, out = self.run_wizard(
            ["n", "", "", "", "", "", "", "", "", "", "", "n"])
        self.assertFalse(tool)
        self.assertNotIn("ds_enable", options)
        self.assertIn("-condebug", options)
        self.assertFalse(cfg["heavy_talks"])
        self.assertFalse(cfg["demo_check"])
        self.assertEqual(started, [])

    def test_a_wrong_download_is_not_saved(self):
        cfg, options, _, _, tool, out = self.run_wizard(
            ["", "", "", "", "", "", "", "", "", "", "", "n"], download=b"something else")
        self.assertFalse(tool)
        self.assertNotIn("ds_enable", options)  # no recording without the program that reads it
        self.assertIn("NOT saved", out)

    def test_recording_every_match_when_record_only_flagged_is_off(self):
        cfg, options, *_ = self.run_wizard(["", "", "", "", "", "", "", "", "", "", "", "n"], record_only_flagged=False)
        self.assertIn("+ds_enable 2", options)
        self.assertNotIn("+ds_enable 0", options)

    def test_a_wrong_paste_is_caught(self):
        cfg, *_ = self.run_wizard(
            ["n", "", "my password", "n", STEAM, "", "", "", "", "", "", "", "", "n"])
        self.assertEqual(cfg["steam_api_key"], STEAM)

    def test_a_running_scanner_isnt_started_twice(self):
        cfg, options, opened, started, tool, out = self.run_wizard(
            ["n", "", "", "", "", "", "", "", "", "", "", "n"], scanner_on=True)
        self.assertEqual(started, [])  # "Start TF2 now?" was answered no; no second scanner either
        self.assertIn("already running", out)
        self.assertIn("picks up the new keys", out)


if __name__ == "__main__":
    unittest.main()
