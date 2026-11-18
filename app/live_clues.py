"""Cheater-score clues from what TF2 prints during the match: the scoreboard (g15_dumpplayer), the
kill feed, chat and the status list. Each function is fn(app, player) -> [Clue] and is registered
with cheat_score.register when that module exists.

Everything here is about the CURRENT match only. The App keeps the raw data in memory
(match_chat, name_changes, spawn_times, kill_times) and clears it in new_match() and on
"Disconnect", like fake_ips: nothing is remembered between matches.

Every likelihood ratio (LR) below is a careful ESTIMATE written down with its reason, not a
measured accuracy. Each clue needs a minimum amount of data and otherwise says nothing (returns
no clue), and none of them ever lowers the odds: a normal player gets no clue, not LR < 1.
"""
import math
import re
import time
from dataclasses import dataclass

from game_log import is_sniper_weapon, name_key

try:
    from cheat_score import Clue, register
except ImportError:  # cheat_score.py not there (yet): the clues still work, nobody collects them
    @dataclass
    class Clue:
        key: str
        lr: float
        text: str
        why: str
        proof: bool = False
        source: str = ""

    def register(fn):
        return fn


SOURCE = "live"

# --- 1. Kill rate ------------------------------------------------------------------------------
# Kills per minute connected (TF2's m_iScore over status's connected time) against the rest of the
# lobby, as a robust z-score: 0.6745 * (x - median) / MAD, which one or two extreme players can't
# drag around the way a mean and standard deviation would.
KILL_RATE_MIN_MINUTES = 5     # less than this is too noisy (one good life is 5 kills)
KILL_RATE_MIN_KILLS = 8
KILL_RATE_MIN_LOBBY = 6       # players with 5+ minutes needed for a median and a spread
KILL_RATE_Z_START = 3.5       # Iglewicz and Hoaglin's usual cut-off for an outlier on this scale
KILL_RATE_MAX_LR = 5.0
# MAD of a lobby where many players have similar rates can be ~0: the spread is never taken as
# smaller than this (kills/min), so a 1.2 against a lobby of 1.0s isn't an "outlier".
KILL_RATE_MIN_SPREAD = 0.15
KILL_RATE_WHY = ("Good honest players often top the scoreboard, so only a rate far beyond the rest of this "
                 "lobby counts, and at most x5: aimbots and bots that kill on sight keep up rates no human "
                 "keeps for long, but a very good player in a weak lobby can too.")


def connected_now(p, now=None):
    """Seconds connected now: status's connected time was measured at its last status line."""
    if not p.last_seen:
        return p.connected
    return p.connected + max(0.0, (now or time.time()) - p.last_seen)


def kill_rates(app, now=None):
    """{sid: (kills, minutes)} for everyone on the scoreboard with MIN_MINUTES connected. Connected time
    can include time before a map change (TF2 resets the score then, not the connected time), which only
    makes a rate lower: that errs on the side of no clue."""
    rates = {}
    for p in app.players.values():
        kills = app.board_int(p.sid, "m_iScore")
        minutes = connected_now(p, now) / 60
        if kills is not None and minutes >= KILL_RATE_MIN_MINUTES:
            rates[p.sid] = (kills, minutes)
    return rates


def kill_rate_lr(z):
    """1 below the outlier cut-off, then a smooth rise towards KILL_RATE_MAX_LR: about x2.6 at
    z = 5, x4.1 at z = 8, x4.6 at z = 10. Slow on purpose: a strong honest player can reach z = 5."""
    if z <= KILL_RATE_Z_START:
        return 1.0
    return 1 + (KILL_RATE_MAX_LR - 1) * (1 - math.exp(-(z - KILL_RATE_Z_START) / 3))


def kill_rate_clues(app, player, now=None):
    rates = kill_rates(app, now)
    mine = rates.get(player.sid)
    if not mine or mine[0] < KILL_RATE_MIN_KILLS or len(rates) < KILL_RATE_MIN_LOBBY:
        return []
    values = sorted(k / m for k, m in rates.values())
    median = _median(values)
    mad = _median(sorted(abs(v - median) for v in values))
    rate = mine[0] / mine[1]
    z = 0.6745 * (rate - median) / max(mad, KILL_RATE_MIN_SPREAD)
    lr = kill_rate_lr(z)
    if lr <= 1.0:
        return []
    return [Clue("kill_rate", round(lr, 2),
                 f"{rate:.1f} kills/min ({mine[0]} in {mine[1]:.0f} min), lobby median {median:.1f}",
                 KILL_RATE_WHY, source=SOURCE)]


