"""Deciding who looks suspicious. Everything that can flag a player is here: cheater lists, bans,
your own marks, new accounts, friends of cheaters, and headshot and crit rates. A flag is a pair
(severity, text): 3 = cheater, bot or ban; 2 = strong hint; 1 = suspicious; 0 = just information."""

import math
import re
import time
from dataclasses import dataclass

from game_log import PENDING, name_key

@dataclass
class Player:
    sid: int
    sid3: str
    userid: int
    name: str
    connected: int
    snapshot: int
    last_seen: float = 0.0
    summary: dict | None = None
    bans: dict | None = None
    sourcebans: list | None = None  # bans on community servers (steamhistory.net)
    profile: dict | None = None     # keyword hits in profile comments/bio
    hours: object = PENDING
    friends: object = PENDING       # set of SteamID64s, or None when the list is private
    level: object = PENDING         # Steam level, or None when hidden
    ping: int = 0                   # from status, in ms


def name_thieves(players):
    """{sid: original name} for players who copied a name already in the server.
    Whoever has been connected the longest keeps the name."""
    groups = {}
    for p in players:
        key = name_key(p.name)
        if key:
            groups.setdefault(key, []).append(p)
    thieves = {}
    for group in groups.values():
        if len(group) > 1:
            original = max(group, key=lambda p: p.connected)
            for p in group:
                if p is not original:
                    thieves[p.sid] = original.name
    return thieves


def evaluate(p, cfg, lists, marks, thieves, now=None):
    """[(severity, text)]: 3 = cheater, bot or any VAC/game/community ban,
    2 = other cheater-list entry, 1 = suspicious, 0 = info."""
    now = now or time.time()
    flags = []
    listed = lists.get(p.sid)
    if listed:
        attrs = sorted(listed["attributes"])
        sources = listed.get("sources") or [listed["source"]]
        where = f"{sources[0]} list" if len(sources) == 1 else f"{len(sources)} lists"
        # cheater/exploiter = red, racist = orange, "suspicious" only (e.g. SteamRep) = yellow
        severity = 3 if {"cheater", "exploiter"} & set(attrs) else 2 if "racist" in attrs else 1
        flags.append((severity, f"on {where} ({', '.join(attrs)})"))
    mark = marks.get(str(p.sid))
    if mark:
        flags.append((3, f"marked by you as {mark['reason']}"))
    if p.sid in thieves:
        flags.append((3, "copied someone's name (bot)"))
    b = p.bans
    if b and (b.get("NumberOfVACBans") or b.get("NumberOfGameBans")):
        parts = []
        if b.get("NumberOfVACBans"):
            parts.append(f"{b['NumberOfVACBans']} VAC ban")
        if b.get("NumberOfGameBans"):
            parts.append(f"{b['NumberOfGameBans']} game ban")
        flags.append((3, f"{' + '.join(parts)} ({b.get('DaysSinceLastBan', 0)}d ago)"))
    if b and b.get("CommunityBanned"):
        flags.append((3, "Steam community banned"))
    if b and b.get("EconomyBan", "none") not in ("none", ""):
        flags.append((1, f"trade {b['EconomyBan']}"))  # "trade banned" / "trade probation"
    sb = p.sourcebans or []
    if sb:
        reasons = []
        for ban in sb:
            reason = clean_reason(ban_field(ban, "reason"))
            if reason and reason.casefold() not in {r.casefold() for r in reasons}:
                reasons.append(reason)
        servers = sorted({ban_field(ban, "server") for ban in sb} - {""})
        n = len(sb)
        text = f"{n} server ban{'s' if n > 1 else ''}"
        if reasons:
            text += ": " + ", ".join(reasons[:3]) + (", …" if len(reasons) > 3 else "")
        if servers:
            text += f" ({', '.join(servers[:3])}{', …' if len(servers) > 3 else ''})"
        flags.append((3, text))
    s = p.summary
    if s:
        created = s.get("timecreated")
        if created and (now - created) / 86400 < cfg["new_account_days"]:
            flags.append((1, "new account"))
        if s.get("communityvisibilitystate") != 3:
            flags.append((0, "private profile"))
        elif not s.get("profilestate"):
            flags.append((1, "profile never set up"))
    if p.level == 0 and p.friends == set():
        # Accounts that never spent $5 can't add friends or level up: throwaways and bots.
        flags.append((1, "likely limited account (level 0, no friends)"))
    elif p.level == 0:
        flags.append((1, "Steam level 0"))
    if isinstance(p.hours, (int, float)) and p.hours < cfg["low_hours"]:
        flags.append((1, f"only {p.hours}h in TF2"))
    return sorted(flags, reverse=True)


