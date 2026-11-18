"""How likely is it that a player cheats? One number per player, worked out the way published
anti-cheat research does it, and explained clue by clue.

The method:
- Start from the base rate: about PRIOR (3%) of the players in a casual lobby cheat.
- Every clue the scanner has is a likelihood ratio (LR): how much more often cheaters show that clue
  than honest players. LR 10 = ten times more common among cheaters; LR 0.5 = twice as common among
  honest players. Bayes' rule in log-odds: odds = prior odds x LR1 x LR2 x ...
- Rates (headshots, random crits) are a statistical test against honest play: the chance that an
  honest player gets at least this many by luck (a binomial tail), only from a minimum sample. A
  small sample (3/3 headshots) never moves the odds.
- Clues that say the same thing count once: two cheater lists are one clue with a bigger LR, an old
  account and many hours are one "experience" clue.
- "Proven" only for things an unmodified game can't do (the demo check's strong checks).

Every LR below is a careful ESTIMATE with a comment saying why, not a measured accuracy. The score
only advises; nothing here acts on it (no automatic votekick).

Other modules add clues with register(fn): fn(app, player) -> [Clue]. live_clues.py and
demo_clues.py are imported at the bottom when they exist."""

import math
import re
import time
from dataclasses import dataclass, field, replace

from game_log import PENDING
from player_flags import CHEAT_BAN_RE, NORMAL_CRIT_RATE, ban_field, binomial_tail

PRIOR = 0.03  # share of cheaters in a casual lobby: a careful estimate (bots and cheaters are common in casual)

# The bands, from the probability. "Proven" needs a clue marked proof, whatever the number says.
BANDS = ("Clean", "Watch", "Suspicious", "Likely", "Proven")
BAND_FROM = (("Likely", 0.70), ("Suspicious", 0.35), ("Watch", 0.10))
BAND_WORDS = {"Clean": "CLEAN", "Watch": "WATCH", "Suspicious": "SUSPICIOUS",
              "Likely": "LIKELY CHEATER", "Proven": "PROVEN CHEATER"}


@dataclass
class Clue:
    key: str        # stable id, e.g. "lists", "hs_rate", "demo_oob_pitch", "kill_rate"
    lr: float       # likelihood ratio (multiplier on the odds)
    text: str       # short reason, e.g. "92% headshots (24/26 Sniper kills)"
    why: str        # one sentence: why this multiplier (what honest players do instead)
    proof: bool = False
    source: str = ""  # "lists" | "steam" | "live" | "demo" | "profile" | "chat" ...


@dataclass
class Score:
    prob: float
    band: str
    clues: list = field(default_factory=list)  # sorted by impact, biggest first
    prior: float = PRIOR

    @property
    def odds(self):
        return to_odds(self.prob)

    @property
    def proof(self):
        return any(c.proof for c in self.clues)

    def at_least(self, band):
        return BANDS.index(self.band) >= BANDS.index(band)


# --- log-odds --------------------------------------------------------------------------------

def to_odds(prob):
    prob = min(max(prob, 1e-12), 1 - 1e-12)
    return prob / (1 - prob)


def log_odds(prob):
    return math.log(to_odds(prob))


def from_log_odds(lo):
    if lo >= 0:
        return 1 / (1 + math.exp(-lo))
    e = math.exp(lo)
    return e / (1 + e)


def combine(prior, lrs):
    """The probability after multiplying the prior odds by every LR (a sum in log-odds)."""
    return from_log_odds(log_odds(prior) + sum(math.log(lr) for lr in lrs if lr > 0))


def band_of(prob, proof=False):
    if proof:
        return "Proven"
    return next((band for band, low in BAND_FROM if prob >= low), "Clean")


def impact(clue):
    return abs(math.log(clue.lr)) if clue.lr > 0 else 0.0


# --- the clues ---------------------------------------------------------------------------------

CLUE_SOURCES = []


