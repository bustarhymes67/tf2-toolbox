"""How likely is it that a player cheats? One number per player, worked out the way published
anti-cheat research does it, and explained clue by clue.

The method:
- Start from the base rate: about PRIOR (2%, the cheat_prior setting) of the players in a casual
  lobby cheat.
- Every clue the toolbox has is a likelihood ratio (LR): how much more often cheaters show that clue
  than honest players. LR 10 = ten times more common among cheaters; LR 0.5 = twice as common among
  honest players. Bayes' rule in log-odds: odds = prior odds x LR1 x LR2 x ...
- Rates (headshots, random crits) compare how likely the kills are for a cheater and for an honest
  player whose skill varies (a beta-binomial Bayes factor), only from a minimum sample. A small
  sample (3/3 headshots) never moves the odds.
- Clues that say the same thing count once: lists that copy each other are one list, and account
  age, hours and profile are one "account" group (the strongest in full, the next at half...).
- "Proven" only for things an unmodified game can't do (the demo check's strong checks).

Every LR below is a careful ESTIMATE with a comment saying where it comes from (LR_RESEARCH = the
research note of 2026-11-19 behind these numbers, by section), not a measured accuracy. The score
only advises; nothing here acts on it (no automatic votekick).

Other modules add clues with register(fn): fn(app, player) -> [Clue]. live_clues.py and
demo_clues.py are imported at the bottom when they exist."""

import math
import re
import time
import urllib.parse
from dataclasses import dataclass, field, replace
from datetime import datetime

from game_log import PENDING
from player_flags import CHEAT_BAN_RE, ban_field, clean_reason, flag_why, profile_flags

PRIOR = 0.02  # LR_RESEARCH s1: ~0.5 human cheaters per 24-player casual lobby since the 2024 ban wave (low confidence)
PRIOR_RANGE = (0.001, 0.5)  # the cheat_prior setting is kept inside this (0.01-0.04 is the defensible range)

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


def prior_of(app):
    """The start of the score: the cheat_prior setting, PRIOR when it isn't set or isn't a number."""
    try:
        value = float(getattr(app, "cfg", {}).get("cheat_prior", PRIOR))
    except (TypeError, ValueError):
        return PRIOR
    return clamp(value, *PRIOR_RANGE) if math.isfinite(value) else PRIOR


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


def fade(lr, years, half_life):
    """An LR > 1 whose evidence is `years` old: what it adds above x1 halves every half_life years."""
    if lr <= 1 or not years or years <= 0:
        return lr
    return 1 + (lr - 1) * 0.5 ** (years / half_life)


def years_since(when, now=None):
    """Years from a time (unix seconds or milliseconds, or an ISO date) to now; None when unknown."""
    if isinstance(when, str):
        text = when.strip()
        if text.isdigit():
            when = int(text)
        else:
            try:
                when = datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
            except ValueError:
                return None
    if not isinstance(when, (int, float)) or isinstance(when, bool) or when <= 0:
        return None
    if when > 1e11:  # milliseconds
        when /= 1000
    return max(0.0, ((now or time.time()) - when) / (365.25 * 86400))


def _flags(app, p):
    return [text for _, text in getattr(app, "flags", {}).get(p.sid, [])]


# Cheater lists. One clue however many lists, counted by independent list FAMILIES: files that copy
# or collect each other are one judgement, not two (LR_RESEARCH s2, measured on the cached lists).
LIST_FAMILIES = (  # (part of the list's address or name, family), first match wins
    ("pazerop/tf2_bot_detector", "pazer"), ("sisterhailey/tf2bd2", "pazer"),  # official list and its fork
    ("tf2bd official", "pazer"), ("official player blacklist", "pazer"),
    ("roto.lol", "roto"), ("@trusted", "roto"),
    ("milenko", "milenko"), ("joekiller", "joekiller"), ("qfoxb", "qfoxb"), ("steamrep", "steamrep"),
)
LIST_AGGREGATORS = {"roto", "milenko"}  # LR_RESEARCH s2: roto holds 93% of the official list, milenko is "cumulative"
LIST_CHEATER_LR = {1: 30.0, 2: 100.0, 3: 200.0}  # LR_RESEARCH s2: independent families (3 = 3+); capped low for hijacked/copied errors
LIST_ENTRY_HALF_LIFE_Y = 3.0  # LR_RESEARCH s2: lists are mostly dormant (median last seen 2021); stolen accounts get returned
LIST_SUSPICIOUS_LR = 1.3      # LR_RESEARCH s2: "suspicious" = SteamRep trade-scam bans, not a cheating judgement
RACIST_LIST_LR = 1.0  # listed only for racism: a list of bad behaviour, not of cheating, so it moves nothing
CHEATER_ATTRS = {"cheater", "exploiter"}


