"""Chat commands anyone can type for information about the lobby, answered by the toolbox:
!check <name> (class and health), !check all (the other team's classes), !stats (this match),
!mystats [name] (lifetime TF2 stats from Steam), !hours <name>, !cheaters, !roast <name>, !ip <name>
and !help. Each can be switched off on the Chat page."""

import random
import re
import threading
import time
from collections import Counter, deque

from chat import fits, CHAT_LIMIT
from game_log import CLASS_MAX_HEALTH, PENDING
from lookups import TF2_CLASSES, tf2_stats_lookup
from player_flags import age_in_words
from settings import save_config

# command -> (what !help and the Chat page call it, what it does)
INFO_COMMANDS = {
    "check": ("!check <name>", "A player's class and health. !check all: the other team's classes."),
    "stats": ("!stats", "This match: the map, kills per team, the best and the worst player, headshots, "
                        "backstabs and crits."),
    "mystats": ("!mystats [name]", "Anyone can type it; the toolbox answers from your account. Alone it "
                                   "posts the lifetime TF2 stats of whoever typed it (hours, kills, main class, "
                                   "best single-life records), with a name it posts that player's. Uses your Steam "
                                   "API key; players with private game details can't be read."),
    "hours": ("!hours <name>", "A player's hours in TF2 and how old their account is."),
    "cheaters": ("!cheaters", "Everyone flagged red in the lobby."),
    "roast": ("!roast <name>", "A roast built from that player's real match: their kills, deaths, nemesis, "
                               "class, hours and account age. !roast me roasts yourself."),
    "ip": ("!ip <name>", "A player's fake IPv4 (the same one for them all match)."),
    "help": ("!help", "The commands players can type."),
}
INFO_RE = re.compile(r"^\s*!(?P<command>" + "|".join(INFO_COMMANDS) + r")\b\s*(?P<rest>.*?)\s*$", re.I)
OTHER_TEAM = {"RED": "BLU", "BLU": "RED"}
SHORT_CLASS = {"Engineer": "Engi"}  # so a whole team fits in one message
ROAST_MEMORY = 6     # a player never gets one of their last 6 roasts again (while others fit)
MYSTATS_CACHE = 600   # seconds a player's Steam stats are kept (in memory only) before asking again


def short(name, size=20):
    return name if len(name) <= size else name[:size - 1] + "…"


def fit_list(prefix, items, sep=", ", empty=""):
    """prefix + as many items as fit in one chat message, then "+N more" for the rest."""
    if not items:
        return prefix + empty
    shown = []
    for n, item in enumerate(items):
        rest = len(items) - n - 1
        if not fits(prefix + sep.join(shown + [item]) + (f" +{rest} more" if rest else ""), CHAT_LIMIT):
            break
        shown.append(item)
    left = len(items) - len(shown)
    return prefix + sep.join(shown) + (f" +{left} more" if left else "")


def big(number):
    """182000 -> "182k", 4812 -> "4.8k", 1250000 -> "1.2M", 950 -> "950": short enough for chat."""
    number = int(number)
    if number >= 1_000_000:
        return f"{number / 1e6:.1f}".rstrip("0").rstrip(".") + "M"
    if number >= 10_000:
        return f"{number / 1000:.0f}k"
    if number >= 1000:
        return f"{number / 1000:.1f}".rstrip("0").rstrip(".") + "k"
    return str(number)


# Best-in-one-life records !mystats can show: (Steam's stat, what it's called, only for this class).
RECORDS = (("inumberofkills", "kills", None), ("idamagedealt", "dmg", None), ("ibackstabs", "stabs", "Spy"),
           ("iheadshots", "headshots", "Sniper"), ("ihealthpointshealed", "healed", "Medic"),
           ("isentrykills", "sentry kills", "Engineer"), ("ipointsscored", "points", None))


def join_fitting(prefix, items, sep):
    """prefix + as many items as fit in one chat message (the first ones matter most)."""
    shown = []
    for item in items:
        if fits(prefix + sep.join(shown + [item]), CHAT_LIMIT):
            shown.append(item)
    return prefix + sep.join(shown)