def register(fn):
    """Adds a clue source fn(app, player) -> [Clue]. Registered again (a module reloaded): replaced."""
    name = f"{fn.__module__}.{fn.__qualname__}"
    CLUE_SOURCES[:] = [f for f in CLUE_SOURCES if f"{f.__module__}.{f.__qualname__}" != name]
    CLUE_SOURCES.append(fn)
    return fn


def clamp(x, low, high):
    return max(low, min(high, x))


def one_in(p):
    """A small chance in words: "1 in 2,000"."""
    if p <= 0:
        return "under 1 in a billion"
    n = 1 / p
    if n >= 1e9:
        return "under 1 in a billion"
    if n >= 1e6:
        return f"1 in {n / 1e6:,.0f} million"
    return f"1 in {sig(n):,}"


def sig(n):
    """n rounded to 2 significant digits (2,147 -> 2,100), so the text doesn't claim precision."""
    if n < 100:
        return round(n)
    digits = int(math.floor(math.log10(n))) - 1
    return int(round(n, -digits))


def tail_lr(p_tail):
    """A binomial tail probability as a likelihood ratio, on a smooth curve:
    LR = 1 / (20 p), kept between 1 and 30. p >= 5% (happens to honest players every few games)
    moves nothing; 1% gives x5; 1 in 600 or rarer the most, x30. Capped at 30 because the honest
    rate is itself an estimate and a very good honest player sits in the tail more often than the
    average one; only the demo's strong checks can prove anything."""
    if p_tail <= 0:
        return 30.0
    return clamp(1 / (20 * p_tail), 1.0, 30.0)


def _flags(app, p):
    return [text for _, text in getattr(app, "flags", {}).get(p.sid, [])]


# Cheater lists. One clue however many lists: they copy each other and share reports, so they
# aren't independent; more lists still mean more separate people checked the player.
LIST_CHEATER_LR = {1: 20.0, 2: 40.0, 3: 80.0}  # 3 = three or more
LIST_SUSPICIOUS_LR = {1: 3.0, 2: 5.0}           # listed only as "suspicious" (e.g. SteamRep)


def list_clues(app, p):
    listed = getattr(app, "lists", {}).get(p.sid)
    if not listed:
        return []
    attrs = set(listed.get("attributes") or ())
    n = len(listed.get("sources") or [listed.get("source")])
    where = "1 cheater list" if n == 1 else f"{n} cheater lists"
    if attrs & {"cheater", "exploiter"}:
        return [Clue("lists", LIST_CHEATER_LR[min(n, 3)], f"on {where} ({', '.join(sorted(attrs))})",
                     "Lists are made from reported cheaters that someone checked; they can be wrong, "
                     "but agreeing lists make a mistake less likely.", source="lists")]
    if attrs - {"racist"}:
        return [Clue("lists", LIST_SUSPICIOUS_LR[min(n, 2)], f"on {where} as {', '.join(sorted(attrs))}",
                     "Listed as suspicious, without the list saying they cheat.", source="lists")]
    return []  # racist only: says nothing about cheating


MARK_LR = 100.0  # your own judgement after watching them: you decided, so it reaches Likely by itself


def mark_clues(app, p):
    mark = getattr(app, "marks", {}).get(str(p.sid))
    if not mark:
        return []
    return [Clue("marked", MARK_LR, f"marked by you as {mark.get('reason', 'cheater')}",
                 "You watched them and judged it yourself.", source="you")]


BOT_NAME_LR = 30.0  # bots copy a name already in the server; honest players almost never share an exact name


def bot_name_clues(app, p):
    if any(t.startswith("copied someone's name") for t in _flags(app, p)):
        return [Clue("bot_name", BOT_NAME_LR, "copied someone's name in this server",
                     "Bots copy the names of players already in the server; honest players almost never "
                     "share an exact name.", source="live")]
    return []