def list_family(name):
    """The family of a list, from its address or its name: lists that copy each other share one."""
    low = (name or "").casefold()
    return next((family for part, family in LIST_FAMILIES if part in low), low)


def independent_lists(families):
    """How many independent judgements these list families are: an aggregator (roto, milenko) only
    counts when nothing else names them (LR_RESEARCH s2's rule)."""
    families = set(families)
    return len(families - LIST_AGGREGATORS) or (1 if families else 0)


def list_cheater_lr(n_independent, years=None):
    """The lists' LR: by independent families, faded by how long ago a list last saw them."""
    if n_independent <= 0:
        return 1.0
    return fade(LIST_CHEATER_LR[min(n_independent, 3)], years, LIST_ENTRY_HALF_LIFE_Y)


def list_clues(app, p, now=None):
    listed = getattr(app, "lists", {}).get(p.sid)
    if not listed:
        return []
    attrs = set(listed.get("attributes") or ())
    sources = [s for s in (listed.get("sources") or [listed.get("source")]) if s]
    n = max(1, len(sources))
    names = ": " + ", ".join(sources[:3]) + (", …" if len(sources) > 3 else "") if sources else ""
    if attrs & CHEATER_ATTRS:
        per = listed.get("by_source") or {}
        cheater = [s for s in sources if not per.get(s) or set(per[s].get("attributes") or ()) & CHEATER_ATTRS]
        families = {list_family((per.get(s, {}).get("urls") or [s])[0]) for s in cheater}
        k = independent_lists(families)
        times = [per[s]["time"] for s in cheater if per.get(s, {}).get("time")]
        years = years_since(max(times), now) if times else None
        lr = list_cheater_lr(k, years)
        where = "1 cheater list" if n == 1 else f"{n} cheater lists"
        why = "Lists of reported cheaters that someone checked; they can be wrong (stolen accounts get returned)."
        if k < len(cheater):
            why += f" Some copy others, so they count as {k} independent list{'s' * (k > 1)}."
        if years is not None and years >= 1:
            why += f" Last seen on a list {years:.0f} year{'s' * (round(years) != 1)} ago, so it counts less."
        return [Clue("lists", lr, f"on {where} ({', '.join(sorted(attrs))}){names}", why, source="lists")]
    where = "1 list" if n == 1 else f"{n} lists"
    if attrs - {"racist"}:
        return [Clue("lists", LIST_SUSPICIOUS_LR, f"on {where} as {', '.join(sorted(attrs))}{names}",
                     "Listed as suspicious (SteamRep: trade scams), not as a cheater.", source="lists")]
    return [Clue("lists", RACIST_LIST_LR, f"on {where} as racist{names}",
                 "Listed for racism, which says nothing about cheating.", source="lists")]


MARK_LR = 150.0  # your own judgement, not evidence to calibrate: big enough to reach Likely by itself at a 2% start (75%)
MARK_KEY = "marked"  # the page shows this clue as YOUR MARK


def mark_clues(app, p):
    mark = getattr(app, "marks", {}).get(str(p.sid))
    if not mark:
        return []
    return [Clue(MARK_KEY, MARK_LR, f"marked by you as {mark.get('reason', 'cheater')}",
                 "You watched them and judged it yourself (Mark as cheater); Unmark as cheater takes it back.", source="you")]


BOT_NAME_LR = 30.0  # LR_RESEARCH s12 (no data, kept): bots copy names by design; humans rarely share an exact name


def bot_name_clues(app, p):
    if any(t.startswith("copied someone's name") for t in _flags(app, p)):
        return [Clue("bot_name", BOT_NAME_LR, "copied someone's name in this server",
                     "Bots copy the names of players already in the server; honest players almost never "
                     "share an exact name.", source="live")]
    return []


