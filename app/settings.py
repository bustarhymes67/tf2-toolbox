"""Where the toolbox keeps its files, every setting with its default, and loading and
saving them. scanner_config.json holds your own settings, so it stays out of git. Your API keys
and the RCON password are not in this folder at all: they're in the secrets file (SECRETS_PATH)."""

import json
import os
import secrets

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "scanner_config.json")
# The settings of the translator from when it could run on its own: moved into scanner_config.json
# once (load_config), then this file is no longer read.
OLD_TRANSLATOR_CONFIG_PATH = os.path.join(HERE, "config.json")
# The API keys and the RCON password: KEY=value lines ("#" for comments), outside the project
# folder so they can't end up on GitHub by accident.
SECRETS_PATH = os.path.join(os.path.expanduser("~"), ".secrets", "tf2translator", ".env")
SECRET_KEYS = ("steam_api_key", "steamhistory_api_key", "rcon_password", "gemini_api_key", "groq_api_key",
               "deepl_api_key")
MARKS_PATH = os.path.join(HERE, "marks.json")
# Left by earlier versions, which remembered players across matches. Only used to delete them
# once at startup (tf2_lobby_scanner.forget_old_player_memory): nothing is kept past a match now.
SEEN_PATH = os.path.join(HERE, "seen_players.json")
FAKE_IPS_PATH = os.path.join(HERE, "fake_ips.json")
LISTS_CACHE_PATH = os.path.join(HERE, "lists_cache.json")
AI_LOG_PATH = os.path.join(HERE, "ai_log.txt")  # which model answered each HoovyGPT message, kept across restarts
FLAGS_DIR = os.path.join(HERE, "flags")
AVATARS_DIR = os.path.join(HERE, "avatars")  # players' Steam avatars, small
CLASS_ICONS_DIR = os.path.join(HERE, "class_icons")

# Community cheater lists in TF2 Bot Detector's format.
DEFAULT_LISTS = [
    "https://trusted.roto.lol/v1/steamids",
    "https://raw.githubusercontent.com/PazerOP/tf2_bot_detector/master/staging/cfg/playerlist.official.json",
    "https://raw.githubusercontent.com/SisterHailey/tf2bd2/main/playerlist.official.json",
    "https://raw.githubusercontent.com/incontestableness/milenko-lists/master/playerlist.milenko-cumulative.json",
    "https://raw.githubusercontent.com/joekiller/joekiller-list/main/playerlist.joekiller.json",
    "https://raw.githubusercontent.com/qfoxb/tf2bd-lists/main/playerlist.qfoxb.json",
    # Old SteamRep scammer archive: unverified, so its entries only get a yellow flag.
    "https://raw.githubusercontent.com/Newport1/Tf2BD_My_lists/main/playerlist.steamrep.json",
]
# Shorter names for list titles in flags and chat.
LIST_NAMES = {
    "Official player blacklist": "TF2BD official",
    "Milenko's cumulative list": "Milenko's",
    "joekiller-list": "joekiller's",
    "qfoxb's playerlist": "qfoxb's",
    "Historical SteamRep Banned Profiles — Suspicious": "SteamRep scammer",
}