# VAC and game bans by how long ago: a recent ban on an account still playing TF2 says the most.
# Older bans may be from another game or long ago, so they say less.
BAN_LR = ((365, 8.0), (3 * 365, 4.0), (None, 2.0))
MANY_BANS = 1.5     # two or more bans on the account: x1.5 more (kept under 12 in all)
COMMUNITY_BAN_LR = 1.5  # Steam community ban: rule breaking, not necessarily cheating
SERVER_CHEAT_BAN_LR = {1: 4.0, 2: 8.0}  # community servers' admins banned them for cheating (2 = 2+ servers)
SERVER_OTHER_BAN_LR = 1.2  # banned on a server for something else (mic spam, ...)


def ban_clues(app, p):
    clues = []
    b = p.bans or {}
    vac, game = b.get("NumberOfVACBans") or 0, b.get("NumberOfGameBans") or 0
    if vac or game:
        days = b.get("DaysSinceLastBan") or 0
        lr = next(lr for limit, lr in BAN_LR if limit is None or days < limit)
        if vac + game >= 2:
            lr = min(12.0, lr * MANY_BANS)
        what = " + ".join(filter(None, (f"{vac} VAC ban" if vac else "", f"{game} game ban" if game else "")))
        age = f"{days} days ago" if days < 365 else f"{days // 365} year{'s' * (days >= 730)} ago"
        clues.append(Clue("bans", lr, f"{what}, last {age}",
                          "A real ban from Valve; a recent one says most, an old one may be from another game.",
                          source="steam"))
    if b.get("CommunityBanned"):
        clues.append(Clue("community_ban", COMMUNITY_BAN_LR, "Steam community banned",
                          "Banned for breaking Steam's community rules, which isn't necessarily cheating.",
                          source="steam"))
    sb = p.sourcebans or []
    if sb:
        cheat = {ban_field(ban, "server") or str(i) for i, ban in enumerate(sb)
                 if CHEAT_BAN_RE.search(ban_field(ban, "reason"))}
        if cheat:
            n = len(cheat)
            clues.append(Clue("server_bans", SERVER_CHEAT_BAN_LR[min(n, 2)],
                              f"banned for cheating on {n} community server{'s' * (n > 1)}",
                              "A server admin judged it, not Valve; admins can be wrong.", source="steam"))
        else:
            clues.append(Clue("server_bans", SERVER_OTHER_BAN_LR, f"{len(sb)} community server ban{'s' * (len(sb) > 1)}",
                              "Banned on a server, with no sign it was for cheating.", source="steam"))
    return clues


# Experience: TF2 hours and account age as ONE clue (they go together, so not counted twice).
# Cheaters and bots mostly play on throwaway accounts that get banned and replaced; years on one
# account and many hours are more typical of honest players. Bots idle hours too, so many hours only
# lower the odds a little (never under x0.4 together).
HOURS_LR = ((100, 3.0), (300, 1.5), (1000, 1.0), (3000, 0.7), (None, 0.5))  # (below this many hours, LR)
AGE_LR = ((90, 3.0), (365, 1.5), (5 * 365, 1.0), (None, 0.8))               # (below this many days, LR)
EXPERIENCE_RANGE = (0.4, 6.0)


def _step(value, table):
    return next(lr for limit, lr in table if limit is None or value < limit)


def experience_clues(app, p, now=None):
    cfg = getattr(app, "cfg", {})
    hours_table = ((cfg.get("low_hours", 100), 3.0),) + HOURS_LR[1:]
    age_table = ((cfg.get("new_account_days", 90), 3.0),) + AGE_LR[1:]
    lr, parts = 1.0, []
    if isinstance(p.hours, (int, float)) and not isinstance(p.hours, bool):
        lr *= _step(p.hours, hours_table)
        parts.append(f"{p.hours:,.0f} hours")
    created = (p.summary or {}).get("timecreated")
    if created:
        days = ((now or time.time()) - created) / 86400
        lr *= _step(days, age_table)
        parts.append(f"{int(days // 365)}-year-old account" if days >= 365 else f"{int(days)}-day-old account")
    lr = clamp(lr, *EXPERIENCE_RANGE)
    if not parts or abs(math.log(lr)) < 0.05:
        return []
    why = ("Cheaters and bots mostly use new throwaway accounts; new honest players exist too." if lr > 1 else
           "Cheaters mostly use new accounts that get banned and replaced; bots idle hours too, so this "
           "lowers the odds only a little.")
    return [Clue("experience", lr, ", ".join(parts), why, source="steam")]