# Community-server ban reasons that mean cheating (not "mic spam" or "not playing against the hale").
CHEAT_BAN_RE = re.compile(r"aim ?bot|aim ?lock|silent ?aim|trigger ?bot|spin ?bot|wall ?hack|\besp\b|cheat|hack|"
                          r"lmaobox|fedoraware|nullcore|exploit|чит|"
                          # Server anti-cheats ban on a detection: SMAC ("SMAC 0.8.6.0: ConVar r_drawothermodels
                          # violation"), StAC, LilAC (Little Anti-Cheat).
                          r"\bsmac\b|\bstac\b|\blilac\b|anti.?cheat", re.I)


# How much each flag says, and why. The first pattern that matches a flag's text wins. The levels:
# "proven" = a fact from Valve, "strong" and "medium" = evidence of cheating, "weak" = also common
# among honest players, "info" = says nothing about cheating, "yours" = your own judgement.
FLAG_WHY = (
    (r"^marked by you", "yours", "You marked them yourself."),
    (r"^demo check: (looked past|turned 180)", "strong",
     "Seen in this match's demo. An unmodified game can't do this, and lag can't cause it."),
    (r"^demo check:", "weak", "Seen in this match's demo. Cheats make these, but high ping and packet loss can too."),
    (r"^on \d+ lists .*(cheater|exploiter)", "strong",
     "Several separate lists name them as a cheater. Players run those lists, but agreeing lists make a mistake less likely."),
    (r"^on .* list .*(cheater|exploiter)", "medium", "One list names them as a cheater. Players run these lists and can be wrong."),
    (r"^on .* lists? .*racist", "info", "Listed for racism, not for cheating."),
    (r"^on .* lists? ", "weak", "A list calls them suspicious, without saying they cheat."),
    (r"copied someone's name", "strong", "Bots copy the names of players in the server. Honest players rarely share an exact name."),
    (r"VAC ban|game ban", "proven", "A real ban on this account. It may be old or from another game, so it doesn't prove cheating in this match."),
    (r"community banned", "weak", "Banned from Steam's community for breaking its rules, which isn't necessarily cheating."),
    (r"^trade ", "info", "A limit on trading, nothing to do with cheating."),
    (r"server bans?:.*(" + CHEAT_BAN_RE.pattern + r")", "medium", "A community server's admin banned them for cheating. That's one admin's judgement, not Valve's."),
    (r"server bans?", "weak", "Banned on a community server, with no sign that it was for cheating."),
    (r"crit kills", "strong", "Luck gets this many random crits less than 1 time in 1000, even with a Kritz medic."),
    (r"% headshots", "medium", "A very high headshot rate this match. Very good snipers can get close to this too."),
    (r"^secondhand cheater|^friends with", "weak", "Being friends with a cheater isn't cheating."),
    (r"new account|never set up|Steam level 0|limited account|^only ", "weak",
     "Common for bots and throwaway cheat accounts, but for new honest players too."),
    (r"profile comment|^bio says", "weak", "Anyone can write this on a profile, and it may be a joke."),
)


def flag_why(severity, text):
    """(level, reason) for one flag. A severity 0 flag is information whatever it says."""
    if severity == 0:
        return "info", "Not suspicious by itself."
    for pattern, level, why in FLAG_WHY:
        if re.search(pattern, text, re.I):
            return level, why
    return "weak", ""


def overall_verdict(levels):
    """One line above a player's flags, saying what they add up to, or None for no line.
    levels: the level of each of their flags, like ["proven", "weak", "weak"]."""
    # TODO(human): decide what these add up to.
    return None