# VAC and game bans fade smoothly with age. A ban seen in a casual match is almost always from
# another game (a TF2 VAC ban keeps them off Valve's servers): "cheated somewhere before".
BAN_LR0 = 8.0      # LR_RESEARCH s3: a ban today; 15-30% of cheaters have an earlier ban vs 2-4% of honest players
BAN_TAU_Y = 2.0    # LR_RESEARCH s3: e-folding time in years (1 y: x5.2, 3 y: x2.6)
BAN_FLOOR = 1.5    # LR_RESEARCH s3: an old ban still says a little (6 y+: x1.5)
BAN_EXTRA = 0.25   # LR_RESEARCH s3: each more ban x(1 + 0.25), counted up to 4 bans (repeat offenders 7.9%)
BAN_MAX = 12.0     # LR_RESEARCH s3: cap for all bans together
COMMUNITY_BAN_LR = 1.3  # LR_RESEARCH s3: community bans are rule breaking; 20% lifted within ~32 days
SERVER_CHEAT_BAN_LR = {1: 4.0, 2: 8.0}  # LR_RESEARCH s3: admins' cheating bans, by server NETWORK (2 = 2+)
SERVER_BAN_HALF_LIFE_Y = 3.0  # LR_RESEARCH s3: same fading as list entries
SERVER_OTHER_BAN_LR = 1.1  # LR_RESEARCH s3: banned on a server for something else (mic spam, ...)


def ban_lr(days, n_bans=1):
    """VAC + game bans: 1 + 7 * exp(-years / 2), never under x1.5, x1.25 per extra ban, at most x12."""
    lr = max(BAN_FLOOR, 1 + (BAN_LR0 - 1) * math.exp(-(max(days, 0) / 365) / BAN_TAU_Y))
    return min(BAN_MAX, lr * (1 + BAN_EXTRA * (min(max(n_bans, 1), 4) - 1)))


def ban_network(ban):
    """Which server network a SourceBans ban is from: the domain when the server is given as an
    address ("bans.skial.com" -> "skial.com"), else its name without its number ("Skial #3" ->
    "skial"). Servers of one network share one ban list, so they are one judgement."""
    value = ban_field(ban, "server").strip()
    if not value:
        return ""
    host = "" if " " in value else urllib.parse.urlparse(value if "://" in value else "//" + value).hostname or ""
    if "." in host:
        labels = [x for x in host.casefold().split(".") if x not in ("www", "bans", "sourcebans", "sb")]
        return ".".join(labels[-2:])
    return re.sub(r"[\W_]*(#?\d+|server)?\s*$", "", value.casefold()).strip() or value.casefold()


def ban_clues(app, p, now=None):
    clues = []
    b = p.bans or {}
    vac, game = b.get("NumberOfVACBans") or 0, b.get("NumberOfGameBans") or 0
    if vac or game:
        days = b.get("DaysSinceLastBan") or 0
        lr = ban_lr(days, vac + game)
        what = " + ".join(filter(None, (f"{vac} VAC ban" if vac else "", f"{game} game ban" if game else "")))
        age = f"{days} days ago" if days < 365 else f"{days // 365} year{'s' * (days >= 730)} ago"
        clues.append(Clue("bans", lr, f"{what}, last {age}",
                          "A real ban from Valve, likely from another game; it counts less every year.",
                          source="steam"))
    if b.get("CommunityBanned"):
        clues.append(Clue("community_ban", COMMUNITY_BAN_LR, "Steam community banned",
                          "Banned for breaking Steam's community rules, which isn't necessarily cheating.",
                          source="steam"))
    sb = p.sourcebans or []
    if sb:
        cheat = [ban for ban in sb if CHEAT_BAN_RE.search(ban_field(ban, "reason"))]
        networks = {ban_network(ban) or str(i) for i, ban in enumerate(cheat)}
        reasons = []
        for ban in sb:
            reason = clean_reason(ban_field(ban, "reason"))
            if reason and reason.casefold() not in {r.casefold() for r in reasons}:
                reasons.append(reason)
        said = f": {', '.join(reasons[:3])}{', …' if len(reasons) > 3 else ''}" if reasons else ""
        if cheat:
            n = len(networks)
            ages = [y for y in (years_since(ban_field(ban, "timestamp") or ban_field(ban, "date"), now)
                                for ban in cheat) if y is not None]
            years = min(ages) if ages else None
            why = "A server admin judged it, not Valve; servers of one community share bans, so they count once."
            if years is not None and years >= 1:
                why += f" The newest is {years:.0f} year{'s' * (round(years) != 1)} old, so it counts less."
            clues.append(Clue("server_bans", fade(SERVER_CHEAT_BAN_LR[min(n, 2)], years, SERVER_BAN_HALF_LIFE_Y),
                              f"banned for cheating by {n} server communit{'ies' if n > 1 else 'y'}{said}",
                              why, source="steam"))
        else:
            clues.append(Clue("server_bans", SERVER_OTHER_BAN_LR,
                              f"{len(sb)} community server ban{'s' * (len(sb) > 1)}{said}",
                              "Banned on a server, with no sign it was for cheating.", source="steam"))
    return clues