def _median(values):
    n = len(values)
    return (values[n // 2] + values[(n - 1) // 2]) / 2


# --- 2. Spawn kills ----------------------------------------------------------------------------
# A spawn is when the scoreboard's m_bAlive turns false -> true between two reads. TF2 doesn't print
# respawns to the console, and the scoreboard is read every G15_SECONDS (3 s), so a spawn time is
# up to 3 s late: a kill counted as "within 5 s" was really within 5-8 s of the spawn. A victim
# killed within 3 s of spawning can be missed altogether (never seen alive), so this undercounts.
SPAWN_KILL_SECONDS = 5
SPAWN_MIN_KILLS = 5          # kills on victims whose spawn was seen, needed before judging
SPAWN_MIN_SPAWN_KILLS = 3
SPAWN_HONEST_SHARE = 0.15    # guessed share of an honest player's kills that land this soon after a spawn
SPAWN_MAX_LR = 3.0           # mostly with a sniper weapon: bots that sit on the spawn door with a rifle
SPAWN_MAX_LR_OTHER = 2.0     # other classes: spawn camping is a (rude) honest tactic too
SPAWN_WHY = ("Honest players do camp spawns, and spawn time is only known to 3 s, so this is capped low; "
             "sniper bots that headshot players the moment they leave spawn do it over and over.")


def binomial_tail(k, n, p):
    """P(X >= k) for X ~ Binomial(n, p)."""
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1))


def tail_strength(tail):
    """0 at a tail probability of 5%, 1 at 1 in 10,000 and beyond, smooth (in log scale) between."""
    if tail <= 0:
        return 1.0
    return min(1.0, max(0.0, (-math.log10(tail) - 1.3) / (4 - 1.3)))


def spawn_kills(app, sid):
    """(kills judged, spawn kills, of which with a sniper weapon) for sid's kills this match."""
    judged = fast = sniper = 0
    for when, killer, victim, weapon in app.kill_times:
        if killer != sid or victim == sid or victim is None:
            continue
        spawns = [s for s in app.spawn_times.get(victim, ()) if s <= when]
        if not spawns:
            continue  # this victim's spawn wasn't seen yet: can't tell
        judged += 1
        if when - spawns[-1] <= SPAWN_KILL_SECONDS:
            fast += 1
            sniper += is_sniper_weapon(weapon)
    return judged, fast, sniper


def spawn_kill_clues(app, player):
    judged, fast, sniper = spawn_kills(app, player.sid)
    if judged < SPAWN_MIN_KILLS or fast < SPAWN_MIN_SPAWN_KILLS:
        return []
    strength = tail_strength(binomial_tail(fast, judged, SPAWN_HONEST_SHARE))
    cap = SPAWN_MAX_LR if sniper * 2 >= fast else SPAWN_MAX_LR_OTHER
    lr = 1 + (cap - 1) * strength
    if lr <= 1.0:
        return []
    with_rifle = f", {sniper} with a sniper weapon" if sniper else ""
    return [Clue("spawn_kills", round(lr, 2),
                 f"{fast} of {judged} kills within ~{SPAWN_KILL_SECONDS}-{SPAWN_KILL_SECONDS + 3} s of the "
                 f"victim spawning{with_rifle}", SPAWN_WHY, source=SOURCE)]


# --- 3. Chat accusations -----------------------------------------------------------------------
# Words people use to call someone a cheater (en, ru, tr, de, es), at the start of a word.
ACCUSE_RE = re.compile(
    r"(?<!\w)(?:hack(?:s|er|ers|ing|z)?|hax\w*|aim ?bot\w*|cheat(?:s|er|ers|ing|ed)?|bot(?:s|ted|ting)?|"
    r"wall ?hack\w*|walls|spin ?bot\w*|"
    r"чит\w*|бот\w*|аим\w*|вх|"
    r"hile\w*|"
    r"betr[üu]ger\w*|schummel\w*|"
    r"tramp\w*|chet[oa]\w*)(?!\w)", re.I)
ACCUSE_LR = {2: 1.5, 3: 2.5}  # different accusers -> LR; 3 or more stay at 2.5
ACCUSE_WHY = ("Weak on purpose: people accuse players who simply beat them, so even a few different "
              "players saying it only nudges the odds, and one angry player never counts.")


# Everyday words that would otherwise "name" a player whose name contains them ("the" in "Theo").
COMMON_WORDS = set("the and you are his her him she this that with for not was has had all any who why "
                   "how what team enemy red blu blue our your their they them its just like lol omg wtf "
                   "так это как что кто тот его она они нас вас".split())


def name_parts(msg):
    """The words of a chat line, as name_key sees them, that could name someone (3+ characters,
    not an accusation word or an everyday word)."""
    return {name_key(w) for w in re.findall(r"\w+", msg)
            if len(name_key(w)) >= 3 and not ACCUSE_RE.fullmatch(w) and name_key(w) not in COMMON_WORDS}


def names_player(app, player, msg):
    """True when msg says player's whole name, or a part of it (3+ characters) that no one else's
    name has, like App.sid_by_name refuses names two players share."""
    key = name_key(player.name)
    if len(key) >= 3 and key in name_key(msg):
        return True
    others = [name_key(p.name) for p in app.players.values() if p.sid != player.sid]
    return any(part in key and not any(part in o for o in others) for part in name_parts(msg))


def accusers(app, player):
    found = set()
    for when, sid, name, msg in app.match_chat:
        who = sid or name
        if sid in (app.me, player.sid) or (sid is None and name == player.name):
            continue
        if ACCUSE_RE.search(msg) and names_player(app, player, msg):
            found.add(who)
    return found