def explain_flags(flags):
    """The text under the buttons for a selected player: the verdict, then each flag with its
    level and reason, or "" when they have no flags."""
    if not flags:
        return ""
    whys = [(flag_why(severity, text), text) for severity, text in flags]
    verdict = overall_verdict([level for (level, _), _ in whys])
    lines = [verdict] if verdict else []
    for (level, why), text in whys:
        lines.append(f"[{level}] {text}" + (f": {why}" if why else ""))
    return "\n".join(lines)


def clean_reason(reason):
    """A ban reason as typed by a server admin, tidied up for one line."""
    reason = " ".join(reason.split()).strip(" .!-")
    return reason if len(reason) <= 40 else reason[:39] + "…"


def lobby_friends(p, players):
    """The players in this lobby who are friends with p. Friendship is mutual,
    so a private friend list is filled in from the other side."""
    friends = p.friends if isinstance(p.friends, set) else set()
    return [q for q in players if q.sid != p.sid and (
        q.sid in friends or (isinstance(q.friends, set) and p.sid in q.friends))]


def friend_flags(p, players, known_cheaters, worst, mark_friends, name_of):
    """Flags from friend lists: friends of someone you marked ("secondhand cheater"),
    known cheaters among a player's friends, and who they're friends with in this lobby.
    worst = {sid: highest flag severity}; mark_friends = {marked sid: their friends,
    saved with the mark}; name_of(sid) = a cheater's name, "" when unknown."""
    friends = p.friends if isinstance(p.friends, set) else mark_friends.get(p.sid, set())
    in_lobby = lobby_friends(p, players)
    flags = []

    def names(sids):
        shown = [n for n in map(name_of, sids) if n][:2]
        return ", ".join(shown) + ("…" if len(sids) > len(shown) else "")

    # Either side's friend list will do: theirs may be private, and the list saved with
    # a mark covers cheaters who aren't in this lobby. The marked ones themselves get the
    # count below instead.
    secondhand = [] if p.sid in mark_friends else sorted(
        sid for sid, theirs in mark_friends.items() if sid in friends or p.sid in theirs)
    if secondhand:
        flags.append((2, f"secondhand cheater (friends with {names(secondhand)})"))
    flagged = [q for q in in_lobby if worst.get(q.sid, -1) >= 3 and q.sid not in secondhand]
    if flagged:
        flags.append((2, f"friends with flagged {', '.join(q.name for q in flagged[:2])}"))
    others = sorted((friends & known_cheaters) - {q.sid for q in flagged} - set(secondhand) - {p.sid})
    if others:  # not counting anyone twice
        n, named = len(others), names(others)
        flags.append((2, f"friends with {n} known cheater{'s' if n > 1 else ''}" + (f": {named}" if named else "")))
    if in_lobby:
        names = ", ".join(q.name for q in in_lobby[:3]) + ("…" if len(in_lobby) > 3 else "")
        flags.append((0, f"friends in lobby: {names}"))
    return flags


# Single-shot ranged weapons that only crit at random (no headshots, backstabs, revenge crits,
# mini-crit tricks). Crit hacks force crits on exactly these. Left out (LR_RESEARCH s11, TF2 wiki
# "Critical hits"): melee (random crits up to 60%, so the test means nothing) and rapid-fire weapons
# (minigun, flamethrower, SMG, pistol, syringe gun: they crit in 2-second bursts, not shot by shot).
RANDOM_CRIT_WEAPONS = {
    "tf_projectile_rocket", "quake_rl", "blackbox", "liberty_launcher", "rocketlauncher_directhit",
    "scattergun", "force_a_nature", "shortstop", "pep_brawlerblaster",
    "shotgun_primary", "shotgun_soldier", "shotgun_pyro", "shotgun_hwg", "panic_attack", "family_business",
    "tf_projectile_pipe", "tf_projectile_pipe_remote", "iron_bomber", "quickiebomb_launcher", "loch_n_load",
    "revolver", "letranger", "enforcer",
    "crusaders_crossbow", "widowmaker",
}
NORMAL_CRIT_RATE = 0.25  # generous: ~15% of kills with these weapons are crits in real matches


def binomial_tail(n, k, p):
    """Chance of k or more successes in n tries at rate p."""
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1))