DEFAULTS = {
    "steam_api_key": "",       # free: https://steamcommunity.com/dev/apikey
    "steamhistory_api_key": "",  # free: https://steamhistory.net/account#developer (community server bans)
    "rcon_port": 27069,
    "rcon_password": "",       # generated on first run
    "log_path": r"C:\Program Files (x86)\Steam\steamapps\common\Team Fortress 2\tf\console.log",
    "toggle_key": "F9",
    "player_filter": "all",       # who the list shows: all, flagged, cheaters or new (the chips above it)
    "scan_seconds": 10,
    "new_account_days": 90,
    "low_hours": 100,
    "headshot_min_kills": 10,     # sniper kills needed before the headshot rate is judged
    "headshot_flag_percent": 80,  # headshot rate (%) that gets flagged
    "crit_min_kills": 10,         # random-crit weapon kills needed before crit rate is judged
    "cheat_prior": 0.02,          # the cheater score's start: share of cheaters in a casual lobby (cheat_score.py)
    "ez_mode": False,             # says "ez <name>" for every kill you make (toggle in the list)
    "announcer": False,           # announces humiliations, first blood, gardens and rage-quits
    "translate_to_chat": False,   # says every translated chat message in chat, for everyone
    "translate_command": True,    # answers "!speak <language> <message>" from anyone (its pill on the Chat page)
    "hud": True,                  # the thin line over the game: enemy line-up, Medics, Spies
    "hud_x": None,                # where you moved it; None = the top-left corner
    "hud_y": None,
    "who_command": True,          # answers "!who <name>" from anyone with that player's summary and stats (Chat page)
    # !check, !medic, !top, !kd, !hours, !cheaters, !ip and !help (info_commands.py): each on or off.
    "info_commands": {"check": True, "medic": True, "top": True, "kd": True, "hours": True, "cheaters": True,
                      "ip": True, "help": True},
    "speak_muted": [],            # Steam IDs whose !speak is ignored (Mute !speak in a player's panel)
    "heavy_talks": False,         # False: HoovyGPT never says or asks anything, whatever keys are set
    "duels_on": False,            # the HoovyGPT + Duels button, kept across restarts while heavy_talks is off
    "ai_lock": None,              # HoovyGPT kept "on" or "muted" (the Lock button)
    "ai_model": "auto",           # HoovyGPT's model (the Model button): "auto" = AI_MODELS from the top
    "page": "Players",            # the page that's open
    # The columns both halves of the player list show, next to the name (the Columns button).
    "columns": ["Ctry", "Class", "HP", "K/D", "Duel", "TF2", "Flags"],
    "demo_check": True,           # runs tools/demo-analysis.exe on the demo TF2 records (demo_check.py)
    "demo_keep_only_cheaters": True,  # deletes finished demos with no detections and no bookmark
    "record_only_flagged": True,  # TF2 records (ds_record) only while a flagged player is in the match
    "demos_dir": "",              # TF2's demo folder; "" = the demos folder next to console.log
    "idle_rejoin": False,         # types "retry" when TF2 kicks you for being idle (Status page)
    "country_beef": ["RU", "UA"],  # the two countries whose kills on each other get announced
    "country_beef_auto": False,    # toggle in the list: announce each of those kills with the score
    "gemini_api_key": "",          # HoovyGPT asks Gemini first (https://aistudio.google.com/api-keys)
    "groq_api_key": "",            # and Groq when Gemini is slow or out (console.groq.com > API Keys)
    # Chat translation: Google first (no key), then DeepL (with this key), then MyMemory.
    "deepl_api_key": "",           # DeepL API Free (deepl.com/your-account/keys), 500,000 characters a month
    # Words looked for in profile comments and bios. Each also matches common
    # endings, so "cheat" finds cheater/cheating/cheats. Empty list = off.
    "profile_keywords": ["cheat", "hack", "aimbot", "aim bot", "wallhack", "walls", "spinbot",
                         "triggerbot", "esp", "bot", "-rep", "vac"],
    "lists": DEFAULT_LISTS,
    "web_width": 0,               # the window's size, as you left it; 0 = the default size
    "web_height": 0,
    "x": 60,                      # where the window was
    "y": 80,
    # The chat translator's overlay (tf2_translator.py).
    "translator_target_lang": "en",   # the language it translates into
    "translator_languages": "all",    # "russian": only lines in the Russian alphabet; "all": every language
    "translator_toggle_key": "F8",    # unlocks the overlay to move it and click its lines
    "translator_x": 20,               # where the overlay is
    "translator_y": 520,
    "translator_width": 620,
    "translator_max_lines": 6,        # translations shown at once
    "translator_line_seconds": 15,    # how long each one stays
    "translator_font_size": 13,
}
# The old translator config.json's setting -> its name here.
OLD_TRANSLATOR_KEYS = {key[len("translator_"):]: key for key in DEFAULTS if key.startswith("translator_")}


