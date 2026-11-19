"""Everything the toolbox says in TF2's chat, apart from duels and HoovyGPT's replies: the spam limit
(ChatLimit), the queue that sends lines one by one, and the lines themselves (EZ mode, the announcer,
player stats and summaries). ChatMixin is the part of the App that does this."""

import os
import re
import secrets
import threading
import time
import unicodedata
from collections import Counter, deque

from settings import HERE, save_config
from tf2_translator import language_code, translate_any
from game_log import PENDING
from player_flags import age_in_words, crit_text, fmt_age, fmt_hours, lobby_friends, profile_flags

# Words skipped when picking the one a player would type: "How Do I Quickscope?" -> quickscope.
SAY_NAME_SKIP = {"the", "a", "an", "of", "i", "is", "my", "just", "do", "and", "in", "to", "on", "at", "for", "how",
                 "why", "what", "who", "mr", "mrs", "ms", "dr", "sgt", "sir", "lord", "im", "its", "not", "no", "ttv",
                 "yt", "twitch", "fuck", "fucking", "shit"}


def say_name(name):
    """A name the way a player would type it in chat: one word, lowercase, no
    numbers, clan tags or decoration. xX_SampleSniper_Xx -> samplesniper,
    Example42K -> example, "Muffin, King of Ping" -> muffin."""
    n = unicodedata.normalize("NFKC", name)
    n = re.split(r"[,|│(]", n)[0] or n                                     # "Muffin, King of Ping", "S4MPL3 | Twitch"
    n = re.sub(r"^\s*[\[\{<][^\]\}>]{1,8}[\]\}>]", "", n)            # [ABC] clan tag
    n = re.sub(r"^(?:xx|x)[_\-. ]+|[_\-. ]+(?:xx|x)$", "", n.strip(), flags=re.I)  # xX_..._Xx
    n = re.sub(r"\d{2,}", " ", n)                                          # 123, 45, 99
    n = re.sub(r"[_\-. ]+", " ", n)                                       # separators
    n = "".join(c for c in n if c.isalnum() or c in " '")                  # ?!™♥ go, the letters close up
    words = []
    for w in n.split():
        if len(w) > 14:  # ElectricWheelchair: one word of the camel case
            words += re.findall(r"[A-ZА-Я]?[a-zа-я']+|[A-ZА-Я]+(?![a-zа-я])", w) or [w]
        else:
            words.append(w)
    for w in words:
        if len(w.strip("'")) >= 3 and w.lower().strip("'") not in SAY_NAME_SKIP:
            return w.strip("'").lower()
    return name.strip()[:14].lower() or name





def duel_name(name):
    """A player's name in duel messages: long names cut to 16 characters."""
    return name if len(name) <= 16 else name[:15].rstrip() + ".."


# Kills so embarrassing they get announced in chat ({victim}/{killer} filled in).
# Keyed by the weapon name TF2 logs (item_logname in items_game.txt, or the taunt kill's name).
HUMILIATIONS = {
    "fryingpan": "*CLANG* {victim} got PAN'D by {killer}",
    "golden_fryingpan": "{killer} wasted a GOLDEN PAN kill on {victim}",
    "holymackerel": "{victim} got FISH SLAPPED to death by {killer}",
    "unarmed_combat": "{victim} got slapped to death with a SEVERED ARM by {killer}",
    "ham_shank": "{victim} got HAMMED by {killer}",
    "skullbat": "{victim} got sent straight to HELL by {killer}",
    "club": "{victim} got chopped up like a coconut by {killer}",  # the Kukri, Sniper's machete
    "shovel": "{victim} got BURIED by {killer}. Shovel included",
    "market_gardener": "{victim} got shoveled by {killer}. Not even a garden",  # crits: GARDENED
    "holiday_punch": "{victim} got tickled to death by {killer}",
    "ball": "{victim} got killed by a BASEBALL",
    "wrap_assassin": "{victim} got killed by a Christmas ornament",
    "rainblower": "{victim} got burned to death by RAINBOWS",
    "cow_mangler": "{victim} got MANGLED by {killer}",
    "righteous_bison": "{victim} got killed by a laser gun from the 80s",
    "pomson": "{victim} got killed by a Pomson from {killer}. Somehow",
    "mantreads": "{victim} got STOMPED by {killer}",  # not seen in a log yet
    "bread_bite": "{victim} got eaten by BREAD",
    "lollichop": "{victim} got killed by a LOLLIPOP",
    "saxxy": "{victim} got killed by an AWARD",
    "nonnonviolent_protest": "{victim} got killed by a protest sign",
    "taunt_heavy": "{victim} got POOTIS POW'D by {killer}",
    "taunt_scout": "{victim} got knocked OUTTA THE PARK by {killer}",
    "taunt_soldier": "{killer} went KAMIKAZE just to take {victim} with them",
    "taunt_pyro": "{victim} got HADOUKEN'D by {killer}",
    "taunt_demoman": "{victim} got decapitated by a drunk Scotsman",
    "taunt_medic": "{victim} got a SPINAL TAP from Dr. {killer}",
    "taunt_sniper": "{victim} got shish-kebab'd by {killer}",
    "taunt_spy": "{victim} lost a fencing match to {killer}",
    "taunt_guitar_kill": "{victim} got a guitar smashed over the head by {killer}",
    "robot_arm_blender_kill": "{victim} got put through a BLENDER by {killer}",
    # not seen in a log yet, names from memory
    "armageddon": "{victim} got killed by RAINBOWS",
    "taunt_soldier_lumbricus": "{victim} got killed by a WORMS grenade",
    # Airblasted back by a Pyro (names seen in console.log). {their} is "my" when it's you.
    "deflect_rocket": "{victim} got killed by {their} own rocket, courtesy of {killer}",
    "deflect_promode": "{victim} ate {their} own pipe, returned to sender by {killer}",
    "deflect_arrow": "{victim} got shot with {their} own arrow by {killer}",
    # Knocked off a cliff or into a pit: TF2 credits whoever pushed them.
    "world": "{killer} YEETED {victim} into the abyss",
}
TAUNT_FALLBACK = "{victim} got TAUNT KILLED by {killer}"  # any other taunt_* kill
DEFLECT_FALLBACK = "{victim} got killed by {their} own shot, airblasted back by {killer}"  # other deflect_*
ANNOUNCER_ANNOUNCEMENT = "ANNOUNCER ON | calling out humiliations, first blood, gardens and rage-quits"
ANNOUNCE_MAX_AGE = 30   # seconds an announcement may wait behind your actions and HoovyGPT
CHAT_ECHO_WAIT = 8      # seconds for a sent line to show up in TF2's console, or it was refused
CHAT_REFUSED_PATH = os.path.join(HERE, "chat_refused.log")
# TF2's spam limit (ChatLimit) is shared with your own lines, so a busy chat can't get an answer
# per line. Instead of a backlog that gets further behind: one reply waits at a time, the newest
# chat line is next, and a reply this many seconds after its question is about old news.
AI_REPLY_MAX_AGE = 21