# Throwaway signs on the profile, as one clue (they go together): never set up, level 0, no friends.
PROFILE_LR = {"private": 1.3, "never set up": 2.5, "limited": 3.0, "level 0": 1.5}
PROFILE_MAX = 4.0


def profile_clues(app, p):
    found = []
    s = p.summary
    if s:
        if s.get("communityvisibilitystate") != 3:
            found.append("private")
        elif not s.get("profilestate"):
            found.append("never set up")
    if p.level == 0:
        found.append("limited" if p.friends == set() else "level 0")
    if not found:
        return []
    lr = min(PROFILE_MAX, math.prod(PROFILE_LR[f] for f in found))
    words = {"private": "private profile", "never set up": "profile never set up",
             "limited": "level 0, no friends (limited account)", "level 0": "Steam level 0"}
    return [Clue("profile", lr, ", ".join(words[f] for f in found),
                 "Common for bots and throwaway cheat accounts, but many honest players hide their profile too.",
                 source="profile")]


# Words on the profile: other players writing "cheater" in the comments (angry losers do that too),
# and the bio (may be a joke or a boast). One clue, at most x5.
COMMENT_LR = {1: 2.0, 2: 3.0, 3: 4.0}
BIO_LR = 1.5
WORDS_MAX = 5.0


def profile_word_clues(app, p):
    pr = p.profile
    if not pr or pr.get("error"):
        return []
    lr, parts = 1.0, []
    n = pr.get("comment_hits") or 0
    if n:
        lr *= COMMENT_LR[min(n, 3)]
        parts.append(f"{n} profile comment{'s' * (n > 1)}: {'/'.join(pr.get('comment_words', [])[:3])}")
    if pr.get("bio_words"):
        lr *= BIO_LR
        parts.append(f"bio says {'/'.join(pr['bio_words'][:3])}")
    if not parts:
        return []
    return [Clue("profile_words", min(lr, WORDS_MAX), "; ".join(parts),
                 "Others call them a cheater on their profile; players who just lost say that too.",
                 source="profile")]


# Friends with cheaters (secondhand): cheaters often play and trade with each other, but being
# friends with one isn't cheating. One clue: the strongest of the three friend flags.
FRIEND_LR = {"secondhand": 2.5, "flagged": 2.0, 1: 2.0, 2: 3.0, 5: 4.0}


def friend_clues(app, p):
    best, texts = 1.0, []
    for text in _flags(app, p):
        lr = None
        if text.startswith("secondhand cheater"):
            lr = FRIEND_LR["secondhand"]
        elif text.startswith("friends with flagged"):
            lr = FRIEND_LR["flagged"]
        elif m := re.match(r"friends with (\d+) known cheater", text):
            n = int(m[1])
            lr = FRIEND_LR[5] if n >= 5 else FRIEND_LR[2] if n >= 2 else FRIEND_LR[1]
        if lr:
            best = max(best, lr)
            texts.append(text)
    if not texts:
        return []
    return [Clue("friends", best, "; ".join(texts),
                 "Cheaters often have cheater friends, but being friends with one isn't cheating.", source="steam")]


# The demo check (demo_check.py). Strong checks are proof: an unmodified game can't send them.
# Weak checks: cheats make them, but lag and packet loss do too; LR grows with the count, and
# high ping (demo_check.ping_note) shrinks it to a quarter.
DEMO_PROOF_LR = 1000.0
DEMO_WEAK_PER_HIT, DEMO_WEAK_MAX, DEMO_HIGH_PING_SHARE = 0.5, 6.0, 0.25