def mystats_lines(name, stats):
    """!mystats in two messages: lifetime totals and main class, then the best single-life records.
    stats as lookups.tf2_stats gives them."""
    n = short(name, 18)
    play = {c: stats.get((c, "accum", "iplaytime"), 0) for c in TF2_CLASSES}
    seconds = sum(play.values())
    life = [f"{round(seconds / 3600):,} h"] if seconds else []
    for stat, label in (("inumberofkills", "kills"), ("idominations", "dominations")):
        total = sum(stats.get((c, "accum", stat), 0) for c in TF2_CLASSES)
        if total:
            life.append(f"{big(total)} {label}")
    if seconds:
        main = max(play, key=play.get)
        life.append(f"mains {main} ({round(100 * play[main] / seconds)}%)")
    best = []
    for stat, label, only in RECORDS:
        value, cls = max((stats.get((c, "max", stat), 0), c) for c in ([only] if only else TF2_CLASSES))
        if value:
            best.append(f"{big(value)} {label}" + ("" if only else f" ({cls})"))
    lines = [join_fitting(f"{n} | ", life, ", ")] if life else []
    if best:
        lines.append(join_fitting(f"{n} | best life: ", best, ", "))
    return lines or [f"[MYSTATS] {n} | Steam has no TF2 stats for them"]