# Cheered after a Russia vs Ukraine kill by the killer's side.
COUNTRY_CHANTS = {"UA": "Slava Ukraini!", "RU": "Za pobedu!"}
# English country names by ISO code, generated from Windows' region list
# (.NET RegionInfo.EnglishName), with the long official ones shortened for chat.
COUNTRY_NAMES = dict(entry.split("=") for entry in (
    "AD=Andorra|AE=United Arab Emirates|AF=Afghanistan|AG=Antigua & Barbuda|AI=Anguilla|"
    "AL=Albania|AM=Armenia|AO=Angola|AR=Argentina|AS=American Samoa|AT=Austria|AU=Australia|"
    "AW=Aruba|AX=Åland Islands|AZ=Azerbaijan|BA=Bosnia & Herzegovina|BB=Barbados|BD=Bangladesh|"
    "BE=Belgium|BF=Burkina Faso|BG=Bulgaria|BH=Bahrain|BI=Burundi|BJ=Benin|BL=St. Barthélemy|"
    "BM=Bermuda|BN=Brunei|BO=Bolivia|BQ=Bonaire, Sint Eustatius and Saba|BR=Brazil|BS=Bahamas|"
    "BT=Bhutan|BW=Botswana|BY=Belarus|BZ=Belize|CA=Canada|CC=Cocos (Keeling) Islands|"
    "CD=Congo (DRC)|CF=Central African Republic|CG=Congo|CH=Switzerland|CI=Côte d’Ivoire|"
    "CK=Cook Islands|CL=Chile|CM=Cameroon|CN=China|CO=Colombia|CR=Costa Rica|"
    "CS=Serbia and Montenegro (Former)|CU=Cuba|CV=Cabo Verde|CW=Curaçao|CX=Christmas Island|"
    "CY=Cyprus|CZ=Czechia|DE=Germany|DJ=Djibouti|DK=Denmark|DM=Dominica|DO=Dominican Republic|"
    "DZ=Algeria|EC=Ecuador|EE=Estonia|EG=Egypt|ER=Eritrea|ES=Spain|ET=Ethiopia|FI=Finland|"
    "FJ=Fiji|FK=Falkland Islands|FM=Micronesia|FO=Faroe Islands|FR=France|GA=Gabon|"
    "GB=United Kingdom|GD=Grenada|GE=Georgia|GF=French Guiana|GG=Guernsey|GH=Ghana|GI=Gibraltar|"
    "GL=Greenland|GM=Gambia|GN=Guinea|GP=Guadeloupe|GQ=Equatorial Guinea|GR=Greece|GT=Guatemala|"
    "GU=Guam|GW=Guinea-Bissau|GY=Guyana|HK=Hong Kong SAR|HN=Honduras|HR=Croatia|HT=Haiti|"
    "HU=Hungary|ID=Indonesia|IE=Ireland|IL=Israel|IM=Isle of Man|IN=India|"
    "IO=British Indian Ocean Territory|IQ=Iraq|IR=Iran|IS=Iceland|IT=Italy|IV=Invariant Country|"
    "JE=Jersey|JM=Jamaica|JO=Jordan|JP=Japan|KE=Kenya|KG=Kyrgyzstan|KH=Cambodia|KI=Kiribati|"
    "KM=Comoros|KN=St. Kitts & Nevis|KP=North Korea|KR=Korea|KW=Kuwait|KY=Cayman Islands|"
    "KZ=Kazakhstan|LA=Laos|LB=Lebanon|LC=St. Lucia|LI=Liechtenstein|LK=Sri Lanka|LR=Liberia|"
    "LS=Lesotho|LT=Lithuania|LU=Luxembourg|LV=Latvia|LY=Libya|MA=Morocco|MC=Monaco|MD=Moldova|"
    "ME=Montenegro|MF=St. Martin|MG=Madagascar|MH=Marshall Islands|MK=North Macedonia|ML=Mali|"
    "MM=Myanmar|MN=Mongolia|MO=Macao SAR|MP=Northern Mariana Islands|MQ=Martinique|MR=Mauritania|"
    "MS=Montserrat|MT=Malta|MU=Mauritius|MV=Maldives|MW=Malawi|MX=Mexico|MY=Malaysia|"
    "MZ=Mozambique|NA=Namibia|NC=New Caledonia|NE=Niger|NF=Norfolk Island|NG=Nigeria|"
    "NI=Nicaragua|NL=Netherlands|NO=Norway|NP=Nepal|NR=Nauru|NU=Niue|NZ=New Zealand|OM=Oman|"
    "PA=Panama|PE=Peru|PF=French Polynesia|PG=Papua New Guinea|PH=Philippines|PK=Pakistan|"
    "PL=Poland|PM=St. Pierre & Miquelon|PN=Pitcairn Islands|PR=Puerto Rico|"
    "PS=Palestinian Authority|PT=Portugal|PW=Palau|PY=Paraguay|QA=Qatar|RE=Réunion|RO=Romania|"
    "RS=Serbia|RU=Russia|RW=Rwanda|SA=Saudi Arabia|SB=Solomon Islands|SC=Seychelles|SD=Sudan|"
    "SE=Sweden|SG=Singapore|SH=St Helena, Ascension, Tristan da Cunha|SI=Slovenia|"
    "SJ=Svalbard & Jan Mayen|SK=Slovakia|SL=Sierra Leone|SM=San Marino|SN=Senegal|SO=Somalia|"
    "SR=Suriname|SS=South Sudan|ST=São Tomé & Príncipe|SV=El Salvador|SX=Sint Maarten|SY=Syria|"
    "SZ=Eswatini|TC=Turks & Caicos Islands|TD=Chad|TG=Togo|TH=Thailand|TJ=Tajikistan|TK=Tokelau|"
    "TL=Timor-Leste|TM=Turkmenistan|TN=Tunisia|TO=Tonga|TR=Türkiye|TT=Trinidad & Tobago|"
    "TV=Tuvalu|TW=Taiwan|TZ=Tanzania|UA=Ukraine|UG=Uganda|UM=U.S. Outlying Islands|"
    "US=United States|UY=Uruguay|UZ=Uzbekistan|VA=Vatican City|VC=St. Vincent & Grenadines|"
    "VE=Venezuela|VG=British Virgin Islands|VI=U.S. Virgin Islands|VN=Vietnam|VU=Vanuatu|"
    "WF=Wallis & Futuna|WS=Samoa|XK=Kosovo|YE=Yemen|YT=Mayotte|ZA=South Africa|ZM=Zambia|"
    "ZW=Zimbabwe"
).split("|"))
COUNTRY_NAMES.update(US="USA", GB="UK", KR="South Korea", HK="Hong Kong")
CHAT_LIMIT = 127  # bytes TF2 accepts in one chat message