def demo_clues(app, p):
    try:
        from demo_check import STRONG_CHECKS, WEAK_CHECKS, ping_note
    except ImportError:
        return []
    counts = app.demo_checks_of(p.sid) if hasattr(app, "demo_checks_of") else {}
    clues = []
    for name, about in STRONG_CHECKS.items():
        if counts.get(name):
            clues.append(Clue("demo_" + name.split("/")[-1], DEMO_PROOF_LR, f"demo check: {about} ({counts[name]}x)",
                              "An unmodified game can't send this, whatever the ping.", proof=True, source="demo"))
    n = sum(counts.get(name, 0) for name in WEAK_CHECKS)
    if n:
        lr = min(DEMO_WEAK_MAX, 1 + DEMO_WEAK_PER_HIT * n)
        note = ping_note(p.ping)
        if note:
            lr = 1 + (lr - 1) * DEMO_HIGH_PING_SHARE
        weak = ", ".join(f"{counts[k]} {about}" for k, about in WEAK_CHECKS.items() if counts.get(k))
        clues.append(Clue("demo_weak", lr, f"demo check: {weak}",
                          "Cheats make these, but lag and packet loss can too" + (f" ({note})." if note else "."),
                          source="demo"))
    return clues


# Most Sniper headshots in one life ever (history). From a sample: 23% of listed cheaters reached
# 30 or more, against 3% of other players: 0.23 / 0.03 = about x7.7 (a small sample, so x7).
HS_RECORD_LR = 7.0


def hs_record_clues(app, p):
    limit = getattr(app, "cfg", {}).get("headshot_record_flag", 30)
    if isinstance(p.hs_record, int) and not isinstance(p.hs_record, bool) and p.hs_record >= limit:
        return [Clue("hs_record", HS_RECORD_LR, f"{p.hs_record} headshots in one life (Sniper record)",
                     f"In a sample, 23% of listed cheaters reached {limit}+, against 3% of other players.",
                     source="history")]
    return []


# Live rates this match: a binomial test against honest play, from a minimum sample.
# Headshots: share of Sniper kills that are headshots. Honest pub Snipers average around 45% (rifle);
# the test assumes 50% so good honest players aren't punished. The Huntsman's headshots are harder:
# 40%. A mix of both: weighted by kills.
HONEST_HS_RIFLE, HONEST_HS_BOW = 0.50, 0.40
BOW_RE = re.compile(r"arrow|huntsman|compound_bow")
MIN_RATE_KILLS = 10
# Random crits: TF2's random crit chance is 2%, rising to 12% with damage dealt in the last 20
# seconds (and rapid-fire weapons crit in bursts). A crit does 3x damage, so crits are a bigger share
# of kills than of shots, and a Kritzkrieg uber or the round-win crits add more. player_flags'
# NORMAL_CRIT_RATE (25% of kills) is a generous upper estimate of all that, used here too.
HONEST_CRIT = NORMAL_CRIT_RATE


def honest_hs_rate(app, p):
    weapons = getattr(app, "weapons", {}).get(p.sid) or {}
    try:
        from game_log import is_sniper_weapon
    except ImportError:
        return HONEST_HS_RIFLE
    bow = sum(n for w, n in weapons.items() if is_sniper_weapon(w) and BOW_RE.search(w) and n > 0)
    rifle = sum(n for w, n in weapons.items() if is_sniper_weapon(w) and not BOW_RE.search(w) and n > 0)
    if bow + rifle == 0:
        return HONEST_HS_RIFLE
    return (rifle * HONEST_HS_RIFLE + bow * HONEST_HS_BOW) / (rifle + bow)


