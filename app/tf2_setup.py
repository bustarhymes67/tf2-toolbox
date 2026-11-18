"""One-time setup for TF2 Toolbox: a guided wizard in the console window.

1. Closes Steam (after asking) and sets TF2's launch options. Steam must be closed,
   because it rewrites its config file when it exits. A backup of the file is kept.
2. Walks through each free API key: says what to click, opens the page, and saves the
   pasted key (keys go to the secrets file, never into this folder).
3. Switches HoovyGPT on if you want it, then offers to start TF2 and the scanner.

Run:  python tf2_setup.py                   (everything)
      python tf2_setup.py --launch-options  (step 1 only)
      python tf2_setup.py --keys            (steps 2 and 3 only)
"""

import ctypes
import glob
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser
import winreg

import tf2_lobby_scanner as scanner

STEAM_USERDATA = r"C:\Program Files (x86)\Steam\userdata"
APP_PATH = ["userlocalconfigstore", "software", "valve", "steam", "apps", "440"]

# Flags this tool manages, with how many arguments each one takes.
OUR_FLAGS = {"-condebug": 0, "-conclearlog": 0, "-g15": 0, "-usercon": 0, "+ip": 1, "+rcon_password": 1,
             "+hostport": 1, "+net_start": 0, "+ds_enable": 1}

KEY_LINE_RE = re.compile(r'^\s*"((?:[^"\\]|\\.)*)"\s*$')
KEY_VALUE_RE = re.compile(r'^(\s*)"((?:[^"\\]|\\.)*)"(\s+)"((?:[^"\\]|\\.)*)"\s*$')


def steam_running():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq steam.exe", "/NH"],
                         capture_output=True, text=True).stdout
    return "steam.exe" in out.lower()


def merge_options(existing, ours):
    """Keeps the user's own launch options, replacing only the ones we manage."""
    tokens, kept, i = existing.split(), [], 0
    while i < len(tokens):
        if tokens[i].lower() in OUR_FLAGS:
            i += 1 + OUR_FLAGS[tokens[i].lower()]
        else:
            kept.append(tokens[i])
            i += 1
    return " ".join(kept + [ours])


def set_launch_options(path, ours):
    """Edits TF2's LaunchOptions in a localconfig.vdf. Returns (old, new)."""
    with open(path, encoding="utf-8", newline="") as f:
        text = f.read()
    eol = "\r\n" if "\r\n" in text else "\n"  # keep Steam's own line endings
    lines = text.split(eol)
    stack, pending, old = [], None, None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "{":
            stack.append(pending)
        elif stripped == "}":
            if stack == APP_PATH:
                # Block ended without LaunchOptions: add it.
                new = merge_options("", ours)
                lines.insert(i, "\t" * len(stack) + f'"LaunchOptions"\t\t"{new}"')
                break
            stack.pop()
        elif m := KEY_VALUE_RE.match(line):
            if stack == APP_PATH and m.group(2).lower() == "launchoptions":
                old = m.group(4)
                new = merge_options(old, ours)
                lines[i] = f'{m.group(1)}"{m.group(2)}"{m.group(3)}"{new}"'
                break
        elif m := KEY_LINE_RE.match(line):
            pending = m.group(1).lower()
    else:
        raise LookupError("TF2's entry wasn't found in Steam's config. Launch TF2 once, then retry.")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(eol.join(lines))
    return old, new


def config_files():
    me = scanner.my_steamid()
    if me:
        path = os.path.join(STEAM_USERDATA, str(me - scanner.STEAM64_BASE), "config", "localconfig.vdf")
        if os.path.exists(path):
            return [path]
    return glob.glob(os.path.join(STEAM_USERDATA, "*", "config", "localconfig.vdf"))