class ChatLimit:
    """TF2's chat spam limit, as the server runs it (CBasePlayer::CanPlayerTalk and
    ArePlayerTalkMessagesAvailable in Valve's source-sdk-2013, src/game/server/player.cpp):
    0.66 s between lines, plus two token buckets (sv_chat_bucket_size_tier1 4, a line per
    sv_chat_seconds_per_msg_tier1 3 s; tier2 30, a line per 10 s). A refused line still
    costs a token, so the scanner works out when the next line gets through and only
    sends then: a short burst of 3, then one every 3 seconds."""
    GAP = 0.66
    MARGIN = 0.15  # tokens kept spare, and GAP_MARGIN seconds, for lag between us and the server
    GAP_MARGIN = 0.15

    def __init__(self):
        # what the server starts a player with (CBasePlayer's constructor)
        self.talked = self.attempted = time.time()
        self.tier1, self.tier2 = 1.0, 10.0

    def note(self, at=None):
        """A chat line reached the server: the scanner's, or one you typed."""
        at = time.time() if at is None else at
        elapsed = at - self.attempted
        self.attempted = self.talked = at
        per_msg = 3.0 - min(0.0, self.tier1)
        self.tier1 = max(-2.5, min(4.0, self.tier1 + max(0.0, elapsed / per_msg)) - 1.0)
        if self.tier1 > 0:
            self.tier2 = max(0.0, min(30.0, self.tier2 + max(0.0, elapsed / 10.0)) - 1.0)

    def refused(self, at=None):
        """A line never showed up, so the server turned it down and our count was too hopeful:
        slow down as if nothing is left, and let the allowance build up again from now."""
        self.attempted = time.time() if at is None else at
        self.tier1 = min(self.tier1, 1.0)

    def wait(self, at=None):
        """Seconds until a line sent would get through (0: now)."""
        at = time.time() if at is None else at
        need = 2.0 + self.MARGIN  # tokens before the line, as the server takes 1 and wants > 1 left
        per_msg = 3.0 - min(0.0, self.tier1)
        ready = max(self.talked + self.GAP + self.GAP_MARGIN,
                    self.attempted + (need - self.tier1) * per_msg,
                    self.attempted + (need - self.tier2) * 10.0)
        return max(0.0, ready - at)


def fits(text, limit):
    return len(text.encode("utf-8")) <= limit


# Flags as said in chat: in words ("VAC banned 36 days ago"), in this order.
CHAT_SHORTER = [
    (re.compile(r"copied someone's name \(bot\)"), "name-stealing bot"),
    (re.compile(r"^1 VAC ban \+ 1 game ban \((\d+)d ago\)$"), r"VAC + game banned \1 days ago"),
    (re.compile(r"^1 (VAC|game) ban \((\d+)d ago\)$"), r"\1 banned \2 days ago"),
    (re.compile(r"\b([2-9]|\d\d+) (VAC|game) ban\b"), r"\1 \2 bans"),
    (re.compile(r" \((\d+)d ago\)$"), r", last \1 days ago"),
    (re.compile(r"\b1 days ago"), "1 day ago"),
    (re.compile(r"\b0 days ago"), "today"),
    (re.compile(r"^(\d+ server bans?): (.+?)(?: \([^()]*\))?$"), r"\1 (\2)"),  # reasons kept, servers dropped
    (re.compile(r"^on (\d+) lists \((cheater|exploiter)[^)]*\)$"), r"on \1 cheater lists"),
    # The same words and numbers as Stats (say_stats), with how rarely luck does it.
    (re.compile(r"^\d+% crit kills \((\d+)/(\d+)\), possible crit hack$"),
     lambda m: crit_text((int(m[2]), int(m[1])))),
    (re.compile(r"^(\d+% headshots) \((\d+)/(\d+) sniper kills?\)$"), r"\1 this match (\2 of \3 sniper kills)"),
]
# Left out of chat: the stats already say it, or it's your own note rather than evidence.
LIVE_STAT_RE = re.compile(r"% (headshots|crit kills) \(")
CHAT_SKIP_RE = re.compile(r"^(only \d+h in TF2|new account|marked by you.*|friends in lobby.*)$")