# The account group: age, TF2 hours and the profile all say "how established is this account", so
# they are ONE clue (LR_RESEARCH s7). Each part is a smooth curve, not steps (LR_RESEARCH s13).
AGE_PIVOT_DAYS = 730.0    # LR_RESEARCH s4: fitted LR = 1 at ~720 days (listed cheaters vs casual players)
AGE_SLOPE = 0.8           # LR_RESEARCH s4: least-squares slope -0.84 of log LR on log age
AGE_RANGE = (0.25, 6.0)   # LR_RESEARCH s4: old accounts get bought/stolen (floor); the extreme data is bots (cap)
HOURS_PIVOT = 500.0       # LR_RESEARCH s5: no TF2 data; same form as age, weaker (low confidence)
HOURS_SLOPE = 0.35        # LR_RESEARCH s5
HOURS_RANGE = (0.5, 3.5)  # LR_RESEARCH s5: bots idle hours, so many hours lower the odds only a little
PROFILE_LR = {"private": 1.1, "never set up": 1.8, "limited": 2.0, "level 0": 1.5}  # LR_RESEARCH s6 (private: Blackburn 2011)
PROFILE_MAX = 2.5         # LR_RESEARCH s6: the profile's parts together
ACCOUNT_WEIGHTS = (1.0, 0.5, 0.25, 0.125)  # LR_RESEARCH s7: the strongest part in full, the next at half...
ACCOUNT_RANGE = (0.2, 8.0)                 # LR_RESEARCH s7: the whole group
ACCOUNT_MIN_EFFECT = 0.05  # under ~x1.05 either way the group isn't shown (it moves nothing you'd notice)


def age_lr(days):
    """Account age: (days / 730) ^ -0.8, kept between x0.25 and x6. 90 days x5.3, 1 year x1.7,
    2 years x1, 5 years x0.48, 10 years x0.28."""
    return clamp((max(days, 1.0) / AGE_PIVOT_DAYS) ** -AGE_SLOPE, *AGE_RANGE)


def hours_lr(hours):
    """TF2 hours: ((h + 10) / 510) ^ -0.35, kept between x0.5 and x3.5. 0 h x3.5, 100 h x1.7,
    500 h x1, 3,000 h x0.54."""
    return clamp(((max(hours, 0) + 10) / (HOURS_PIVOT + 10)) ** -HOURS_SLOPE, *HOURS_RANGE)


def account_lr(lrs):
    """The group's LR: in log terms the parts that point the same way are sorted by size and weighted
    1, 0.5, 0.25, ... (they mostly repeat each other); the two directions are added; kept between
    x0.2 and x8."""
    logs = [math.log(x) for x in lrs if x and x > 0 and abs(math.log(x)) > 1e-9]
    total = 0.0
    for side in (sorted((l for l in logs if l > 0), reverse=True), sorted(l for l in logs if l < 0)):
        total += sum(w * l for w, l in zip(ACCOUNT_WEIGHTS, side))
    return clamp(math.exp(total), *ACCOUNT_RANGE)


def profile_parts(p):
    """The profile's throwaway signs, as words."""
    found = []
    s = p.summary
    if s:
        if s.get("communityvisibilitystate") != 3:
            found.append("private")
        elif not s.get("profilestate"):
            found.append("never set up")
    if p.level == 0:
        found.append("limited" if p.friends == set() else "level 0")
    return found


PROFILE_WORDS = {"private": "private profile", "never set up": "profile never set up",
                 "limited": "level 0, no friends (limited account)", "level 0": "Steam level 0"}