def crit_flag(stats, cfg):
    """stats = [random-crit weapon kills, of which crits]. Flags crit rates that
    would happen by luck less than 1 in 1000 times, even for a Kritz pocket."""
    kills, crits = stats
    if kills < cfg["crit_min_kills"] or binomial_tail(kills, crits, NORMAL_CRIT_RATE) > 0.001:
        return None
    return 2, f"{round(100 * crits / kills)}% crit kills ({crits}/{kills}), possible crit hack"


def luck_odds(kills, crits):
    """How rarely luck alone gives this many crits, at the generous NORMAL_CRIT_RATE:
    "1 in 950k by luck"."""
    chance = binomial_tail(kills, crits, NORMAL_CRIT_RATE)
    n = 1 / chance if chance > 0 else float("inf")
    if n >= 999_500_000:
        return "under 1 in a billion by luck"
    if n >= 999_500:
        return f"1 in {n / 1_000_000:.0f}M by luck"
    if n >= 999.5:
        return f"1 in {n / 1000:.0f}k by luck"
    return f"1 in {n:.0f} by luck"


def crit_text(stats, odds_below=0.01):
    """stats = [random-crit weapon kills, of which crits], for chat: "10/10 random-crit kills
    (100%), 1 in 950k by luck". The odds are left out while luck explains it easily."""
    kills, crits = stats
    text = f"{crits}/{kills} random-crit kills ({round(100 * crits / kills)}%)"
    if binomial_tail(kills, crits, NORMAL_CRIT_RATE) <= odds_below:
        text += f", {luck_odds(kills, crits)}"
    return text


def headshot_text(stats):
    kills, headshots = stats
    return f"{round(100 * headshots / kills)}% headshots ({headshots}/{kills} sniper kill{'s' if kills > 1 else ''})"


def headshot_flag(stats, cfg):
    """stats = [sniper kills, headshots]; headshot kills show up as "(crit)"."""
    kills, headshots = stats
    if kills < 5:
        return None
    pct = round(100 * headshots / kills)
    text = headshot_text(stats)
    if kills >= cfg["headshot_min_kills"] and pct >= cfg["headshot_flag_percent"]:
        return 2, text
    return 0, text


def fmt_hours(hours):
    if hours == PENDING:
        return "…"
    return "hidden" if hours is None else f"{hours}h"


def fmt_age(summary, now=None):
    if not summary or not summary.get("timecreated"):
        return "…" if summary is None else "?"
    days = int(((now or time.time()) - summary["timecreated"]) // 86400)
    return f"{days // 365}y" if days >= 365 else f"{days}d"


def age_in_words(summary, now=None):
    """An account's age as "3 years" or "36 days", or "" when it isn't known."""
    if not summary or not summary.get("timecreated"):
        return ""
    days = int(((now or time.time()) - summary["timecreated"]) // 86400)
    if days >= 365:
        return f"{days // 365} year{'s' * (days // 365 != 1)}"
    return f"{days} day{'s' * (days != 1)}"


def ban_field(ban, name):
    """First field whose key contains name ("reason" skips UnbanReason). Tolerant
    of how steamhistory.net spells its keys."""
    for key, value in ban.items():
        k = key.lower()
        if name in k and not k.startswith("unban"):
            return str(value or "")
    return ""


def profile_text(profile):
    """What the Profile column shows, and whether it found anything."""
    if profile is None:
        return "…", False
    if profile.get("error"):
        return "?", False
    parts = []
    if profile["comment_hits"]:
        n = profile["comment_hits"]
        parts.append(f"{n} comment{'s' if n > 1 else ''}: {', '.join(profile['comment_words'][:3])}")
    if profile["bio_words"]:
        parts.append(f"bio: {', '.join(profile['bio_words'][:3])}")
    if parts:
        return " · ".join(parts), True
    return ("" if profile["comments_visible"] else "comments hidden"), False


def profile_flags(profile):
    """Profile keyword hits as flags, for the chat summary."""
    if not profile or profile.get("error"):
        return []
    flags = []
    if profile["comment_hits"]:
        n = profile["comment_hits"]
        flags.append((2, f"{n} profile comment{'s say' if n > 1 else ' says'} "
                         f"{'/'.join(profile['comment_words'][:3])}"))
    if profile["bio_words"]:
        flags.append((2, f"bio says {'/'.join(profile['bio_words'][:3])}"))
    return flags