def accusation_clues(app, player):
    n = len(accusers(app, player))
    if n < 2:
        return []
    return [Clue("chat_accused", ACCUSE_LR[min(n, 3)], f"called a cheater in chat by {n} different players",
                 ACCUSE_WHY, source="chat")]


# --- 4. Bot behaviour ----------------------------------------------------------------------------
# Signs of a bot account; each is a small multiplier, and they are combined into ONE clue capped at
# BOT_MAX_LR because they are strongly correlated (the same bot does all of them).
URL_RE = re.compile(r"https?://|www\.|discord(?:\.gg|app\.com/invite|\.com/invite)|"
                    r"\b[\w-]+\.(?:com|net|org|ru|gg|xyz|io|cc|tk|me|shop|store)\b", re.I)
REPEAT_MIN = 3        # the same line this many times
REPEAT_MIN_CHARS = 8  # shorter lines ("gg", "lol", "nice shot") are repeated by everyone
LR_REPEAT = 2.0       # spam bots post the same line on a timer; humans rarely repeat a long line 3 times
LR_URL = 2.5          # links and Discord invites in casual chat are almost always bot advertising
LR_NAME_CHANGE = 1.5  # one name change mid-match: humans do it now and then
LR_NAME_CHANGES = 2.5  # 3+: bots cycle names to copy others or dodge kicks
NAME_CHANGES_MANY = 3
# A new account that joined with another new account (likely together): bot waves. Only what the
# GROUP adds: the account's own young age is already cheat_score's "experience" clue (under 90 days
# x3), so counting x2 for "new" again here would count the same fact twice. x1.5 is the extra for
# two fresh accounts arriving together, which honest friends on new accounts do less often than bots.
LR_NEW_GROUP = 1.5
BOT_MAX_LR = 4.0
TOGETHER_SECONDS = 5  # same rule as web_players.likely_groups (used from there when it can be imported)
BOT_WHY = ("Each sign alone has honest explanations (a pasted link, a name change, friends on fresh "
           "accounts), so each is a small multiplier and together they are capped at x4.")


def player_lines(app, player):
    return [msg for _, sid, name, msg in app.match_chat if sid == player.sid]


def new_account(app, p, now=None):
    created = (p.summary or {}).get("timecreated")
    return bool(created) and ((now or time.time()) - created) / 86400 < app.cfg["new_account_days"]


def together_with(app, player):
    """The other players in the player's "likely together" group (same team, joined within 5 s)."""
    try:
        from web_players import likely_groups
        groups = [[int(s) for s in g["sids"]] for g in likely_groups(app)]
    except Exception:  # web_players not importable here: the same rule, done locally
        groups = _likely_groups(app)
    for sids in groups:
        if player.sid in sids:
            return [app.players[s] for s in sids if s != player.sid and s in app.players]
    return []


def _likely_groups(app):
    teams = {}
    for p in app.players.values():
        if colour := app.team_color(p):
            teams.setdefault(colour, []).append(p)
    groups = []
    for members in teams.values():
        members.sort(key=lambda p: p.last_seen - p.connected)
        cluster = []
        for p in members + [None]:
            if p is not None and cluster and (p.last_seen - p.connected) - (cluster[0].last_seen - cluster[0].connected) <= TOGETHER_SECONDS:
                cluster.append(p)
                continue
            if 2 <= len(cluster) <= 6:
                groups.append([q.sid for q in cluster])
            cluster = [p]
    return groups


def bot_clues(app, player):
    lr, signs = 1.0, []
    lines = player_lines(app, player)
    counts = {}
    for msg in lines:
        text = msg.strip().casefold()
        if len(text) >= REPEAT_MIN_CHARS and not text.startswith("!"):
            counts[text] = counts.get(text, 0) + 1
    if counts and max(counts.values()) >= REPEAT_MIN:
        lr *= LR_REPEAT
        signs.append(f"same chat line {max(counts.values())} times")
    if any(URL_RE.search(msg) for msg in lines):
        lr *= LR_URL
        signs.append("posted a link")
    changes = len(app.name_changes.get(player.sid, ()))
    copied = any(t.startswith("copied someone's name") for _, t in getattr(app, "flags", {}).get(player.sid, []))
    if changes and not copied:  # a copied name is cheat_score's bot_name clue already: not counted twice
        lr *= LR_NAME_CHANGES if changes >= NAME_CHANGES_MANY else LR_NAME_CHANGE
        signs.append(f"changed name {changes} time{'s' * (changes != 1)} this match")
    if new_account(app, player) and any(new_account(app, q) for q in together_with(app, player)):
        lr *= LR_NEW_GROUP
        signs.append("new account that joined together with another new account")
    if not signs:
        return []
    return [Clue("bot_behaviour", round(min(lr, BOT_MAX_LR), 2), "bot-like: " + ", ".join(signs), BOT_WHY,
                 source=SOURCE)]


for _fn in (kill_rate_clues, spawn_kill_clues, accusation_clues, bot_clues):
    register(_fn)
