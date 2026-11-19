"""What TF2 prints and how to read it: the patterns for the status list, the kill feed and the
scoreboard, SteamID conversion, and which weapon belongs to which class."""

import os
import re
import unicodedata

STEAM64_BASE = 76561197960265728
PENDING = "pending"  # hours not looked up yet (None means hidden/private)
USER_AGENT = {"User-Agent": "tf2-toolbox"}

STATUS_HEADER_RE = re.compile(r"#\s*userid\s+name\s+uniqueid")
STATUS_RE = re.compile(
    r'#\s+(?P<userid>\d+)\s+"(?P<name>.*)"\s+(?P<sid>\[U:1:\d+\])\s+(?P<connected>[\d:]+)'
    r"\s+(?P<ping>\d+)\s+(?P<loss>\d+)\s+(?P<state>\w+)"
)
# "map     : ctf_2fort at: 0 x, 0 y, 0 z" in status, "Map: ctf_2fort" when one loads.
MAP_RE = re.compile(r"^(?:map\s+:|Map:) ([\w./-]+)(?: at: .*)?\s*$")
# "hostname: Valve Matchmaking Server (Frankfurt srcds5020-fra2 #228)" and
# "players : 24 humans, 0 bots (24 max)" in status. Exact spacing on purpose: chat is
# "name :  message" (a space before the colon, two after), so a player named "hostname" or
# "players" can't fake these lines.
HOSTNAME_RE = re.compile(r"^hostname: (\S.*?)\s*$")
PLAYERS_RE = re.compile(r"^players : (\d+) humans?, (\d+) bots? \((\d+) max\)")
VALVE_SERVER_RE = re.compile(r"^Valve Matchmaking Server \((.+)\)\s*$")
SERVER_NAME_CHARS = 32  # a community server's name in the title bar is cut to this
LOBBY_HEADER_RE = re.compile(r"CTFLobbyShared:")
LOBBY_MEMBER_RE = re.compile(r"(?:Member|Pending)\[\d+\]\s+(?P<sid>\[U:1:\d+\])\s+team = (?P<team>\w+)")
NO_LOBBY_RE = re.compile(r"Failed to find lobby shared object")
# g15_dumpplayer (needs -g15) answers over RCON with TF2's scoreboard per slot, e.g.
# "m_iTeam[9] integer (2)". It has team, deaths, health, alive and m_iScore, which is
# kills (it rose by exactly each player's kill-feed kills in a live check). No class
# or killstreak: those still come from the kill feed.
G15_RE = re.compile(r"^\s*(m_\w+)\[(\d+)\]\s+\w+\s+\((.*)\)\s*$")
G15_TEAMS = {2: "RED", 3: "BLU"}
# Full health per class (overheal goes above it), for the HP column and !status.
CLASS_MAX_HEALTH = {"Scout": 125, "Soldier": 200, "Pyro": 175, "Demo": 175, "Heavy": 300,
                    "Engineer": 125, "Medic": 150, "Sniper": 125, "Spy": 125}
G15_SECONDS = 3            # how often the scoreboard is read
G15_DONE = "__g15_done__"  # marks the end of one scoreboard read in the line queue
IDLE_KICK = " has been idle for too long and has been kicked"
# Your own idle kick as TF2 reports it when it disconnects you ("TF_Idle_kicked" in tf_english.txt).
IDLE_DISCONNECT_RE = re.compile(r"Kicked due to inactivity|#TF_Idle_kicked")

# Cyrillic letters bots use to fake-copy a name that is written in Latin letters.
CONFUSABLES = str.maketrans("аеорсухАВЕКМНОРСТХ", "aeopcyxABEKMHOPCTX")


# --- Steam IDs and names ------------------------------------------------------

def to_steam64(sid):
    """Accepts [U:1:N] or a 64-bit id (int or str)."""
    s = str(sid)
    if s.startswith("[U:1:"):
        return STEAM64_BASE + int(s[5:].rstrip("]"))
    return int(s)