def steam_exe():
    """Steam's own steam.exe, from the registry, else the usual place."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            path = winreg.QueryValueEx(key, "SteamExe")[0]
            if os.path.exists(path):
                return os.path.normpath(path)
    except OSError:
        pass
    path = r"C:\Program Files (x86)\Steam\steam.exe"
    return path if os.path.exists(path) else None


def ask_yes(question, default=True):
    """A yes/no question; Enter takes the default."""
    hint = "[Y/n]" if default else "[y/N]"
    while True:
        answer = input(f"{question} {hint} ").strip().lower()
        if not answer:
            return default
        if answer in ("y", "yes", "n", "no"):
            return answer.startswith("y")
        print("  Type y or n.")


def close_steam():
    """Asks Steam to quit (as Steam > Exit does) and waits until it's gone. False if it's still running."""
    exe = steam_exe()
    if not exe:
        return False
    print("  Closing Steam...", end="", flush=True)
    subprocess.Popen([exe, "-shutdown"])
    for _ in range(60):
        time.sleep(1)
        print(".", end="", flush=True)
        if not steam_running():
            print(" closed.")
            time.sleep(2)  # Steam writes its config files as it exits
            return True
    print(" still running.")
    return False


# The live cheat check's program: Nocrex's demo-analysis, the official v3 release (GPL-3.0),
# checked against the SHA-256 that GitHub publishes for it.
DEMO_TOOL_URL = "https://github.com/Nocrex/demo-analysis/releases/download/v3/cli.exe"
DEMO_TOOL_SHA256 = "29ff97518c324276f979fcdbcb94c24853f1e117bfdfc68d0af589a5d24f70db"
DEMO_TOOL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools", "demo-analysis.exe")


def install_demo_tool():
    """Downloads demo-analysis into tools/ unless it's already there. True when it's there."""
    if os.path.exists(DEMO_TOOL):
        print("demo-analysis is already installed.")
        return True
    print(f"Downloading demo-analysis (4 MB) from {DEMO_TOOL_URL} ...")
    try:
        with urllib.request.urlopen(DEMO_TOOL_URL, timeout=60) as r:
            data = r.read()
    except OSError as e:
        print(f"Download failed ({e}). Run '1 - Install.bat' again later, or see app/tools/README.md.")
        return False
    if hashlib.sha256(data).hexdigest() != DEMO_TOOL_SHA256:
        print("The download isn't the expected file, so it was NOT saved. See tools/README.md.")
        return False
    os.makedirs(os.path.dirname(DEMO_TOOL), exist_ok=True)
    with open(DEMO_TOOL, "wb") as f:
        f.write(data)
    print("Installed (checksum OK).")
    return True


def record_mode(cfg):
    """TF2's ds_enable for the cheat check: 0 (only when the scanner says ds_record) while
    record_only_flagged is on, else 2 (every match)."""
    return 0 if cfg.get("record_only_flagged", True) else 2


def setup_launch_options(cfg, record_demos=False):
    while steam_running():
        print("Steam is running. It must be closed to change the launch options.")
        if ask_yes("Close Steam now?") and close_steam():
            break
        print("Close Steam yourself: right-click the Steam icon near the clock, click Exit.")
        if not ask_yes("Try again?"):
            print("Launch options were NOT changed. Run '1 - Install.bat' again later.")
            return False
    paths = config_files()
    if not paths:
        print("Steam's config wasn't found. Start TF2 one time, then run '1 - Install.bat' again.")
        return False
    # The cheat check reads the demos TF2 records. ds_enable 0: TF2 records only when told to (the
    # scanner types ds_record while a flagged player is in the match, record_only_flagged);
    # ds_enable 2: TF2 records every match by itself.
    ours = scanner.launch_options(cfg) + (f" +ds_enable {record_mode(cfg)}" if record_demos else "")
    for path in paths:
        backup = f"{path}.backup-{time.strftime('%Y%m%d-%H%M%S')}"
        shutil.copy2(path, backup)
        try:
            old, _ = set_launch_options(path, ours)
        except LookupError as e:
            print(e)
            return False
        old = re.sub(r"(\+rcon_password )\S+", r"\1<hidden>", old or "empty")
        print(f"TF2 launch options set (they were: {old}).")
        print(f"  Backup of Steam's config: {backup}")
    return True


# What a key of each kind looks like, to catch a wrong paste (a warning only).
KEY_SHAPES = {"steam_api_key": re.compile(r"^[0-9A-Fa-f]{32}$"),
              "gemini_api_key": re.compile(r"^AIza[\w-]{30,}$"),
              "groq_api_key": re.compile(r"^gsk_\w{20,}$"),
              "deepl_api_key": re.compile(r"^[0-9a-fA-F-]{36}(:fx)?$")}


def ask_key(cfg, field, title, url, steps):
    """Says what to click, opens the page, and saves the pasted key. True if a key is set."""
    print(f"\n--- {title} ---")
    if cfg[field]:
        print("Already set.")
        if not ask_yes("Replace it?", default=False):
            return True
    for i, text in enumerate(steps, 1):
        print(f"  {i}. {text}")
    input("Press Enter to open the page in your browser...")
    webbrowser.open(url)
    print(f"  (If no page opened, go to {url})")
    while True:
        key = input("Paste the key here, then press Enter (or just press Enter to skip): ").strip().strip('"')
        if not key:
            print("Skipped.")
            return bool(cfg[field])
        shape = KEY_SHAPES.get(field)
        if shape and not shape.match(key) and not ask_yes("That doesn't look like this kind of key. Save it anyway?", False):
            continue
        cfg[field] = key
        scanner.save_config(cfg)  # keys go to the secrets file, never into scanner_config.json
        print("Saved.")
        return True


def scanner_running():
    """True while TF2 Toolbox runs (it holds this name for as long as it runs)."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenMutexW.restype = ctypes.c_void_p
    handle = kernel32.OpenMutexW(0x00100000, False, "tf2_lobby_scanner")  # SYNCHRONIZE
    if handle:
        kernel32.CloseHandle(ctypes.c_void_p(handle))
    return bool(handle)


