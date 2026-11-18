"""Chat commands anyone can type for information about the lobby, answered by the scanner:
!check <name> (class and health), !check all (the other team's classes), !medic, !top,
!kd <name>, !hours <name>, !cheaters and !help. Each can be switched off on the Chat page."""

import re
from collections import Counter

from chat import fits, CHAT_LIMIT
from game_log import CLASS_MAX_HEALTH, PENDING
from player_flags import age_in_words
from settings import save_config

# command -> (what !help and the Chat page call it, what it does)
INFO_COMMANDS = {
    "check": ("!check <name>", "A player's class and health. !check all: the other team's classes."),
    "medic": ("!medic", "The other team's Medics and their health."),
    "top": ("!top", "The most kills on each team."),
    "kd": ("!kd <name>", "A player's kills, deaths and killstreak."),
    "hours": ("!hours <name>", "A player's hours in TF2 and how old their account is."),
    "cheaters": ("!cheaters", "Everyone flagged red in the lobby."),
    "ip": ("!ip <name>", "A player's fake IPv4 (the same one for them all match)."),
    "help": ("!help", "The commands players can type."),
}
INFO_RE = re.compile(r"^\s*!(?P<command>" + "|".join(INFO_COMMANDS) + r")\b\s*(?P<rest>.*?)\s*$", re.I)
OTHER_TEAM = {"RED": "BLU", "BLU": "RED"}
SHORT_CLASS = {"Engineer": "Engi"}  # so a whole team fits in one message


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
        if command in ("check", "kd", "hours", "ip"):  # about one player, or !check all
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
        elif command == "medic":
            self.announce_chat(self.medic_line(self.other_team_of(name)), say)
        elif command == "top":
            self.announce_chat(self.top_line(), say)
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

    def medic_line(self, color):
        if not color:
            return "[MEDIC] The teams aren't known yet"
        medics = [p for p in self.team_players(color) if self.player_class(p) == "Medic"]
        items = [f"{short(p.name, 16)} {self.health_words(p)}" for p in medics]
        return fit_list(f"[MEDIC] {color}: ", items, empty="no Medic")

    def top_line(self):
        parts = []
        for color in ("RED", "BLU"):
            scored = [(self.board_int(p.sid, "m_iScore"), p) for p in self.team_players(color)]
            scored = [(kills, p) for kills, p in scored if kills is not None]
            if scored:
                kills, p = max(scored, key=lambda item: item[0])
                parts.append(f"{color}: {short(p.name, 18)} {kills}/{self.board_int(p.sid, 'm_iDeaths') or 0}")
        return "[TOP] " + " | ".join(parts) if parts else "[TOP] Scores not known yet (needs -g15)"

    def kd_line(self, p):
        kills, deaths = self.board_int(p.sid, "m_iScore"), self.board_int(p.sid, "m_iDeaths")
        if kills is None and deaths is None:
            return f"[KD] {self.tag(p)} | not known yet"
        current, best = self.player_streak(p)
        streak = f" | streak {current}" + (f" (best {best})" if best > current else "") if best else ""
        return f"[KD] {self.tag(p)} | {kills or 0} kills, {deaths or 0} deaths{streak}"

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
        return fit_list("[HELP] ", items, sep=" | ", empty="no commands are on")

    def toggle_info_command(self, command):
        """A pill on the Chat page's Chat commands card."""
        on = dict(self.cfg["info_commands"])
        on[command] = not on.get(command, True)
        self.cfg["info_commands"] = on
        save_config(self.cfg)
        self.update_info_buttons()