def chat_line(p, team, flags, limit=CHAT_LIMIT):
    """One chat message summing up a player, trimmed to fit TF2's chat limit.
    To make room it drops details in brackets, then shortens a long name, and
    only then drops the least serious flags. Hours and account age are left
    out once there's a serious flag (bans, cheater lists): those say it all."""
    texts, serious = [], False
    for severity, text in sorted(flags, reverse=True):
        if not CHAT_SKIP_RE.match(text):
            serious |= severity >= 2
            for pattern, short in CHAT_SHORTER:
                text = pattern.sub(short, text)
            texts.append(text)
    # Hours and account age in words, with the short form as a fallback when a line gets too long.
    words, short = [], []
    hours, age = fmt_hours(p.hours), fmt_age(p.summary)
    if hours != "…" and not serious:
        words.append("hours hidden" if hours == "hidden" else f"{int(p.hours):,} hours in TF2")
        short.append("hours hidden" if hours == "hidden" else f"{hours} TF2")
    if age not in ("…", "?") and not serious:
        words.append(f"account {age_in_words(p.summary)} old")
        short.append(f"account {age}")
    if not texts and p.bans is not None:
        texts.append("clean: no bans, not on any cheater list")
    def no_details(t):
        return re.sub(r" \([^()]*\)$", "", t)  # e.g. the server list after a ban reason

    def build(name, shown, stats):
        parts = [f"{name}{f' ({team})' if team else ''}"]
        if shown:
            parts.append(" | ".join(shown))
        if stats:
            parts.append(", ".join(stats))
        return " | ".join(parts)

    names = [p.name] + ([p.name[:15] + "…"] if len(p.name) > 16 else [])
    # The most serious flag's details (what someone was banned for: "Aimbot") matter
    # more than how many other flags fit, so they're only dropped as a last resort.
    for keep_details in (True, False):
        for n in range(len(texts), 0, -1):
            variants = ((texts[:n], texts[:1] + [no_details(t) for t in texts[1:n]]) if keep_details else
                        ([no_details(t) for t in texts[:n]],))
            for stats in (words, short):
                for name in names:
                    for shown in variants:
                        line = build(name, shown, stats)
                        if fits(line, limit):
                            return line
    if not texts:  # nothing to drop: only the name and stats
        for stats in (words, short):
            for name in names:
                if fits(line := build(name, [], stats), limit):
                    return line
    # Even the most serious flag alone is too long: cut it short rather than drop it.
    line = build(names[-1], [no_details(t) for t in texts[:1]], short)
    if fits(line, limit):
        return line
    while not fits(line + "…", limit):
        line = line[:-1]
    return line + "…"


KICK_RE = re.compile(r"^\s*!kick\b\s*(?P<name>.*?)\s*$", re.I)
WHO_RE = re.compile(r"^\s*!who\b\s*(?P<name>.*?)\s*$", re.I)
TRANSLATE_RE = re.compile(r"^\s*!speak\b\s*(?P<lang>\S*)\s*(?P<text>.*?)\s*$", re.I)


def split_chat(text, limit, max_parts):
    """Splits text into chat messages of at most `limit` bytes, at spaces where
    possible; whatever doesn't fit in `max_parts` messages is cut off."""
    parts = []
    while text and len(parts) < max_parts:
        if fits(text, limit):
            parts.append(text)
            break
        cut = len(text.encode("utf-8")[:limit].decode("utf-8", "ignore"))
        space = text.rfind(" ", 0, cut)
        cut = space if space > cut // 2 else cut
        parts.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    return parts


def quoted(name):
    """A player's name in announcements, so it can't blend into the sentence around it."""
    return f"'{name}'"


def _host():
    return secrets.randbelow(254) + 1  # no .0 or .255


def _octet():
    return secrets.randbelow(256)


# Blocks no one on the internet can have: private, shared and reserved ones (none is "global").
# Nothing starting with 192 or 172.
FAKE_IP_BLOCKS = (
    lambda: f"10.{_octet()}.{_octet()}.{_host()}",                      # private (RFC 1918)
    lambda: f"100.{64 + secrets.randbelow(64)}.{_octet()}.{_host()}",   # ISPs' shared space (RFC 6598)
    lambda: f"169.254.{_host()}.{_host()}",                             # link-local (RFC 3927)
    lambda: f"198.{18 + secrets.randbelow(2)}.{_octet()}.{_host()}",    # benchmarking (RFC 2544)
    lambda: f"{secrets.choice(('198.51.100', '203.0.113'))}.{_host()}",  # documentation (RFC 5737)
    lambda: f"{240 + secrets.randbelow(15)}.{_octet()}.{_octet()}.{_host()}",       # reserved (RFC 1112)
)
_last_ip_block = [None]


def fake_ipv4():
    """A random IPv4 that looks real but can never belong to anyone. Each comes from a different
    block than the one before, so lines for one team jump all over the place."""
    block = secrets.choice([b for b in FAKE_IP_BLOCKS if b is not _last_ip_block[0]])
    _last_ip_block[0] = block
    return block()


def console_safe(text):
    """Text that can't break out of a quoted console argument (a player could
    pick a name like `x"; disconnect`)."""
    return text.replace('"', "'").replace(";", ",").replace("\n", " ").replace("\r", " ")