def pythonw():
    """pythonw.exe next to the Python running this, so it works right after Python was installed
    (before Windows has put Python on the PATH)."""
    path = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return path if os.path.exists(path) else "pythonw"


def step(n, total, title):
    print(f"\n==================== Step {n} of {total}: {title} ====================")


def main():
    cfg = scanner.load_config()
    keys_only, options_only = "--keys" in sys.argv, "--launch-options" in sys.argv
    total = 1 if options_only else 3 if keys_only else 6
    print("TF2 Toolbox setup. Each step says what to do.")
    print("For a [Y/n] question, press Enter for the answer in capitals.")
    n = 0
    if not keys_only:
        record_demos = False
        if not options_only:
            n += 1
            step(n, total, "Cheat check (recommended)")
            print("The cheat check reads the demo TF2 records and looks for aimbots and the like.")
            print("TF2 records only while someone flagged is in your match, so clean matches never fill your disk.")
            print("It uses demo-analysis, a free open-source program (github.com/Nocrex/demo-analysis).")
            print("Demos with nothing found are deleted afterwards, so they don't fill your disk.")
            if ask_yes("Set up the cheat check?"):
                record_demos = install_demo_tool()
            cfg["demo_check"] = record_demos
            scanner.save_config(cfg)
        else:
            record_demos = cfg["demo_check"] and os.path.exists(DEMO_TOOL)
        n += 1
        step(n, total, "TF2 launch options")
        print("This lets the scanner read TF2's console and talk to TF2. It changes only the launch options.")
        setup_launch_options(cfg, record_demos)
    if options_only:
        return

    n += 1
    step(n, total, "Player information (free, optional)")
    print("These two keys let the scanner see hours, account age and bans. Without them it still works.")
    ask_key(cfg, "steam_api_key", "Steam API key", "https://steamcommunity.com/dev/apikey",
            ["Log in to Steam on the page, if it asks.",
             "In 'Domain Name', type: localhost",
             "Tick the box to agree, then click Register.",
             "Copy the long code after 'Key:'."])
    ask_key(cfg, "steamhistory_api_key", "steamhistory.net key", "https://steamhistory.net/account#developer",
            ["Log in with Steam on the page.",
             "In the Developer section, make an API key.",
             "Copy the key."])

    n += 1
    step(n, total, "HoovyGPT, the AI chat bot (free, optional)")
    print("HoovyGPT answers other players in chat as the Heavy, from your account.")
    print("It uses Gemini first, and Groq as the backup when Gemini is slow or out of free answers.")
    print("Without these keys, everything else still works. To skip a key, press Enter without one.")
    gemini = ask_key(cfg, "gemini_api_key", "Gemini API key (main)", "https://aistudio.google.com/api-keys",
                     ["Log in with a Google account.", "Click 'Create API key'.",
                      "Copy the key (it starts with AIza)."])
    groq = ask_key(cfg, "groq_api_key", "Groq API key (backup)", "https://console.groq.com/keys",
                   ["Log in (Google, GitHub or e-mail).", "Click 'Create API Key'. Give it any name.",
                    "Copy the key (it starts with gsk_). Groq shows it only once."])
    if gemini or groq:
        cfg["heavy_talks"] = True
        scanner.save_config(cfg)
        print("\nHoovyGPT is ready. In the scanner, open the Duels page and click 'HoovyGPT + Duels'"
              " to switch it on. It starts off each time, so it never talks by surprise.")
    else:
        print("No AI key was saved, so HoovyGPT stays off. Run '1 - Install.bat' again to add one.")

    n += 1
    step(n, total, "Chat translation backups (free, optional)")
    print("Chat is translated by Google first, with no key. When Google says 'too many requests'")
    print("(a busy lobby), DeepL takes over, then Microsoft Translator. Without these keys the")
    print("translator falls back to MyMemory, which is weaker. Both sites ask for a card to check")
    print("you're a person, but their free plans never charge it.")
    ask_key(cfg, "deepl_api_key", "DeepL API key (first backup)", "https://www.deepl.com/pro-api",
            ["Sign up for 'DeepL API Free' (500,000 characters a month, free).",
             "Then open https://www.deepl.com/your-account/keys",
             "Copy the key (it ends with :fx)."])
    if ask_key(cfg, "microsoft_translator_key", "Microsoft Translator key (second backup)",
               "https://portal.azure.com/#create/Microsoft.CognitiveServicesTextTranslation",
               ["Log in with a Microsoft account (make a free Azure account if it asks).",
                "Resource group: 'Create new', any name. Region: Global. Name: anything.",
                "Pricing tier: 'F0 (Free)' (2 million characters a month). Click 'Review + create', then 'Create'.",
                "Click 'Go to resource', then 'Keys and Endpoint' on the left.",
                "Copy 'KEY 1'."]):
        region = input("The Region you picked (press Enter for Global): ").strip()
        cfg["microsoft_translator_region"] = "" if region.lower() in ("", "global") else region
        scanner.save_config(cfg)

    if keys_only:
        return
    n += 1
    step(n, total, "Done")
    print("Set TF2 to Windowed or Fullscreen Windowed (TF2: Options > Video), or the player list can't show over it.")
    if scanner_running():
        print("TF2 Toolbox is already running. It picks up the new keys by itself within a few seconds.")
        if ask_yes("Start TF2 now?"):
            os.startfile("steam://rungameid/440")
        return
    if ask_yes("Start TF2 and the scanner now?"):
        os.startfile("steam://rungameid/440")
        subprocess.Popen([pythonw(), os.path.join(os.path.dirname(os.path.abspath(__file__)), "tf2_lobby_scanner.py")])
        print("Starting. In TF2, press F9 to show or hide the player list.")
    else:
        print("Later: start TF2, then open '2 - Start TF2 Toolbox.bat'. In TF2, press F9 for its window.")


if __name__ == "__main__":
    main()