RETIRED = ("votekick_reply_key", "report_key", "team_ip_key", "translate_switch_key",
           "microsoft_translator_region", "token_panel", "token_panel_x", "token_panel_y", "scanner_width",
           "scanner_height", "scanner_minimized", "web_ui", "headshot_record_flag")  # settings of removed features, dropped from old configs


def load_secrets():
    """{setting: value} for the keys and the RCON password in the secrets file."""
    found = {}
    try:
        with open(SECRETS_PATH, encoding="utf-8") as f:
            for line in f:
                name, equals, value = line.strip().partition("=")
                if equals and name.strip().lower() in SECRET_KEYS:
                    found[name.strip().lower()] = value.strip()
    except OSError:
        pass
    return found


def save_secrets(values):
    """Writes the keys and the RCON password to the secrets file, keeping any other line in it."""
    try:
        with open(SECRETS_PATH, encoding="utf-8") as f:
            kept = [line.rstrip("\n") for line in f
                    if line.strip().partition("=")[0].strip().lower() not in SECRET_KEYS]
    except OSError:
        kept = ["# TF2 Toolbox's API keys and RCON password. KEY=value, one per line."]
    os.makedirs(os.path.dirname(SECRETS_PATH), exist_ok=True)
    with open(SECRETS_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(kept + [f"{key.upper()}={values.get(key, '')}" for key in SECRET_KEYS]) + "\n")


def load_config():
    """Reads scanner_config.json over the defaults and the keys from the secrets file, and makes
    an RCON password the first time. Keys found in scanner_config.json (a config from before
    they moved, or one you pasted a key into) are moved to the secrets file."""
    cfg = dict(DEFAULTS)
    on_disk = load_json(CONFIG_PATH, {})
    cfg.update(on_disk)
    for key in RETIRED:
        cfg.pop(key, None)
    cfg["info_commands"] = {**DEFAULTS["info_commands"], **cfg["info_commands"]}  # commands added later start on
    moved = not any(key.startswith("translator_") for key in on_disk) and move_translator_config(cfg)
    stored = load_secrets()
    for key in SECRET_KEYS:
        cfg[key] = on_disk.get(key) or stored.get(key, "")
    if moved or any(key in on_disk for key in SECRET_KEYS):
        save_config(cfg)  # writes them to the secrets file, and the config again without them
    if not cfg["rcon_password"]:
        cfg["rcon_password"] = secrets.token_hex(8)
        save_config(cfg)
    # Lists added in an update reach configs saved before it.
    new_lists = [url for url in DEFAULT_LISTS if url not in cfg["lists"]
                 and url not in cfg.get("lists_seen", [])]
    if new_lists:
        cfg["lists"] = cfg["lists"] + new_lists
        cfg["lists_seen"] = sorted(set(cfg.get("lists_seen", [])) | set(DEFAULT_LISTS))
        save_config(cfg)
    return cfg


def move_translator_config(cfg):
    """Once: the settings of the translator's own config.json (from when it could run on its own)
    become the translator_... settings here. The file itself is left alone, and not read again
    once these are saved. True when there was one."""
    old = load_json(OLD_TRANSLATOR_CONFIG_PATH, None)
    if not isinstance(old, dict):
        return False
    for key, setting in OLD_TRANSLATOR_KEYS.items():
        if key in old and isinstance(old[key], type(DEFAULTS[setting])):
            cfg[setting] = old[key]
    return True