def account_clues(app, p, now=None):
    parts = []  # (words, LR)
    created = (p.summary or {}).get("timecreated")
    if created:
        days = ((now or time.time()) - created) / 86400
        parts.append((f"{int(days // 365)}-year-old account" if days >= 365 else f"{int(days)}-day-old account",
                      age_lr(days)))
    if isinstance(p.hours, (int, float)) and not isinstance(p.hours, bool):  # hidden hours (None): no part, x1
        parts.append((f"{p.hours:,.0f} hours", hours_lr(p.hours)))
    found = profile_parts(p)
    if found:
        parts.append((", ".join(PROFILE_WORDS[f] for f in found),
                      min(PROFILE_MAX, math.prod(PROFILE_LR[f] for f in found))))
    if not parts:
        return []
    lr = account_lr([x for _, x in parts])
    if abs(math.log(lr)) < ACCOUNT_MIN_EFFECT:
        return []
    parts.sort(key=lambda part: abs(math.log(part[1])), reverse=True)
    text = "; ".join(f"{words} {lr_text(x)}" for words, x in parts)
    why = ("Cheaters and bots mostly use new, bare accounts; new honest players exist too." if lr > 1 else
           "Years on one account with many hours is typical of honest players, but accounts get sold or stolen.")
    ups, downs = sum(x > 1 for _, x in parts), sum(x < 1 for _, x in parts)
    if max(ups, downs) > 1:
        why += " These parts overlap, so they count as one: the biggest in full, the next at half strength."
    return [Clue("account", lr, text, why, source="steam")]


# Words on the profile: other players writing "cheater" in the comments (angry losers do that too),
# and the bio (may be a joke or a boast). One clue.
COMMENT_LR = {1: 1.3, 2: 1.5, 3: 2.0}  # LR_RESEARCH s8: 6.1% of reported-but-clean accounts banned later: one accusation says little
BIO_LR = 1.3                           # LR_RESEARCH s8
WORDS_MAX = 3.0                        # LR_RESEARCH s8: the profile's words together


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


# Friends who are flagged, by the SHARE of their friends: ~70% of cheaters have >= 10% cheater
# friends, ~70% of honest players have none (LR_RESEARCH s9, Blackburn 2011).
FRIEND_LR_ANY = 1.8    # LR_RESEARCH s9: any flagged friend (or the friend count is unknown)
FRIEND_LR_TENTH = 3.0  # LR_RESEARCH s9: 10% or more of their friends flagged
FRIEND_LR_HALF = 6.0   # LR_RESEARCH s9: half or more (~15% of cheaters, ~1-2% of honest players)


def friends_lr(n_flagged, n_friends=None):
    if n_flagged <= 0:
        return 1.0
    if not n_friends:
        return FRIEND_LR_ANY
    share = n_flagged / max(n_friends, n_flagged)
    return FRIEND_LR_HALF if share >= 0.5 else FRIEND_LR_TENTH if share >= 0.1 else FRIEND_LR_ANY


def flagged_friends(app, p):
    """The friends of p who are known cheaters, marked by you, or flagged red in this lobby."""
    friends = p.friends if isinstance(p.friends, set) else set()
    marks = getattr(app, "marks", {}) or {}
    marked = {int(k) for k in marks if str(k).isdigit()}
    found = (friends & (set(getattr(app, "cheater_ids", ()) or ()) | marked)) - {p.sid}
    for k, mark in marks.items():
        if str(k).isdigit() and p.sid in set(mark.get("friends", ()) or ()):
            found.add(int(k))
    flags = getattr(app, "flags", {})
    for q in getattr(app, "players", {}).values():
        if q.sid != p.sid and (q.sid in friends or (isinstance(q.friends, set) and p.sid in q.friends)) \
                and max((s for s, _ in flags.get(q.sid, [])), default=-1) >= 3:
            found.add(q.sid)
    return found


def _named(text):
    """How many people a friend flag names ("friends with flagged Ann, Bo" -> 2)."""
    if m := re.match(r"friends with (\d+) known cheater", text):
        return int(m[1])
    names = re.sub(r"^(secondhand cheater \(friends with |friends with flagged )", "", text).rstrip(")")
    return max(1, len([n for n in names.split(", ") if n.strip()]))