class InfoCommandsMixin:
    def info_command(self, name, msg, team):
        """Answers the info commands above, typed by anyone (you too), in the chat they were
        typed in. Part of a name works, like with !duel and !who."""
        m = INFO_RE.match(msg)
        if not m or self.rcon_state != "connected":
            return
        command = m["command"].lower()
        if not self.cfg["info_commands"].get(command, True):
            return
        say = "say_team" if team else "say"
        rest = m["rest"].strip("'\"@")
        if command == "roast":
            self.roast_command(name, rest, say)
        elif command == "mystats":
            self.mystats_command(name, rest, say)
        elif command in ("check", "hours", "ip"):  # about one player, or !check all
            if command == "check" and rest.lower() == "all":
                self.announce_chat(self.lineup_line(self.other_team_of(name)), say)
            elif not rest or rest.lower() == "all":
                more = ", or !check all" if command == "check" else ""
                self.announce_chat(f"[{command.upper()}] Type !{command} <name>{more}. Part of a name works", say)
            else:
                p, error = self.find_player(rest, command.upper())
                if command == "ip" and p and p.sid == self.me:
                    line = f"{p.name} | same WiFi as your mom"  # someone tried !ip on you
                else:
                    line = error or (self.ip_line(p) if command == "ip" else getattr(self, f"{command}_line")(p))
                self.announce_chat(line, say)
        elif command == "stats":
            self.announce_chat(self.stats_line(), say)
        elif command == "cheaters":
            self.announce_chat(self.cheaters_line(), say)
        elif command == "help":
            self.announce_chat(self.help_line(), say)

    def find_player(self, wanted, tag):
        """(player, None), or (None, the line that says why not): an exact name first, else
        the one name that has the text in it."""
        wanted = wanted.strip().lower()
        if not wanted:
            return None, f"[{tag}] Type a name after the command. Part of a name works"
        players = list(self.players.values())
        matches = [p for p in players if p.name.lower() == wanted] or [p for p in players if wanted in p.name.lower()]
        if not matches:
            return None, f"[{tag}] nobody here is called '{wanted}'"
        if len(matches) > 1:
            names = ", ".join(f"'{short(p.name)}'" for p in matches[:3])
            return None, f"[{tag}] '{wanted}' matches {names}. Type more of the name"
        return matches[0], None

    def other_team_of(self, name):
        """RED or BLU: the team the one who typed it plays against (from your view if not known)."""
        asker = self.players.get(self.sid_by_name(name))
        color = self.team_color(asker) if asker else ""
        if not color and (me := self.players.get(self.me)):
            color = self.team_color(me)
        return OTHER_TEAM.get(color, "")

    def tag(self, p):
        color = self.team_color(p)
        return f"{short(p.name)}{f' ({color})' if color else ''}"

    def health_words(self, p):
        """ "87/125 HP", "450/300 HP (overhealed)", "dead", or why it isn't known."""
        fields = self.board.get(p.sid)
        if not fields:
            return "HP not known (needs -g15)"
        if fields.get("m_bAlive") == "false":
            return "dead"
        hp = self.board_int(p.sid, "m_iHealth")
        if hp is None:
            return "HP not known yet"
        full = CLASS_MAX_HEALTH.get(self.player_class(p))
        if not full:
            return f"{hp} HP"
        return f"{hp}/{full} HP" + (" (overhealed)" if hp > full else "")

    def check_line(self, p):
        return f"[CHECK] {self.tag(p)} | {self.player_class(p) or 'class not known'} | {self.health_words(p)}"

    def team_players(self, color):
        return [p for p in self.players.values() if color and self.team_color(p) == color]

    def lineup_line(self, color):
        if not color:
            return "[CHECK] The teams aren't known yet"
        team = self.team_players(color)
        counts = Counter(self.player_class(p) for p in team if self.player_class(p)).most_common()
        items = [f"{count} {SHORT_CLASS.get(cls, cls)}" for cls, count in counts]
        unknown = sum(1 for p in team if not self.player_class(p))
        if unknown:
            items.append(f"{unknown} not known")
        return fit_list(f"[CHECK] {color}: ", items, empty="nobody")

    def top_line(self, unknown="[TOP] Scores not known yet (needs -g15)"):
        """Each team's total kills and its top fragger, from TF2's scoreboard: what the Players
        page's Kill race button posts. `unknown` when no score is known (the button passes None
        and says why in the toolbox instead)."""
        teams = {}  # RED/BLU -> (total kills, top player, their kills)
        for color in ("RED", "BLU"):
            scored = [(self.board_int(p.sid, "m_iScore"), p) for p in self.team_players(color)]
            scored = [(kills, p) for kills, p in scored if kills is not None]
            if scored:
                kills, p = max(scored, key=lambda item: item[0])
                teams[color] = (sum(k for k, _ in scored), p, kills)
        if not teams:
            return unknown
        red, blu = (teams.get(color, (0, None, 0))[0] for color in ("RED", "BLU"))
        parts = [f"[TOP] Kills: RED {red} - {blu} BLU"]
        parts += [f"{color}: {short(p.name, 18)} {kills}/{self.board_int(p.sid, 'm_iDeaths') or 0}"
                  for color, (_, p, kills) in teams.items()]
        while not fits(" | ".join(parts), CHAT_LIMIT) and len(parts) > 1:
            parts.pop()
        return " | ".join(parts)

    def hours_line(self, p):
        hours = ("not known yet" if p.hours == PENDING else "hours hidden" if p.hours is None
                 else f"{int(p.hours):,} hours in TF2")
        age = age_in_words(p.summary)
        return f"[HOURS] {self.tag(p)} | {hours}" + (f" | account {age} old" if age else "")

    def cheaters_line(self):
        found = []
        for p in self.players.values():
            red = sorted((s, t) for s, t in self.flags.get(p.sid, []) if s >= 3 and not t.startswith("marked by you"))
            if red or str(p.sid) in self.marks:
                why = re.sub(r" \([^()]*\)$", "", red[-1][1]) if red else "marked"
                found.append(f"{short(p.name, 16)} ({why})")
        return fit_list("[CHEATERS] ", found, empty="nobody flagged red in this lobby")

    def help_line(self):
        cfg = self.cfg
        items = [usage for command, (usage, _) in INFO_COMMANDS.items()
                 if command != "help" and cfg["info_commands"].get(command, True)]
        items = (["!who <name>"] if cfg["who_command"] else []) + items
        items += (["!duel <name>"] if self.ai_on else []) + (["!speak <language> <text>"] if cfg["translate_command"] else [])
        line = fit_list("[HELP] ", items, sep=" | ", empty="no commands are on")
        if line.endswith("more"):  # too many for one message: just the names, most take a name after them
            line = fit_list("[HELP] ", [item.split(" ")[0] for item in items], sep=" ") + " (most take a name)"
        return line

    # --- !stats: this match ------------------------------------------------------------------

    def stats_line(self):
        """This match in one line: the map and how long you've been on it, kills per team, the
        best player and the one dying most (TF2's scoreboard), then headshots, backstabs and crit
        kills (the kill feed). The least important parts go first when it doesn't fit."""
        head = "[STATS] " + (self.map_name or "this map")
        if self.match_joined_at:
            head += f", {int((time.time() - self.match_joined_at) // 60)} min"
        parts = [head]
        scored = [(self.board_int(p.sid, "m_iScore"), self.board_int(p.sid, "m_iDeaths"), p)
                  for p in self.players.values()]
        scored = [(k or 0, d or 0, p) for k, d, p in scored if k is not None or d is not None]
        if scored:
            team = {color: sum(k for k, _, p in scored if self.team_color(p) == color) for color in ("RED", "BLU")}
            parts.append(f"Kills RED {team['RED']} - {team['BLU']} BLU")
            k, d, best = max(scored, key=lambda s: (s[0], -s[1]))
            parts.append(f"MVP {short(best.name, 16)} {k}/{d}")
            k2, d2, worst = max(scored, key=lambda s: (s[1], -s[0]))
            if worst is not best and d2:
                parts.append(f"most deaths {short(worst.name, 16)} {d2}")
        heads = sum(v[1] for v in self.kills.values())
        stabs = sum(self.stab_kills.values())
        kills, crits = (sum(v[i] for v in self.all_crits.values()) for i in (0, 1))
        feed = [f"{heads} headshot{'s' * (heads != 1)}", f"{stabs} backstab{'s' * (stabs != 1)}"]
        if kills:
            feed.append(f"{round(100 * crits / kills)}% crit kills")
        parts.append(", ".join(feed))
        while not fits(" | ".join(parts), CHAT_LIMIT) and len(parts) > 1:
            parts.pop()
        return " | ".join(parts)

    # --- !mystats: lifetime stats from Steam -------------------------------------------------

    def mystats_command(self, name, rest, say):
        """!mystats: the lifetime TF2 stats of whoever typed it; !mystats <name>: that player's (part
        of a name works). Steam is asked on a background thread; the answer comes back as a
        "mystats" event (mystats_answered)."""
        if rest.lower() in ("", "me", "myself"):
            sid = self.sid_by_name(name)
            if not sid:
                self.announce_chat(f"[MYSTATS] Couldn't find {short(name)} on the scoreboard. "
                                   "Type !mystats <name>", say)
                return
        else:
            p, error = self.find_player(rest, "MYSTATS")
            if error:
                self.announce_chat(error, say)
                return
            sid = p.sid
        if not self.cfg["steam_api_key"]:
            self.announce_chat("[MYSTATS] Needs a Steam API key in the toolbox", say)
            return
        cached = self.__dict__.setdefault("mystats_cache", {}).get(sid)
        if cached and time.time() - cached[0] < MYSTATS_CACHE:
            self.mystats_answered(sid, say, cached[1])
            return
        threading.Thread(target=tf2_stats_lookup, args=(self.cfg["steam_api_key"], sid, say, self.events),
                         daemon=True).start()

    def mystats_answered(self, sid, say, result):
        """Steam's answer for !mystats: the stats (a dict), or why not ("private", "offline"...)."""
        p = self.players.get(sid)
        name = p.name if p else "?"
        if not isinstance(result, dict):
            why = ("TF2 stats are private (Steam profile: Game details)" if result == "private"
                   else f"Steam didn't answer ({result})")
            self.announce_chat(f"[MYSTATS] {short(name)} | {why}", say)
            return
        self.__dict__.setdefault("mystats_cache", {})[sid] = (time.time(), result)
        for line in mystats_lines(name, result):
            self.announce_chat(line, say)

    # --- !roast: a joke built from someone's real match ---------------------------------------

    def roast_command(self, name, rest, say):
        """!roast <name>, or !roast / !roast me for yourself."""
        asker = self.sid_by_name(name)
        if rest.lower() in ("", "me", "myself"):
            p = self.players.get(asker)
            if not p:
                self.announce_chat("[ROAST] Couldn't find you on the scoreboard. Type !roast <name>", say)
                return
        else:
            p, error = self.find_player(rest, "ROAST")
            if error:
                self.announce_chat(error, say)
                return
        self.announce_chat(self.roast_line(p), say)

    def roast_line(self, p):
        """One roast for p, picked at random from every line that fits their match, never one of
        the last ROAST_MEMORY said about them (unless nothing else fits)."""
        options = self.roasts(p)
        recent = self.__dict__.setdefault("roast_recent", {}).setdefault(p.sid, deque(maxlen=ROAST_MEMORY))
        fresh = [line for line in options if line not in recent] or [line for line in options if line != (recent or [None])[-1]] or options
        line = random.choice(fresh)
        recent.append(line)
        return f"[ROAST] {line}"

    def roasts(self, p):
        """Every roast that fits p's match: chat trash talk about their gameplay and Steam numbers
        only, nothing about who they are."""
        n = short(p.name, 18)
        k, d = self.board_int(p.sid, "m_iScore"), self.board_int(p.sid, "m_iDeaths")
        if k is None and d is None:  # no scoreboard (no -g15): the kill feed's count
            k = sum(self.weapons.get(p.sid, Counter()).values())
            d = sum(v for (_, victim), v in self.pair_kills.items() if victim == p.sid)
        k, d = k or 0, d or 0
        cls = self.player_class(p)
        died_to = self.death_kinds.get(p.sid, Counter())
        killers = Counter({killer: v for (killer, victim), v in self.pair_kills.items() if victim == p.sid and v > 0})
        hours = p.hours if isinstance(p.hours, (int, float)) and not isinstance(p.hours, bool) else None
        days = None
        if p.summary and p.summary.get("timecreated"):
            days = int((time.time() - p.summary["timecreated"]) // 86400)
        kd = f"{k}-{d}"
        losing = d >= 4 and k * 2 <= d
        out = []
        if k >= 10 and k >= 3 * max(d, 1):  # sweating
            out += [f"{n} {kd} in casual. bro tryharding like there's prize money",
                    f"{n} {kd}. relax bro it's casual, the medal is plastic",
                    f"{n} {kd} in casual. bro thinks this is comp, nobody's watching"]
        if d >= 6 and k * 3 <= d:  # a bad match
            out += [f"{n} is {kd}. dogwater. absolute dogwater. uninstall.",
                    f"{n} {kd}. skill issue so big it has its own hitbox",
                    f"{n} {kd}. spends more time in spawn than the cart",
                    f"{n} {kd}. getting dunked on by f2ps with stock weapons",
                    f"{n} {kd}. enemy team should be paying you a salary",
                    f"{n} {kd}. free to play and still a waste of money",
                    f"{n} {kd}. bro is playing with the monitor off"]
        if k == 0 and d >= 3:
            out += [f"{n} 0 kills. playing on peaceful mode",
                    f"{n} 0 kills. a spectator with extra steps",
                    f"{n} 0-{d}. not a player, a respawn timer"]
        if killers:
            top, count = killers.most_common(1)[0]
            if count >= 4 and top in self.players:
                kn = short(self.players[top].name, 16)
                back = max(self.pair_kills.get((p.sid, top), 0), 0)
                out += [f"{kn} {count} {n} {back}. {n} respawning just to say hi",
                        f"{n} died to {kn} {count} times. {kn} has you on a subscription plan",
                        f"{kn} {count} {n} {back}. {n} is a free daily for {kn}"]
        if died_to["backstab"] >= 3:
            c = died_to["backstab"]
            out += [f"{n} backstabbed {c} times. your back's seen more knives than a kitchen",
                    f"{n} got backstabbed {c} times. spy's farming you like a contract"]
        if died_to["headshot"] >= 3:
            c = died_to["headshot"]
            out += [f"{n} ate {c} headshots. stop peeking the sniper, it's not a love story",
                    f"{n} took {c} headshots. sniper's got your head on speed dial"]
        if hours and hours >= 1000 and d > k:
            out.append(f"{n} {int(hours):,} hours and still {kd}. {int(hours):,} hours of tutorial mode")
        if days is not None and days < 60 and d > k:
            out.append(f"{n} {days} day old account and {kd}. smurfing and still getting clapped")
        class_lines = {
            "Sniper": (k <= 2 and d >= 4, f"{n}, sniper with {k} kill{'s' * (k != 1)}. scoped in, zoned out"),
            "Spy": (not self.stab_kills.get(p.sid) and d >= 3, f"{n}, spy with 0 stabs. bro's a 125hp tourist"),
            "Pyro": (k <= 3 and d >= 4, f"{n}, pyro with {k} kill{'s' * (k != 1)}. W+M1 and still lost the 1v1"),
            "Demoman": (k <= 3 and d >= 4, f"{n}, demo with {k} kill{'s' * (k != 1)}. sticky spam, zero damage, max embarrassment"),
            "Heavy": (k <= 3 and d >= 4, f"{n}, heavy with {k} kill{'s' * (k != 1)}. biggest hitbox in the game, smallest impact"),
            "Soldier": (k <= 3 and d >= 4, f"{n}, soldier with {k} kill{'s' * (k != 1)}. rocket jumped straight into the killfeed"),
            "Scout": (d >= 8 and k < d, f"{n}, scout with {d} deaths. fastest class, slowest brain"),
            "Engineer": (k <= 3 and d >= 4, f"{n}, engi with {k} kill{'s' * (k != 1)}. sentry's hard carrying, you're just its wrench"),
            "Medic": (losing, f"{n} playing medic and the whole team is dead. uber your brain"),
        }
        if cls in class_lines and class_lines[cls][0]:
            out.append(class_lines[cls][1])
        if not out:
            if not k and not d:
                out.append(f"{n} just got here. no stats yet, the vibes are already bad")
            else:
                out += [f"{n} {kd}. aggressively mid", f"{n} {kd}. background npc, no dialogue"]
        return [line if fits(f"[ROAST] {line}", CHAT_LIMIT) else line[:CHAT_LIMIT - 12] + "..." for line in out]

    def toggle_info_command(self, command):
        """A pill on the Chat page's Chat commands card."""
        on = dict(self.cfg["info_commands"])
        on[command] = not on.get(command, True)
        self.cfg["info_commands"] = on
        save_config(self.cfg)