def rate_clue(key, kills, hits, p_honest, text, honest_words, source="live"):
    """A Clue from a binomial test, or None while the sample is too small or luck explains it."""
    if kills < MIN_RATE_KILLS or hits <= kills * p_honest:
        return None
    p_tail = binomial_tail(kills, hits, p_honest)
    lr = tail_lr(p_tail)
    if lr <= 1.0:
        return None
    return Clue(key, lr, text, f"{honest_words}; this is {one_in(p_tail)} by luck.", source=source)


def rate_clues(app, p):
    clues = []
    kills, hs = (getattr(app, "kills", {}).get(p.sid) or (0, 0))[:2]
    if kills:
        rate = honest_hs_rate(app, p)
        c = rate_clue("hs_rate", kills, hs, rate, f"{hs}/{kills} Sniper headshots ({round(100 * hs / kills)}%)",
                      f"An honest Sniper hits ~45% (tested at {round(100 * rate)}% to be fair)")
        clues += [c] if c else []
    cfg = getattr(app, "cfg", {})
    kills, crits = (getattr(app, "crits", {}).get(p.sid) or (0, 0))[:2]
    if kills >= max(MIN_RATE_KILLS, cfg.get("crit_min_kills", 0)):
        c = rate_clue("crit_rate", kills, crits, HONEST_CRIT, f"{crits}/{kills} random-crit kills ({round(100 * crits / kills)}%)",
                      "Random crits are 2-12% of shots; even with Kritz and round-win crits honest kills stay under ~25%")
        clues += [c] if c else []
    return clues


BUILTIN_SOURCES = (list_clues, mark_clues, bot_name_clues, ban_clues, experience_clues, profile_clues,
                   profile_word_clues, friend_clues, demo_clues, hs_record_clues, rate_clues)
for _fn in BUILTIN_SOURCES:
    register(_fn)


# --- the score -----------------------------------------------------------------------------------

_failed = set()


def gather(app, p):
    """Every clue for p, one per key: when two sources give the same key, the one registered later
    wins (so live_clues.py / demo_clues.py can replace a clue from here)."""
    if p.sid == getattr(app, "me", None):
        return []
    by_key = {}
    for fn in CLUE_SOURCES:
        try:
            found = fn(app, p) or []
        except Exception as e:  # one broken source mustn't take the list down (said once, not 3x a second)
            said = (getattr(fn, "__name__", str(fn)), type(e).__name__)
            if said not in _failed:
                _failed.add(said)
                print(f"cheat_score: {said[0]} failed: {e!r}")
            continue
        for c in found:
            if c and c.lr > 0:
                by_key[c.key] = c
    return sorted(demo_overlap(list(by_key.values())), key=impact, reverse=True)


# Nocrex's weak demo checks (demo_weak: aim flicks, angle repeats) and demo_clues' aim clues
# (demo_aim_lock, demo_fast_acquire) look at the same aim in the same demo: an aimbot's snap is often
# both a Nocrex flick and a hard stop. When both groups are up, the smaller group counts only as its
# square root, as demo_clues already does between its own two clues (OVERLAP_POWER there).
DEMO_WEAK_GROUP, DEMO_AIM_GROUP = ("demo_weak",), ("demo_aim_lock", "demo_fast_acquire")
DEMO_OVERLAP_POWER = 0.5


def demo_overlap(clues):
    """clues with the smaller of the two correlated demo groups shrunk to its square root (each of its
    clues to the root, so the group's product is the root). Only clues that raise the odds count."""
    weak = [c for c in clues if c.key in DEMO_WEAK_GROUP and c.lr > 1 and not c.proof]
    aim = [c for c in clues if c.key in DEMO_AIM_GROUP and c.lr > 1 and not c.proof]
    if not weak or not aim:
        return clues
    small = min((weak, aim), key=lambda g: math.prod(c.lr for c in g))
    shrunk = {id(c): replace(c, lr=c.lr ** DEMO_OVERLAP_POWER,
                             why=c.why + " Counted as its square root: the demo's other aim check saw the same aim.")
              for c in small}
    return [shrunk.get(id(c), c) for c in clues]