def friend_clues(app, p):
    texts = [t for t in _flags(app, p) if t.startswith(("secondhand cheater", "friends with flagged"))
             or re.match(r"friends with \d+ known cheater", t)]
    if not texts:
        return []
    n = max(len(flagged_friends(app, p)), sum(_named(t) for t in texts))
    total = len(p.friends) if isinstance(p.friends, set) and p.friends else None
    share = f" ({n} of {total} friends)" if total else ""
    return [Clue("friends", friends_lr(n, total), "; ".join(texts) + share,
                 "Cheaters often have cheater friends, but being friends with one isn't cheating"
                 + ("; counted by the share of their friends." if total else "; their friend list is hidden."),
                 source="steam")]


# The demo check (demo_check.py). Strong checks are proof: an unmodified game can't send them.
# Weak checks: cheats make them, but lag and packet loss do too; LR grows with the count, and
# high ping (demo_check.ping_note) shrinks it to a quarter.
DEMO_PROOF_LR = 1000.0  # LR_RESEARCH s12 (kept): the only place proof is justified
DEMO_WEAK_PER_HIT, DEMO_WEAK_MAX, DEMO_HIGH_PING_SHARE = 0.5, 6.0, 0.25  # LR_RESEARCH s12 (kept, no data): low caps


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


# Live rates this match, as a Bayes factor: how likely k hits of n kills are for a cheater against
# an honest player whose own rate varies (both beta-binomial), from a minimum sample. Not a tail
# p-value, which isn't a likelihood ratio (LR_RESEARCH s10, s13).
HS_HONEST_MEAN = 0.72   # LR_RESEARCH s10: 72.0% of 16,237 rifle kills by Snipers on logs.tf were headshots
HS_HONEST_CONC = 30.0   # LR_RESEARCH s10: fit a+b = 40; 30 is wider on purpose, kinder to good Snipers
HS_CHEAT_MEAN = 0.93    # LR_RESEARCH s10: aimbot Snipers headshot nearly every kill (estimate)
HS_CHEAT_CONC = 15.0    # LR_RESEARCH s10: wide, for closet cheaters
HS_BOW_SHIFT = -0.12    # LR_RESEARCH s10: Huntsman honest mean ~0.60 (estimate, no data)
HS_LR_RANGE = (1.0, 30.0)  # LR_RESEARCH s10: never lowers the odds; capped, the honest reference is a sample
HONEST_HS_RIFLE, HONEST_HS_BOW = HS_HONEST_MEAN, HS_HONEST_MEAN + HS_BOW_SHIFT
BOW_RE = re.compile(r"arrow|huntsman|compound_bow")
MIN_RATE_KILLS = 10     # under this many kills a rate never moves the odds
# Random crits, only single-shot ranged weapons (player_flags.RANDOM_CRIT_WEAPONS: no melee, no
# rapid-fire). Random crits are 2-8% of shots; a crit does 3x damage, so their share of kills is higher.
CRIT_HONEST_MEAN = 0.10  # LR_RESEARCH s11: honest crit-kill share of ranged weapons (estimate, at most ~15%)
CRIT_HONEST_CONC = 20.0  # LR_RESEARCH s11
CRIT_CHEAT_MEAN = 0.45   # LR_RESEARCH s11: crit hacks (estimate)
CRIT_CHEAT_CONC = 6.0    # LR_RESEARCH s11
CRIT_LR_RANGE = (1.0, 20.0)  # LR_RESEARCH s11


def _lbeta(a, b):
    return math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)


def betabin_lr(k, n, honest_mean, honest_conc, cheat_mean, cheat_conc):
    """P(k of n | cheater) / P(k of n | honest), both beta-binomial (the binomial coefficients cancel)."""
    ah, bh = honest_mean * honest_conc, (1 - honest_mean) * honest_conc
    ac, bc = cheat_mean * cheat_conc, (1 - cheat_mean) * cheat_conc
    return math.exp((_lbeta(k + ac, n - k + bc) - _lbeta(ac, bc)) - (_lbeta(k + ah, n - k + bh) - _lbeta(ah, bh)))


def betabin_tail(k, n, mean, conc):
    """The chance of k or more hits of n for an honest player (rates varying around mean): the
    "1 in N by luck" in the text. The LR is betabin_lr, not this."""
    a, b = mean * conc, (1 - mean) * conc
    return min(1.0, sum(math.exp(math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1)
                                 + _lbeta(i + a, n - i + b) - _lbeta(a, b)) for i in range(k, n + 1)))