def save_config(cfg):
    """Writes the settings to scanner_config.json, and the keys and the RCON password to the
    secrets file (only when one changed): those never stay in the project folder."""
    # A key pasted into either file while the scanner runs survives the scanner's next save.
    stored, pasted = load_secrets(), load_json(CONFIG_PATH, {})
    for key in SECRET_KEYS:
        if not cfg.get(key) and (pasted.get(key) or stored.get(key)):
            cfg[key] = pasted.get(key) or stored[key]
    secret = {key: cfg[key] for key in SECRET_KEYS if cfg.get(key)}
    if secret != {key: value for key, value in stored.items() if value}:
        save_secrets(secret)  # first: if this fails, the config file still has them
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump({key: value for key, value in cfg.items() if key not in SECRET_KEYS}, f, indent=2)


def launch_options(cfg):
    # -g15 makes TF2 answer g15_dumpplayer (its scoreboard data); -conclearlog
    # starts console.log fresh each launch, because those dumps make it grow fast.
    return (f"-condebug -conclearlog -g15 -usercon +ip 0.0.0.0 +rcon_password {cfg['rcon_password']} "
            f"+hostport {cfg['rcon_port']} +net_start")


def load_json(path, default):
    """Reads a JSON file, or returns default when it's missing or broken."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# --- UI ----------------------------------------------------------------------------

# Tactical HUD: near-black, thin 1px lines, square corners, one cyan accent. Red, orange and
# yellow are kept for how bad a flag is, red and blue for the teams.
BG = "#07090c"
ROW_ALT_BG = "#0b0f14"     # every other row of the player table
ROW_HOVER_BG = "#10151c"
BAR_BG = "#0b0f14"         # header, sidebar and the player's panel
CARD_BG = "#0b0f14"
CARD_HOVER_BG = "#10151c"
LINE = "#1a222c"           # the 1px lines around cards and between rows
BORDER = "#283342"         # the 1px lines around buttons and the window
SELECTED_BG = "#0c2120"    # the accent, dimmed: the selected row
BUTTON_BG = "#10151c"
BUTTON_HOVER_BG = "#0c2120"
DANGER_BG = "#1f0e0f"      # danger buttons: red line and text on a dark red
DANGER_HOVER_BG = "#3a1517"
DANGER_FG = "#ff8a83"
LINK_BG = "#0b1724"        # buttons that open a website (SteamHistory): blue line and text
LINK_HOVER_BG = "#10253a"
LINK_FG = "#7dbdff"
ON_BG = "#2de2c8"          # a setting that's on: the accent, with dark text on it
ON_FG = "#03211d"
ACCENT = "#2de2c8"         # the open page, the chosen option
TEXT = "#e3eaf1"
TEXT2 = "#a3b0be"          # second-level text: classes, numbers, descriptions
MUTED = "#7b8996"          # labels
FAINT = "#3a4552"          # switched off, unknown
GOOD = "#3fdc8a"           # status lights
WAITING = "#ff9640"
BAD = "#ff5a52"
KEY_COLOR = "#010101"
SEVERITY_FG = {3: "#ff5a52", 2: "#ff9640", 1: "#f2d04b", 0: TEXT, -1: TEXT}
HP_FG = {"over": "#8ccfff", "high": GOOD, "mid": WAITING, "low": BAD}  # health by share of the class's full health
TEAM_FG = {"ALLY": "#3fdc8a", "ENEMY": "#ff8a83", "YOU": ACCENT, "?": MUTED}
TEAM_ACCENT = {"BLU": "#4ea8ff", "RED": "#ff5a52"}

# Fonts that come with Windows 10 and 11: Bahnschrift (a condensed DIN) for text and labels, and a
# monospace font for numbers, so columns of digits line up.
FONT_UI = "Bahnschrift"
FONT_UI_BOLD = "Bahnschrift SemiBold"
FONT_LABEL = "Bahnschrift SemiBold SemiConden"   # Tk's name for Bahnschrift SemiBold SemiCondensed
MONO_FONTS = ("Cascadia Mono", "Consolas")       # Cascadia comes with Windows 11, Consolas with every Windows


def mono_family(root):
    """The first monospace font from MONO_FONTS that this PC has."""
    import tkinter.font as tkfont
    have = set(tkfont.families(root))
    return next((f for f in MONO_FONTS if f in have), "Consolas")