def my_steamid():
    """The Steam account most recently logged in on this PC."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            steam = winreg.QueryValueEx(k, "SteamPath")[0]
        with open(os.path.join(steam, "config", "loginusers.vdf"), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    users = re.findall(r'"(7656\d{13})"\s*\{(.*?)\}', text, re.S)
    for sid, body in users:
        if re.search(r'"MostRecent"\s*"1"', body):
            return int(sid)
    return int(users[0][0]) if users else None


def name_key(name):
    """Name as bots see it: no invisible characters, lookalike letters folded."""
    name = unicodedata.normalize("NFKC", name).translate(CONFUSABLES)
    return "".join(
        ch for ch in name
        if not ch.isspace() and unicodedata.category(ch) not in ("Cf", "Cc", "Mn")
    ).casefold()


def server_label(hostname):
    """A short name for the server, for the title bar: "Casual · Frankfurt" for Valve's
    matchmaking servers (the region is in the hostname's brackets, before "srcds..."), else the
    community server's own name, cut to SERVER_NAME_CHARS. "" when not known."""
    hostname = (hostname or "").strip()
    if m := VALVE_SERVER_RE.match(hostname):
        words = []
        for word in m[1].split():
            if word.lower().startswith("srcds") or word.startswith("#"):
                break
            words.append(word)
        return "Casual · " + (" ".join(words) or m[1])
    if len(hostname) > SERVER_NAME_CHARS:
        return hostname[:SERVER_NAME_CHARS - 1].rstrip() + "…"
    return hostname


def connected_seconds(text):
    secs = 0
    for part in text.split(":"):
        secs = secs * 60 + int(part)
    return secs


KILL_RE = re.compile(r"^(?P<killer>.+?) killed (?P<victim>.+) with (?P<weapon>[\w-]+)\.(?P<crit> \(crit\))?\s*$")
# Kill icons of weapons that can headshot. The Sydney Sleeper can't, and an
# arrow a Pyro reflected ("deflect_") isn't a sniper kill.
SNIPER_WEAPON_RE = re.compile(r"sniper|rifle|machina|penetration|awper|bazaar|shooting_star|classic"
                              r"|arrow|huntsman|compound_bow")
NOT_SNIPER_RE = re.compile(r"sydney|deflect")


def is_sniper_weapon(weapon):
    return bool(SNIPER_WEAPON_RE.search(weapon)) and not NOT_SNIPER_RE.search(weapon)


def current_match_lines(path, max_bytes=64_000_000):
    """The current server's player list and kill feed from the log, so a scanner
    started (or restarted) mid-match still knows who has been headshotting."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - max_bytes))
            lines = [l.rstrip("\r") for l in f.read().decode("utf-8", errors="replace").split("\n")]
    except OSError:
        return []
    joined = max((i for i, l in enumerate(lines) if "Client reached server_spawn" in l), default=None)
    if joined is None:
        return []
    lines = lines[joined:]
    if any(l.startswith("Disconnect") for l in lines):
        return []  # you've left that server since
    headers = [i for i, l in enumerate(lines) if STATUS_HEADER_RE.search(l)]
    status = []
    if headers:
        status.append(lines[headers[-1]])
        for l in lines[headers[-1] + 1:]:
            if not STATUS_RE.search(l):
                break
            status.append(l)
    return status + [l for l in lines if KILL_RE.match(l)]


# Kill-feed weapon names that only one class can use, so a kill reveals the class.
# Shared weapons (Frying Pan, Pain Train, Half-Zatoichi, Panic Attack...) aren't listed.
CLASS_WEAPONS = {
    "Scout": "scattergun force_a_nature shortstop soda_popper pep_brawlerblaster back_scatter "
             "pistol_scout pep_pistol bat bat_wood sandman ball holymackerel unarmed_combat "
             "candy_cane boston_basher atomizer wrap_assassin guillotine lava_bat warfan the_winger "
             "taunt_scout",
    "Soldier": "tf_projectile_rocket quake_rl blackbox liberty_launcher rocketlauncher_directhit "
               "cow_mangler tf_projectile_energy_ball dumpster_device airstrike righteous_bison "
               "shotgun_soldier mantreads shovel unique_pickaxe unique_pickaxe_escape market_gardener "
               "disciplinary_action taunt_soldier",
    "Pyro": "flamethrower degreaser backburner phlogistinator rainblower dragons_fury dragons_fury_bonus "
            "ai_flamethrower shotgun_pyro flaregun detonator scorch_shot manmelter fireaxe axtinguisher "
            "powerjack sledgehammer lava_axe the_maul back_scratcher thirddegree annihilator hot_hand "
            "deflect_rocket deflect_promode deflect_arrow deflect_flare deflect_sticky taunt_pyro",
    "Demo": "tf_projectile_pipe tf_projectile_pipe_remote iron_bomber quickiebomb_launcher loch_n_load "
            "loose_cannon loose_cannon_impact sticky_resistance bottle sword headtaker claidheamohmor "
            "persian_persuader ullapool_caber ullapool_caber_explosion battleaxe demoshield "
            "splendid_screen tide_turner nessieclub scotland_shard taunt_demoman",
    "Heavy": "minigun natascha brass_beast tomislav iron_curtain long_heatmaker shotgun_hwg "
             "family_business fists gloves gloves_running_urgently steel_fists warrior_spirit "
             "eviction_notice holiday_punch bread_bite apocofists taunt_heavy",
    "Engineer": "obj_sentrygun obj_sentrygun2 obj_sentrygun3 obj_minisentry wrangler_kill wrench "
                "robot_arm wrench_jag southern_hospitality eureka_effect frontier_justice widowmaker "
                "pomson rescue_ranger shotgun_primary tf_projectile_mechanicalarmorb taunt_engineer "
                "taunt_guitar_kill",
    "Medic": "syringegun_medic blutsauger crusaders_crossbow proto_syringe bonesaw ubersaw "
             "battleneedle amputator solemn_vow taunt_medic",
    "Sniper": "sniperrifle awper_hand machina player_penetration pro_rifle bazaar_bargain "
              "shooting_star the_classic sydney_sleeper tf_projectile_arrow compound_bow smg pro_smg "
              "club tribalkukri bushwacka shahanshah taunt_sniper",
    "Spy": "knife eternal_reward kunai big_earner black_rose sharp_dresser spy_cicle voodoo_pin "
           "revolver ambassador letranger enforcer diamondback taunt_spy",
}
# Spy knives: a crit kill with one of these is a backstab.
SPY_KNIVES = set("knife eternal_reward kunai big_earner black_rose sharp_dresser spy_cicle voodoo_pin".split())
WEAPON_CLASS = {w: cls for cls, names in CLASS_WEAPONS.items() for w in names.split()}
NOT_A_WEAPON = {"world", "player", "bleed_kill", "telefrag", "tf_generic_bomb"}
# Readable names for kill-feed weapons whose names aren't obvious.
WEAPON_NAMES = {
    "tf_projectile_rocket": "Rocket Launcher", "quake_rl": "Original", "blackbox": "Black Box",
    "rocketlauncher_directhit": "Direct Hit", "tf_projectile_energy_ball": "Cow Mangler",
    "tf_projectile_pipe": "Grenade Launcher", "tf_projectile_pipe_remote": "Stickybomb Launcher",
    "loch_n_load": "Loch-n-Load", "loose_cannon_impact": "Loose Cannon", "sword": "Eyelander",
    "claidheamohmor": "Claidheamh Mor", "nessieclub": "Nessie's Nine Iron", "battleaxe": "Skullcutter",
    "sniperrifle": "Sniper Rifle", "awper_hand": "AWPer Hand", "pro_rifle": "Hitman's Heatmaker",
    "player_penetration": "Machina", "the_classic": "Classic", "tf_projectile_arrow": "Huntsman",
    "pro_smg": "Cleaner's Carbine", "club": "Kukri", "obj_sentrygun": "Sentry", "obj_sentrygun2": "Sentry",
    "obj_sentrygun3": "Sentry", "obj_minisentry": "Mini-Sentry", "robot_arm": "Gunslinger",
    "wrench_jag": "Jag", "tf_projectile_mechanicalarmorb": "Short Circuit",
    "shotgun_primary": "Shotgun", "shotgun_soldier": "Shotgun", "shotgun_pyro": "Shotgun",
    "shotgun_hwg": "Shotgun", "force_a_nature": "Force-A-Nature", "pep_brawlerblaster": "Baby Face's Blaster",
    "pep_pistol": "Pretty Boy's Pistol", "holymackerel": "Holy Mackerel", "long_heatmaker": "Huo-Long Heater",
    "gloves": "KGB", "gloves_running_urgently": "GRU", "dragons_fury_bonus": "Dragon's Fury",
    "ai_flamethrower": "Nostromo Napalmer", "annihilator": "Neon Annihilator", "kunai": "Conniver's Kunai",
    "eternal_reward": "Your Eternal Reward", "spy_cicle": "Spy-cicle", "letranger": "L'Etranger",
    "crusaders_crossbow": "Crusader's Crossbow", "syringegun_medic": "Syringe Gun",
    "fryingpan": "Frying Pan", "nonnonviolent_protest": "Conscientious Objector",
    "demokatana": "Half-Zatoichi", "unique_pickaxe": "Equalizer", "unique_pickaxe_escape": "Escape Plan",
    "deflect_rocket": "reflected rockets", "deflect_promode": "reflected grenades",
    "deflect_arrow": "reflected arrows", "deflect_flare": "reflected flares",
}


def weapon_name(weapon):
    return WEAPON_NAMES.get(weapon) or weapon.replace("_", " ").title()


GC_TEAM_COLOR = {"TF_GC_TEAM_DEFENDERS": "RED", "TF_GC_TEAM_INVADERS": "BLU"}