def hs_lr(k, n, honest_mean=HS_HONEST_MEAN):
    """The headshot clue's LR, kept between x1 and x30: 24/26 x5, 15/15 x24, 30/30 x30."""
    return clamp(betabin_lr(k, n, honest_mean, HS_HONEST_CONC, HS_CHEAT_MEAN, HS_CHEAT_CONC), *HS_LR_RANGE)


def crit_lr(k, n):
    """The random-crit clue's LR, kept between x1 and x20."""
    return clamp(betabin_lr(k, n, CRIT_HONEST_MEAN, CRIT_HONEST_CONC, CRIT_CHEAT_MEAN, CRIT_CHEAT_CONC), *CRIT_LR_RANGE)


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


def rate_clues(app, p):
    clues = []
    kills, hs = (getattr(app, "kills", {}).get(p.sid) or (0, 0))[:2]
    if kills >= MIN_RATE_KILLS:
        rate = honest_hs_rate(app, p)
        lr = hs_lr(hs, kills, rate)
        if lr > 1.0:
            tail = betabin_tail(hs, kills, rate, HS_HONEST_CONC)
            clues.append(Clue("hs_rate", lr, f"{hs}/{kills} Sniper headshots ({round(100 * hs / kills)}%)",
                              f"Honest Snipers headshot ~{round(100 * rate)}% of their kills; "
                              f"this is {one_in(tail)} by luck.", source="live"))
    cfg = getattr(app, "cfg", {})
    kills, crits = (getattr(app, "crits", {}).get(p.sid) or (0, 0))[:2]
    if kills >= max(MIN_RATE_KILLS, cfg.get("crit_min_kills", 0)):
        lr = crit_lr(crits, kills)
        if lr > 1.0:
            tail = betabin_tail(crits, kills, CRIT_HONEST_MEAN, CRIT_HONEST_CONC)
            clues.append(Clue("crit_rate", lr, f"{crits}/{kills} random-crit kills ({round(100 * crits / kills)}%)",
                              f"Random crits are 2-8% of shots, about {round(100 * CRIT_HONEST_MEAN)}% of honest "
                              f"kills (no melee); this is {one_in(tail)} by luck.", source="live"))
    return clues


# Headshot and crit flags the rate test can't use yet (too few kills, or luck explains the rate): the
# flag still shows, as a clue that moves nothing. Registered before rate_clues, whose real clue (same
# key) replaces it as soon as the test says something.
SMALL_SAMPLE_LR = 1.0


def small_sample_clues(app, p):
    clues = []
    for text in _flags(app, p):
        for key, pattern, stats in (("hs_rate", r"% headshots", "kills"), ("crit_rate", r"crit kills", "crits")):
            if not re.search(pattern, text) or any(c.key == key for c in clues):
                continue
            kills, hits = (getattr(app, stats, {}).get(p.sid) or (0, 0))[:2]
            if kills < MIN_RATE_KILLS:
                why = (f"Only {kills} kill{'s' * (kills != 1)} so far: too few to tell skill or luck from cheating "
                       f"(the test starts at {MIN_RATE_KILLS}).")
            else:
                mean, conc = ((honest_hs_rate(app, p), HS_HONEST_CONC) if key == "hs_rate"
                              else (CRIT_HONEST_MEAN, CRIT_HONEST_CONC))
                why = (f"Honest players get this by luck often enough ({one_in(betabin_tail(hits, kills, mean, conc))}), "
                       "so it doesn't change the odds.")
            clues.append(Clue(key, SMALL_SAMPLE_LR, text, why, source="live"))
    return clues


# Flags that say nothing about cheating, shown so you know them, at x1:
# - a trade ban or probation: Valve limits trading after scams, chargebacks or a stolen account, not
#   for cheating, and no sample we know says cheaters get them more often;
# - friends in this lobby: playing with friends is normal (friends who ARE cheaters are friend_clues).
TRADE_LR = 1.0
LOBBY_FRIENDS_LR = 1.0