class ChatMixin:
    def ez_kill(self, m):
        """With EZ mode on, every kill you make queues "ez <victim>" for chat."""
        me = self.players.get(self.me)
        if not self.cfg["ez_mode"] or not me or m["killer"] != me.name or m["victim"] == me.name:
            return
        self.announce_chat(f"ez {say_name(m['victim'])}")

    def humiliation(self, m):
        """With the announcer on, anyone killed by a pan, a fish, a ham or a taunt
        gets announced in chat. When it's you, it's said in first person."""
        if not self.cfg["announcer"] or m["killer"] == m["victim"]:
            return
        weapon, victim, killer = m["weapon"], quoted(m["victim"]), quoted(m["killer"])
        if weapon == "market_gardener" and m["crit"]:
            return  # a real garden: ez_extras says "GARDENED"
        template = HUMILIATIONS.get(weapon) or (TAUNT_FALLBACK if weapon.startswith("taunt_") else
                                                DEFLECT_FALLBACK if weapon.startswith("deflect_") else None)
        if not template:
            return
        me = self.players.get(self.me)
        if me and m["victim"] == me.name:
            # "I got PAN'D by Hans", "Hans wasted a GOLDEN PAN kill on me", "my own rocket"
            template = re.sub(r"\{victim\}(?= (got|lost|ate) )", "I", template).replace("{victim}", "me")
            self.announce_chat(template.format(killer=killer, their="my"))
        else:
            self.announce_chat(template.format(victim=victim, killer=killer, their="their"))

    def ez_extras(self, m):
        """The announcer's other kill lines: first blood of the map and gardens."""
        if not self.cfg["announcer"] or m["killer"] == m["victim"]:
            return
        if self.first_blood_open:
            self.announce_chat(f"FIRST BLOOD: {quoted(m['killer'])} killed {quoted(m['victim'])}")
        if m["weapon"] == "market_gardener" and m["crit"]:
            self.announce_chat(f"{quoted(m['killer'])} GARDENED {quoted(m['victim'])}!")

    def check_rage_quits(self):
        """Players gone from TF2's scoreboard within 30 s of dying get called out
        (announcer). TF2 doesn't log leaves, but its scoreboard drops them in seconds."""
        connected = set(self.board)
        gone = self.connected_before - connected
        self.connected_before = connected
        if not self.cfg["announcer"]:
            return
        for sid in gone:
            died_at, killer = self.last_death.pop(sid, (0, ""))
            p = self.players.get(sid)
            if p and sid != self.me and time.time() - died_at <= 30:
                self.announce_chat(f"{quoted(p.name)} ragequit after dying to {quoted(killer)}")

    def queue_chat(self, text, command="say"):
        """Your own actions (buttons) and HoovyGPT's own messages: these go first."""
        self.chat_queue.append((command, text))
        if not self.chat_sending:
            self.send_next_chat()

    def announce_chat(self, text, command="say"):
        """Lines the scanner says by itself (kills, duels): these go when nothing else
        wants the spam limit's room, and are dropped once they're too old to matter."""
        self.announce_queue.append((time.time(), command, text))
        if not self.chat_sending:
            self.send_next_chat()

    def send_next_chat(self):
        """Posts one waiting message as soon as TF2's spam limit lets it through (see ChatLimit),
        so a multi-kill becomes several lines instead of a flood TF2 would block. The order is
        your own actions, then HoovyGPT's reply, then announcements. Old replies and old
        announcements are thrown away here, as they'd only be about something long gone."""
        now = time.time()
        if self.ai_reply and (not self.ai_on or self.ai_muted or now - self.ai_reply_at > AI_REPLY_MAX_AGE):
            self.ai_reply = []
            self.ask_waiting_ai()
        while self.announce_queue and now - self.announce_queue[0][0] > ANNOUNCE_MAX_AGE:
            self.announce_queue.popleft()
        if not self.chat_queue and not self.ai_reply and not self.announce_queue:
            self.chat_sending = False
            return
        self.chat_sending = True
        # This also covers lines you type yourself: a "!duel" answer sent right after
        # the "!duel" never showed up.
        if (wait := self.chat_limit.wait()) > 0:
            self.root.after(int(wait * 1000) + 20, self.send_next_chat)
            return
        if self.chat_queue:
            command, text = self.chat_queue.popleft()
        elif self.ai_reply:
            command, text = self.ai_reply.pop(0)
        else:
            _, command, text = self.announce_queue.popleft()
            # TF2 allows only about one line per 10 seconds once a busy chat used up its allowance,
            # so translations waiting together go out as one line: "A said: x | B said: y".
            while (" said: " in text and self.announce_queue and self.announce_queue[0][1] == command
                   and " said: " in self.announce_queue[0][2]
                   and fits(f"{text} | {self.announce_queue[0][2]}", CHAT_LIMIT)):
                text += " | " + self.announce_queue.popleft()[2]
        self.ask_waiting_ai()
        if self.rcon_state == "connected":
            self.commands.put(f'{command} "{console_safe(text)}"')
            self.chat_sent.append(console_safe(text).strip())
            self.chat_unconfirmed.append((time.time(), console_safe(text).strip()))
            self.chat_sent_count += 1
            self.chat_limit.note()
        self.root.after(0, self.send_next_chat)

    def note_my_chat(self, name, msg, team):
        """A chat line from you. One the scanner sent is proof it got through; any other
        you typed yourself in TF2, which uses up the same spam allowance."""
        me = self.players.get(self.me)
        if not me or name != me.name:
            return
        msg = msg.strip()
        for entry in self.chat_unconfirmed:
            # startswith: the server may cut a line short at its own limit
            if entry[1] == msg or (len(msg) >= 20 and entry[1].startswith(msg)):
                self.chat_unconfirmed.remove(entry)
                return
        if msg not in self.chat_sent:
            self.chat_limit.note()

    def check_refused_chat(self):
        """Every line the scanner sends should come back through TF2's console. One that doesn't
        within CHAT_ECHO_WAIT was refused, most likely by the spam limit. These are counted on
        screen and written to chat_refused.log, which shows if ChatLimit matches the real server.
        A line that wasn't sent to a server at all (no players around) says nothing, so it's skipped."""
        now = time.time()
        while self.chat_unconfirmed and now - self.chat_unconfirmed[0][0] > CHAT_ECHO_WAIT:
            sent_at, text = self.chat_unconfirmed.popleft()
            if self.rcon_state != "connected" or not self.players:
                continue
            self.chat_refused_count += 1
            limit = self.chat_limit
            try:
                with open(CHAT_REFUSED_PATH, "a", encoding="utf-8") as f:
                    f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(sent_at))} "
                            f"tier1={limit.tier1:.2f} tier2={limit.tier2:.2f} sent={self.chat_sent_count} {text}\n")
            except OSError:
                pass
            limit.refused(now)
            self.dirty = True

    def country_of(self, sid):
        p = self.players.get(sid)
        return (p.summary or {}).get("loccountrycode") if p else None

    def country_beef_kill(self, m):
        """With the country toggle on, a kill between the two country_beef countries
        is announced with this match's score, killer's country first."""
        if not self.cfg["country_beef_auto"]:
            return
        killer, victim = self.sid_by_name(m["killer"]), self.sid_by_name(m["victim"])
        if not killer or not victim or killer == victim:
            return
        kc, vc = self.country_of(killer), self.country_of(victim)
        if {kc, vc} != set(self.cfg["country_beef"]):
            return
        score = Counter()
        for (k, v), n in self.pair_kills.items():  # already includes this kill
            score[(self.country_of(k), self.country_of(v))] += n

        # 'Ivan' (RU) killed 'Taras' (UA) | Russia 1 - 0 Ukraine. Za pobedu!
        chant = COUNTRY_CHANTS.get(kc)
        self.announce_chat(f"{quoted(self.players[killer].name)} ({kc}) killed {quoted(self.players[victim].name)} ({vc}) | "
                        f"{COUNTRY_NAMES.get(kc, kc)} {score[(kc, vc)]} - {score[(vc, kc)]} {COUNTRY_NAMES.get(vc, vc)}"
                        + (f". {chant}" if chant else ""))

    def toggle_country_beef(self):
        self.cfg["country_beef_auto"] = not self.cfg["country_beef_auto"]
        save_config(self.cfg)

    def toggle_ez_mode(self):
        self.cfg["ez_mode"] = not self.cfg["ez_mode"]
        save_config(self.cfg)

    def toggle_translate_to_chat(self):
        self.cfg["translate_to_chat"] = not self.cfg["translate_to_chat"]
        save_config(self.cfg)

    def translate_command(self, name, msg, team):
        """Answers "!speak <language> <message>" typed by anyone (you too): says the message in
        that language as "<name> said: ...", like Translate to chat does, in team chat when it was
        typed there. Nothing is said for a language it doesn't know; you see that here only."""
        if not (m := TRANSLATE_RE.match(msg)) or not self.cfg["translate_command"]:
            return
        if self.sid_by_name(name) in self.cfg["speak_muted"]:
            return  # muted by you: nothing is said, and nothing tells them
        code = language_code(m["lang"])
        if not code or not m["text"]:
            self.notify(f"{name}'s !speak: " + (f"no language called '{m['lang']}'" if m["text"] else
                                                "type !speak <language> <message>"))
            return
        if self.rcon_state != "connected":
            return
        threading.Thread(target=self.translate_for_chat, args=(name, m["text"], code, team), daemon=True).start()

    def translate_for_chat(self, name, text, code, team):
        """Background thread: the translation goes to say_translated on the Tk thread."""
        try:
            self.events.put(("translate_say", name, translate_any(text, code)[0], team))
        except Exception as e:
            print(f"!speak from {name} failed: {e!r}", flush=True)
            self.events.put(("translate_failed", name, str(e)))

    def say_translated(self, name, text, team):
        if not self.cfg["translate_command"]:  # switched off while it was being translated
            return
        for part in split_chat(f"{name} said: {text}", CHAT_LIMIT, 2):
            self.announce_chat(part, "say_team" if team else "say")

    def who_command(self, name, msg, team):
        """Answers "!who <name>" typed by anyone (you too) with up to three messages about that
        player: the line the Summary button says, the Stats line (left out while they have no
        stats this match), and for a cheater their SteamHistory link, where anyone can check the bans. Part of a name works, like with !duel; when it fits nobody or
        several players, it says so instead. Answered in team chat when it was typed there."""
        if not (m := WHO_RE.match(msg)) or not self.cfg["who_command"] or self.rcon_state != "connected":
            return
        command = "say_team" if team else "say"
        wanted = m["name"].strip("'\"@").lower()
        if not wanted:
            self.announce_chat("[WHO] Type !who <name>. Part of a name works", command)
            return
        players = list(self.players.values())
        matches = [p for p in players if p.name.lower() == wanted] or [p for p in players if wanted in p.name.lower()]
        if not matches:
            self.announce_chat(f"[WHO] nobody here is called '{wanted}'", command)
        elif len(matches) > 1:
            names = ", ".join(f"'{p.name}'" for p in matches[:3])
            self.announce_chat(f"[WHO] '{wanted}' matches {names}. Type more of the name", command)
        else:
            self.announce_chat(self.chat_text(matches[0], country=True), command)
            if stats := self.stats_text(matches[0]):
                self.announce_chat(stats, command)
            if proof := self.history_line(matches[0]):
                self.announce_chat(proof, command)

    def history_line(self, p):
        """For a player the toolbox counts as a cheater: a chat line with their SteamHistory page,
        where everyone can see the bans that prove it. None for everyone else."""
        import cheat_score
        if p.sid == self.me or not cheat_score.is_cheater(self, p):
            return None
        name = p.name if len(p.name) <= 24 else p.name[:23] + "…"
        return f"{name} | bans: https://steamhistory.net/id/{p.sid}"

    def toggle_who_command(self):
        """The !who pill on the Chat page."""
        self.cfg["who_command"] = not self.cfg["who_command"]
        save_config(self.cfg)

    def toggle_speak_mute(self):
        """Mute !speak / Unmute !speak in a player's panel: their !speak is ignored from now on,
        also after a restart and in later matches. What they had waiting to be said is dropped."""
        p = self.players.get(self.selected)
        if not p or p.sid == self.me:
            return
        was_muted = p.sid in self.cfg["speak_muted"]
        # A new list each time: the setting's default is never changed in place.
        muted = self.cfg["speak_muted"] = [sid for sid in self.cfg["speak_muted"] if sid != p.sid] + [p.sid] * (not was_muted)
        if not was_muted:
            self.announce_queue = deque(e for e in self.announce_queue if not e[2].startswith(f"{p.name} said: "))
        save_config(self.cfg)
        self.notify(f"{p.name}'s !speak is {'muted' if p.sid in muted else 'back on'}")

    def unmute_all_speak(self):
        """The !speak: muted players card on the Chat page: everyone can use !speak again."""
        count = len(self.cfg["speak_muted"])
        self.cfg["speak_muted"] = []
        save_config(self.cfg)
        self.notify(f"Unmuted {count} player{'s' * (count != 1)}" if count else "Nobody is muted")

    def toggle_translate_command(self):
        """The !speak pill on the Chat page: !speak stops working until it's clicked again."""
        self.cfg["translate_command"] = not self.cfg["translate_command"]
        save_config(self.cfg)
        on = self.cfg["translate_command"]
        if not on:  # translations still waiting to be said are dropped too
            self.announce_queue = deque(e for e in self.announce_queue if " said: " not in e[2])
        self.notify(f"!speak {'on' if on else 'off'}")

    def translated(self, entry):
        """A new line in the translator: said in chat while Translate to chat is on.
        Your own lines (and HoovyGPT's) are skipped, and so are failed translations,
        which still hold the Cyrillic and would come back to be translated again."""
        me = self.players.get(self.me)
        if self.cfg["translate_to_chat"] and entry["lang"] != "?" and not (me and entry["name"] == me.name):
            self.say_translation(entry)

    def toggle_announcer(self):
        self.cfg["announcer"] = not self.cfg["announcer"]
        save_config(self.cfg)
        if self.cfg["announcer"]:
            self.queue_chat(ANNOUNCER_ANNOUNCEMENT)

    # --- actions -----------------------------------------------------------------------

    def votekick(self):
        """The Votekick button on the Players tab: for the selected player."""
        p = self.players.get(self.selected)
        if p:
            self.votekick_player(p)

    def votekick_player(self, p):
        """Starts a vote to kick p, or copies the command without RCON."""
        if self.team_of(p) == "ENEMY":
            self.notify("Votes only work on your own team")
            return
        cmd = f'callvote kick "{p.userid} cheating"'
        if self.rcon_state == "connected":
            self.commands.put(cmd)
            self.notify("Vote started (only works on your own team)")
        else:
            self.copy(cmd)
            self.notify("RCON not connected: command copied, paste it in the TF2 console")

    def kick_command(self, name, msg, team):
        """"!kick <name>" typed by you (nobody else): starts a vote to kick that player for cheating.
        Part of a name works, like !duel; you can name yourself too. Votes only work on your own team. What went wrong shows
        on your screen only (over the game: you typed it there), never in chat. A vote that started
        only says so in the title bar, like the Votekick button."""
        me = self.players.get(self.me)
        if not (m := KICK_RE.match(msg)) or not me or name != me.name:
            return
        p, error = self.find_player(m["name"].strip("'\"@"), "KICK")
        if error:
            self.toast.show(error.replace("[KICK] ", "!kick: "), 1)
        elif self.team_of(p) == "ENEMY":
            self.toast.show(f"!kick: {p.name} is on the other team (votes only work on your own team)", 1)
        else:
            self.votekick_player(p)

    def chat_text(self, p, country=False):
        """The Say in chat line for one player: their flags and stats, short enough for TF2's chat.
        country=True (for !who) adds the country on their Steam profile after their team,
        when they set one: "Hank (RED, Russia) | ..."."""
        team = self.team_color(p)
        if country:
            where = self.country_of(p.sid) or ""
            team = ", ".join(filter(None, (team, COUNTRY_NAMES.get(where, where))))
        flags = self.flags.get(p.sid, []) + profile_flags(p.profile)
        listed = self.lists.get(p.sid)
        sources = (listed or {}).get("sources", [])
        if len(sources) > 1:
            # Chat names the lists, which people recognize; the panel just counts them.
            attrs = ", ".join(sorted(listed["attributes"]))
            shown = ", ".join(sources[:3]) + (f" +{len(sources) - 3} more" if len(sources) > 3 else "")
            counted, named = f"on {len(sources)} lists (", f"on {shown} lists ({attrs})"
            flags = [(s, named if t.startswith(counted) else t) for s, t in flags]
        # Flagged headshot/crit rates from this match go first: they show what the
        # player is doing right now, which nobody can wave away as an old ban.
        flags = [(4 if s >= 2 and LIVE_STAT_RE.search(t) else s, t) for s, t in flags]
        return chat_line(p, team, flags)

    def say_stats(self):
        """Posts what's known about the player this match in one message: class,
        headshots, crits, gardens, killstreak and favorite weapon, leaving out what
        they have none of and dropping from the end until it fits. The log only
        records kills, so shots fired and misses can't be counted."""
        p = self.players.get(self.selected)
        if not p:
            return
        text = self.stats_text(p)
        if text:
            self.post(text)
        else:
            self.notify("No kills seen for them yet")

    def stats_text(self, p):
        """The Stats line for a player (see say_stats), or None while nothing is known."""
        parts = [self.player_class(p)] if self.player_class(p) else []
        sniper_kills, headshots = self.kills.get(p.sid, (0, 0))
        if headshots:
            parts.append(f"{headshots}/{sniper_kills} headshots ({round(100 * headshots / sniper_kills)}%)")
        # Only weapons that crit at random count, as for the crit hack flag in Summary: melee
        # crits from a Kritz or a Market Garden, and headshots, would make anyone look lucky.
        kills, crits = self.crits.get(p.sid, (0, 0))
        if crits > 0:
            parts.append(crit_text((kills, crits)))
        gardens = self.gardens.get(p.sid, 0)
        if gardens:
            parts.append(f"{gardens} garden{'s' if gardens > 1 else ''}")
        current, best = self.player_streak(p)
        if best and not current:
            parts.append(f"best killstreak {best}")
        elif best:
            parts.append(f"{current} killstreak" + (f" (best {best})" if best > current else ""))
        favorite = re.sub(r"^1 kills ", "1 kill ", self.favorite_weapon(p, "{kills} kills with {name}"))
        if favorite:
            parts.append(favorite)
        if not parts:
            return None
        team = self.team_color(p)
        tag = f" ({team})" if team else ""
        name = p.name
        while not fits(f"{name}{tag} | {' | '.join(parts)}", CHAT_LIMIT) and len(name) > 8:
            name = name[:-2] + "…"
        while len(parts) > 1 and not fits(f"{name}{tag} | {' | '.join(parts)}", CHAT_LIMIT):
            parts.pop()  # the favorite weapon goes first, then the killstreak...
        return f"{name}{tag} | {' | '.join(parts)}"

    def say_lobby_summary(self):
        """The Lobby summary button: posts lobby_summary_text, or says why there's nothing yet."""
        text = self.lobby_summary_text()
        if not text:
            self.notify("No scores yet (needs -g15 and some kills)")
            return
        self.post(text)

    def lobby_summary_text(self):
        """This match's leaderboards (the Match highlights line) in one chat message, dropping the
        least important entries until it fits, or None while nothing is known. All from TF2's
        scoreboard and the kill feed."""
        players = list(self.players.values())
        name = {p.sid: p.name for p in players}

        def board(field):  # {sid: value} for players TF2's scoreboard has a value for
            return {p.sid: self.board_int(p.sid, field) for p in players
                    if self.board_int(p.sid, field)}

        def leader(scores, fmt):
            if not scores:
                return None
            sid = max(scores, key=scores.get)
            return fmt(name[sid], scores[sid]) if scores[sid] else None

        kills, deaths = board("m_iScore"), board("m_iDeaths")
        streaks = {p.sid: self.player_streak(p)[1] for p in players if self.player_streak(p)[1]}
        snipers = {p.sid: self.kills[p.sid] for p in players
                   if self.kills.get(p.sid, (0, 0))[0] >= self.cfg["headshot_min_kills"]}
        hs = {sid: s[1] / s[0] for sid, s in snipers.items()}
        gardens = {p.sid: self.gardens[p.sid] for p in players if self.gardens.get(p.sid)}

        def score(sid):
            return f"{kills.get(sid, 0)}-{deaths.get(sid, 0)}"

        # MVP: most kills, fewest deaths breaking ties. Worst: most deaths, unless that's the MVP.
        mvp = max(kills, key=lambda sid: (kills[sid], -deaths.get(sid, 0)), default=None)
        worst = max((sid for sid in deaths if sid != mvp), key=lambda sid: (deaths[sid], -kills.get(sid, 0)),
                    default=None)
        parts = [p for p in (
            mvp and f"MVP: {name[mvp]} ({score(mvp)})",
            worst and f"worst: {name[worst]} ({score(worst)})",
            leader(streaks, lambda n, v: f"best streak: {n} ({v})"),
            leader(gardens, lambda n, v: f"most gardens: {n} ({v})"),
            leader(hs, lambda n, v: f"best sniper: {n} ({round(100 * v)}% hs)"),
        ) if p]
        if not parts:
            return None
        while not fits(" | ".join(parts), CHAT_LIMIT) and len(parts) > 1:
            parts.pop()
        return " | ".join(parts)

    def say_kill_race(self):
        """The Players page's Kill race button: posts the same line as !top (info_commands.top_line)."""
        line = self.top_line(unknown=None)
        if not line:
            self.notify("No scores yet (needs -g15)")
            return
        self.post(line)

    def say_translation(self, entry=None):
        """Says a translated chat message (the newest one by default) for everyone,
        in team chat when it was said there."""
        by_itself = entry is not None
        overlay = getattr(self, "translator", None) and self.translator[0]
        entry = entry or (overlay.history[-1] if overlay and overlay.history else None)
        if not entry:
            self.notify("Nothing translated yet")
            return
        text = f"{entry['name']} said: {entry['text']}"
        if self.rcon_state != "connected":
            self.copy(text)
            self.notify("RCON not connected: copied, paste it in chat")
            return
        # Translate to chat passes the entry and runs by itself; the button is your own action.
        say = self.announce_chat if by_itself else self.queue_chat
        for part in split_chat(text, CHAT_LIMIT, 2):
            say(part, "say_team" if entry["team"] else "say")
        self.notify("Posted in chat")

    def say_ip(self):
        """A random address from fake_ipv4. Their country (public on their Steam
        profile) goes with it; nothing more precise does."""
        self.post(self.ip_line(self.players[self.selected]))

    def fake_ip_of(self, p):
        """The fake IPv4 this player gets (the Send fake IP button, !ip): drawn by fake_ipv4 the
        first time, then the same one for as long as this match lasts. Kept in memory only:
        new_match and a disconnect forget them all, and nothing is ever saved."""
        key = str(p.sid)
        if key not in self.fake_ips:
            self.fake_ips[key] = fake_ipv4()
        return self.fake_ips[key]

    def ip_line(self, p):
        country = COUNTRY_NAMES.get(self.country_of(p.sid) or "", "")
        return f"{p.name} | {country + ' | ' if country else ''}IPv4 {self.fake_ip_of(p)}"

    def say_friends(self):
        """Posts who in this lobby the selected player is friends with."""
        p = self.players.get(self.selected)
        if not p:
            return
        text, reason = self.friends_text(p)
        if text:
            self.post(text)
        else:
            self.notify(reason)

    def friends_text(self, p):
        """(the chat line naming who in this lobby p is friends with, None), or (None, why not)."""
        friends = lobby_friends(p, list(self.players.values()))
        if not friends:
            loading = any(q.friends == PENDING for q in self.players.values())
            return None, ("Friend lists are still loading" if loading
                          else "No friends of theirs in this lobby (or their list is private)")

        def tagged(q):
            team = self.team_color(q)
            return f"{q.name} ({team})" if team else q.name

        # Drop names from the end until it fits one chat message.
        for shown in range(len(friends), 0, -1):
            more = f" +{len(friends) - shown} more" if shown < len(friends) else ""
            text = f"{tagged(p)} is friends with {', '.join(tagged(q) for q in friends[:shown])}{more}"
            if fits(text, CHAT_LIMIT):
                break
        return text, None

    def post(self, text):
        """Says text in chat over RCON, or copies it when RCON isn't connected."""
        if self.rcon_state == "connected":
            self.queue_chat(text)
            self.notify("Posted in chat")
        else:
            self.copy(text)
            self.notify("RCON not connected: copied, paste it in chat")

    def say_in_chat(self):
        """Post their summary: the summary line, and for a cheater a second line with their
        SteamHistory link (history_line). Without RCON both are copied as one line."""
        p = self.players.get(self.selected)
        if not p:
            return
        text, proof = self.chat_text(p), self.history_line(p)
        if proof and self.rcon_state == "connected":
            self.queue_chat(text)
        self.post(proof if proof and self.rcon_state == "connected" else " | ".join(filter(None, (text, proof))))