def score(app, p):
    clues = gather(app, p)
    prob = combine(PRIOR, [c.lr for c in clues])
    return Score(prob, band_of(prob, any(c.proof for c in clues)), clues, PRIOR)


def is_cheater(app, p, sc=None):
    """The Cheaters filter: the old rule (a severity-3 flag or marked by you) OR the score's band is
    Likely or Proven. Both, so neither misses one."""
    if p.sid == getattr(app, "me", None):
        return False
    old = any(s >= 3 for s, _ in getattr(app, "flags", {}).get(p.sid, [])) or str(p.sid) in getattr(app, "marks", {})
    return old or (sc or score(app, p)).at_least("Likely")


# --- in words ------------------------------------------------------------------------------------

def odds_text(odds):
    """odds 0.031 -> "1 : 32", 15.2 -> "15 : 1"."""
    if odds >= 1:
        return f"{sig(odds):,} : 1"
    return f"1 : {sig(1 / odds):,}"


def lr_text(lr):
    """x40, x12, x2.5, x0.5"""
    if lr >= 10:
        return f"×{lr:,.0f}"
    text = f"{lr:.1f}" if lr >= 2 else f"{lr:.2f}"  # x1.05 stays x1.05, not a misleading x1
    return "×" + (text.rstrip("0").rstrip(".") if "." in text else text)


def pct_text(prob):
    pct = 100 * prob
    if pct >= 99.5:
        return ">99%"
    if pct < 1:
        return "<1%"
    return f"{pct:.0f}%"


# Clues that barely move the odds (x0.9 to x1.1) are shown as one line with their combined multiplier,
# so the list stays short and the multipliers shown still multiply to the result.
SMALL_LR = (0.9, 1.1)


def is_small(clue):
    return not clue.proof and SMALL_LR[0] <= clue.lr <= SMALL_LR[1]


def small_row(clues):
    """One row for the small clues among clues, or None when there are none."""
    small = [c for c in clues if is_small(c)]
    if not small:
        return None
    lr = math.prod(c.lr for c in small)
    n = len(small)
    return {"lr": lr_text(lr), "up": lr >= 1, "proof": False, "key": "small", "source": "",
            "text": f"+ {n} small clue{'s' * (n > 1)} ({lr_text(SMALL_LR[0])}–{lr_text(SMALL_LR[1])} each)",
            "why": "; ".join(f"{lr_text(c.lr)} {c.text}" for c in small)}


def breakdown(sc):
    """The score as the tooltip shows it: the start, one line per clue (biggest first; the small ones
    together as one line at the end), the result."""
    small = small_row(sc.clues)
    return {
        "start": f"Start: {round(100 * sc.prior)}% of casual players cheat (odds {odds_text(to_odds(sc.prior))})",
        "rows": [{"lr": lr_text(c.lr), "up": c.lr >= 1, "text": c.text, "why": c.why, "proof": c.proof,
                  "key": c.key, "source": c.source} for c in sc.clues if not is_small(c)] + ([small] if small else []),
        "end": f"= odds {odds_text(sc.odds)}",
        "pct": pct_text(sc.prob),
        "band": sc.band,
        "words": BAND_WORDS[sc.band],
        "note": "Proof: an unmodified game can't do this." if sc.band == "Proven" else
                "" if sc.clues else "No clues yet: the base rate.",
    }


def explain(sc):
    """The same as plain text lines."""
    b = breakdown(sc)
    lines = [b["start"]] + [f"{r['lr']:<6} {r['text']} — {r['why']}" for r in b["rows"]]
    return "\n".join(lines + [f"{b['end']}  →  {b['pct']}  {b['words']}"])


# Other tasks' clue sources register themselves when imported.
try:
    import live_clues  # noqa: F401,E402
except ImportError:
    pass
try:
    import demo_clues as _demo_clues  # noqa: F401,E402
except ImportError:
    pass