def info_clues(app, p):
    clues = []
    for text in _flags(app, p):
        if text.startswith("trade ") and not any(c.key == "trade" for c in clues):
            clues.append(Clue("trade", TRADE_LR, text, "A limit on trading (scams, chargebacks), not a cheating ban.",
                              source="steam"))
        elif text.startswith("friends in lobby") and not any(c.key == "lobby_friends" for c in clues):
            clues.append(Clue("lobby_friends", LOBBY_FRIENDS_LR, text,
                              "Playing with friends is normal; friends who are known cheaters count separately.",
                              source="steam"))
    return clues


BUILTIN_SOURCES = (list_clues, mark_clues, bot_name_clues, ban_clues, account_clues,
                   profile_word_clues, friend_clues, demo_clues, small_sample_clues, rate_clues,
                   info_clues)
for _fn in BUILTIN_SOURCES:
    register(_fn)


# --- which flag a clue is about ------------------------------------------------------------------

# A flag (player_flags.evaluate and the rest, as the list shows them) and the clue that counts it.
# A clue whose text is the flag's own text matches first; then these patterns on the flag's text.
DEMO_PROOF_FLAG = r"^demo check: (looked past|turned 180)"
FLAG_CLUES = {
    "lists": r"^on .* lists?\b", MARK_KEY: r"^marked by you", "bot_name": r"copied someone's name",
    "bans": r"VAC ban|game ban", "community_ban": r"community banned", "server_bans": r"server bans?",
    "account": r"^new account|^only \d|private profile|never set up|level 0|limited account",
    "profile_words": r"profile comment|^bio says", "friends": r"^secondhand cheater|^friends with (flagged|\d)",
    "demo_weak": r"^demo check: \d", "hs_rate": r"% headshots",
    "crit_rate": r"crit kills", "trade": r"^trade ", "lobby_friends": r"^friends in lobby",
}


def flag_clue(text, clues):
    """The clue that counts the flag with this text, or None."""
    for c in clues:
        if c.text == text:
            return c
    for c in clues:
        pattern = FLAG_CLUES.get(c.key)
        if pattern is None and c.proof and c.key.startswith("demo"):
            pattern = DEMO_PROOF_FLAG
        if pattern and re.search(pattern, text, re.I):
            return c
    return None


def all_flags(app, p):
    """[(severity, text)]: the player's flags and their profile's keyword hits, as the page shows them."""
    return list(getattr(app, "flags", {}).get(p.sid, [])) + profile_flags(getattr(p, "profile", None))


LEFTOVER_LR = 1.0  # a flag no clue above knows (a new kind): shown, but it moves nothing until it has an LR


def leftover_clues(app, p, clues):
    """A x1 clue for each flag no clue counts, so every reason the list has also shows with the score."""
    out = []
    for severity, text in all_flags(app, p):
        if flag_clue(text, clues + out) is None:
            why = flag_why(severity, text)[1] or "Shown for information."
            out.append(Clue("flag:" + text, LEFTOVER_LR, text, why + " Not counted in the score.", source="flag"))
    return out


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
    clues = say_so_overlap(demo_overlap(list(by_key.values())))
    clues += leftover_clues(app, p, clues)
    return sorted(clues, key=impact, reverse=True)


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


# Profile comments and chat accusations are both "people say so" (LR_RESEARCH s8): when both raise
# the odds, the smaller counts at half strength in log terms (its square root), as in the account group.
SAY_SO_KEYS = ("profile_words", "chat_accused")
SAY_SO_POWER = 0.5  # LR_RESEARCH s7/s8: the second of two overlapping parts at weight 0.5


def say_so_overlap(clues):
    both = [c for c in clues if c.key in SAY_SO_KEYS and c.lr > 1 and not c.proof]
    if len(both) < 2:
        return clues
    small = min(both, key=lambda c: c.lr)
    shrunk = replace(small, lr=small.lr ** SAY_SO_POWER,
                     why=small.why + " Counted at half strength: other players saying so is one kind of clue.")
    return [shrunk if c is small else c for c in clues]


def score(app, p):
    clues = gather(app, p)
    prior = prior_of(app)
    prob = combine(prior, [c.lr for c in clues])
    return Score(prob, band_of(prob, any(c.proof for c in clues)), clues, prior)


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
        "start": f"Start: {100 * sc.prior:.3g}% of casual players cheat (odds {odds_text(to_odds(sc.prior))})",
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
