"""Chat duels: anyone types "!duel <name>" and every kill between the two is announced with the score.
DuelsMixin is the part of the App that keeps the scores and answers the commands."""

import re
import secrets
import time
from collections import Counter, deque

from game_log import G15_TEAMS
from chat import CHAT_LIMIT, duel_name, fits, quoted

# --- players and flags ----------------------------------------------------------

def duel_pair(target):
    """The two players in '!duel "Hans", "Jan"', "!duel hans, jan" or "!duel hans vs jan",
    else None (a "!duel" with one name)."""
    quoted_names = re.findall(r'"([^"]+)"', target)
    if len(quoted_names) == 2:
        return quoted_names
    parts = re.split(r"\s*,\s*|\s+vs\.?\s+", target, maxsplit=1, flags=re.I)
    return parts if len(parts) == 2 and all(p.strip() for p in parts) else None

# Chat duels: anyone types "!duel <part of a name>" and every kill between the
# two is announced with the score until the map ends or one of them leaves.
# Said after a 1v1 duel's score: {killer}/{victim} (or {winner}/{loser}) are short names.
DUEL_LINES = {
    "first": ("{victim} has entered the find-out phase", "{victim}'s respawn timer is now their favorite map",
              "first blood. {victim} forgot this was a duel", "{killer} opens the account, {victim} opens the respawn menu",
              "{victim} is already googling how to aim", "{killer} strikes first, {victim} strikes out",
              "{victim} warmed up by dying. bold strategy", "{victim} came to duel, left to respawn",
              "Mann Co. would like to remind {victim} this counts", "{victim} is off to a flying start. into the ground"),
    "tied": ("all square. both equally mid", "tied. Mann Co. is now taking bets", "the tension is unbearable (it isn't)",
             "dead even. emphasis on dead", "tied. the most balanced thing in TF2", "{killer} evens it up, somebody get popcorn",
             "perfectly balanced, as all things should be", "tied again. Valve couldn't balance this better",
             "neck and neck. mostly neck", "back to square one. {victim} is sweating"),
    "lead": ("the tables have turned and {victim} is under them", "{killer} takes the lead, {victim} takes the respawn room",
             "plot twist. {victim} did not see that coming", "{killer} is in front now, {victim} is in denial",
             "lead change. {victim} got too comfortable", "{killer} remembered how to play",
             "{killer} pulls ahead, {victim} pulls a face", "momentum shift. {victim} can feel it",
             "{victim}'s lead has left the server", "{killer} goes ahead. Saxton Hale approves"),
    "ahead": ("{victim} should try another class. or game", "{killer} is cooking and {victim} is the ingredient",
              "{victim} keeps walking into it like it's a dispenser", "just another day at the office for {killer}",
              "{victim} needs a medic. and a therapist", "{killer} is playing with their food",
              "{victim} is donating kills. very generous", "is {victim} even trying or is this a bit",
              "{victim} should check if their monitor is on", "{killer} makes it look easy because it is"),
    "blowout": ("{victim} is speedrunning the respawn timer", "{victim}'s K/D just filed a missing persons report",
                "this isn't a duel anymore, it's a tutorial", "{victim} should start paying rent in that spawn room",
                "{victim} is now a dispenser for {killer}'s killstreak", "somebody call a ref, this is a crime scene",
                "{victim} might want to uninstall. respectfully", "{killer} is in another league, {victim} is in another tab",
                "mercy rule please. {victim} has a family", "{victim} has been reported to Mann Co. as defective"),
    "behind": ("{killer} remembered they have a mouse", "comeback arc loading... 12%", "not over yet, {killer} still has a pulse",
               "{killer} is clawing back. {victim} is sweating", "the gap is closing. {victim} felt that one",
               "{killer} won't go quietly", "{victim} can feel it slipping", "one step closer. {killer} smells blood",
               "don't count {killer} out yet", "{killer} found the aim button"),
    "streak": ("{killer} has {victim} on a monthly subscription", "{victim}'s spawn door has their name on it now",
               "{victim} keeps coming back for more. respect", "{killer} owns {victim} now, the paperwork is done",
               "someone stop {killer}. anyone. please", "{victim} is stuck in a loop. a dying loop",
               "{killer} is farming {victim} like it's Mann vs Machine", "{victim} should take a break. a long one",
               "again. and again. and again", "{victim} is a respawn room regular now"),
    "crit": ("crit. Valve's RNG picked a side", "random crit. skill is a social construct", "crit. totally earned, definitely skill",
             "{killer} rolled the dice, {victim} rolled over", "RNG has chosen {killer}", "crits: the great equalizer",
             "{victim} is filing a complaint about crits", "that crit was pure skill, obviously", "Valve says that's balanced",
             "crit. {victim} never stood a chance (literally)"),
    "won": ("GG {loser}. Mann Co. offers no refunds", "{loser} has been recalled by Mann Co. for defects",
            "{winner} reigns supreme, {loser} reigns in spawn", "{loser} will want a rematch. and lose that too",
            "{loser} has been sent to the shadow realm", "bow down to {winner}", "{loser} should practice more. on bots",
            "{winner} is the champion, {loser} is a participant", "GG. the respawn room misses {loser} already",
            "flawless. mostly"),
    "draw": ("a draw. nobody wins, everybody's mid", "perfectly balanced. perfectly boring", "a draw. rematch next map?",
             "both equally bad. impressive", "nobody learned anything"),
}
DUEL_BACKLOG = 4      # kill lines are skipped (still counted) while this many messages wait to be said
EVERYONE = "everyone"  # the "group" of the duels "!duel all, all" makes
DUEL_RE = re.compile(r"^\s*!duel\b\s*(?P<target>.*?)\s*$", re.I)


class DuelsMixin:
    def count_duel(self, killer, victim, sign=1):
        """Counts a kill between you and someone for the Duel column; sign=-1 takes one back."""
        me = self.players.get(self.me)
        if not me or killer == victim:
            return
        if killer == me.name and (other := self.sid_by_name(victim)):
            self.duels.setdefault(other, [0, 0])[0] += sign
            self.dirty = True
        elif victim == me.name and (other := self.sid_by_name(killer)):
            self.duels.setdefault(other, [0, 0])[1] += sign
            self.dirty = True

    # --- Chat duels: "!duel <name>" from anyone, kills between the two announced. On ----
    # --- while HoovyGPT is (one button since 2026-10-31) ----------------------------------

    def duel_between(self, a, b):
        return next((d for d in self.chat_duels if set(d["sids"]) == {a, b}), None)

    def duel_target(self, text, challenger):
        """The player a "!duel" names: an exact name first, else the one name that
        contains the text. Returns (sid, None) or (None, why not)."""
        text = text.strip().strip("'\"@").lower()
        here = [p for sid, p in self.players.items() if sid != challenger and (sid in self.board or not self.board)]
        exact = [p for p in here if p.name.lower() == text]
        matches = exact or [p for p in here if text in p.name.lower()]
        if len(matches) == 1:
            return matches[0].sid, None
        if not matches:
            return None, f"nobody here is called '{text}'"
        return None, f"'{text}' matches {', '.join(quoted(p.name) for p in matches[:3])}. Type more of the name"

    def duel_command(self, name, msg, team):
        """Answers every "!duel ..." command typed in chat, by anyone."""
        if not (m := DUEL_RE.match(msg)):
            return
        if not self.ai_on:
            if (me := self.players.get(self.me)) and name == me.name:
                self.notify("Duels are off: switch them on on the Duels page, then type !duel again")
            return
        challenger = self.sid_by_name(name)
        if not challenger:
            return
        if m["target"].lower() == "reset":
            self.reset_duels(None, None, challenger)
            return
        if m["target"].lower().endswith(" reset") and (pair := duel_pair(m["target"][:-6])):
            # "!duel hans, jan reset": that pair's score back to 0-0
            first, error = self.duel_player_by_name(pair[0])
            second, error2 = self.duel_player_by_name(pair[1]) if first else (None, None)
            if error or error2:
                self.announce_chat(f"[DUEL] {error or error2}")
            else:
                self.reset_duels(first, second, challenger)
            return
        if m["target"].lower() in ("stopall", "stop all"):
            self.stop_all_duels(challenger)
            return
        if m["target"].lower().split(" ")[0] == "stop":
            # "!duel stop" ends all your duels, "!duel stop jag" only the one with Noodle.
            rest = m["target"][4:].strip()
            other, error = self.duel_target(rest, challenger) if rest else (None, None)
            if error:
                self.announce_chat(f"[DUEL] {error}")
            self.end_duels([d for d in self.chat_duels if challenger in d["sids"] and (not other or other in d["sids"])],
                           "stopped", challenger)
            return
        if not m["target"]:
            self.announce_chat("[DUEL] Type !duel <name> to challenge someone on the enemy team. Part of a name works")
            return
        if m["target"].lower() == "all":
            self.duel_all(challenger)
            return
        if m["target"].lower() in ("scores", "score"):
            self.duel_scores()
            return
        if pair := duel_pair(m["target"]):
            # '!duel "Hans", "Jan"' or "!duel hans vs jan": two other players, made to duel.
            # "!duel sayko, all": sayko against the whole other team.
            part = [x.strip().strip("'\"").lower() for x in pair]
            if part == ["all", "all"]:
                self.duel_everyone(challenger)
                return
            if "all" in part:
                other = pair[part.index("all") - 1]  # the part that isn't "all"
                player, error = self.duel_target(other, None)
                if error:
                    self.announce_chat(f"[DUEL] {error}")
                else:
                    self.duel_all(player, challenger)
                return
            first, error = self.duel_target(pair[0], None)
            second, error2 = self.duel_target(pair[1], first) if first else (None, None)
            if error or error2:
                self.announce_chat(f"[DUEL] {error or error2}")
                return
            self.start_duel(first, second, challenger)
            return
        target, error = self.duel_target(m["target"], challenger)
        if error:
            self.announce_chat(f"[DUEL] {error}")
            return
        self.start_duel(challenger, target)

    def start_duel(self, first, second, starter=None):
        """A duel between two players; starter is whoever made two others duel."""
        a, b = self.players[first], self.players[second]
        teams = self.board_int(first, "m_iTeam"), self.board_int(second, "m_iTeam")
        if None not in teams and teams[0] == teams[1]:
            self.announce_chat(f"[DUEL] {duel_name(a.name)} and {duel_name(b.name)} are on the same team")
            return
        if duel := self.duel_between(first, second):
            self.announce_chat(f"[DUEL] {duel_name(a.name)} and {duel_name(b.name)} are already dueling "
                            f"{duel['score'][first]}-{duel['score'][second]}")
            return
        self.chat_duels.append({"sids": (first, second), "score": {first: 0, second: 0}})
        by = "" if starter in (None, first, second) else f" (by {duel_name(self.players[starter].name)})"
        self.announce_chat(f">>> [DUEL] {duel_name(a.name)} vs {duel_name(b.name)} <<<{by}")

    def duel_all(self, challenger, starter=None):
        """"!duel all": a duel with everyone on
        the other team, announced in one line instead of one per player.
        starter: whoever typed "!duel sayko, all" to send someone else at them."""
        p = self.players.get(challenger)
        team = self.board_int(challenger, "m_iTeam")
        if not p or team not in G15_TEAMS:
            self.announce_chat("[DUEL] Can't tell the teams yet. Try again in a few seconds")
            return
        enemies = [sid for sid in self.board if self.board_int(sid, "m_iTeam") in G15_TEAMS
                   and self.board_int(sid, "m_iTeam") != team and sid in self.players]
        new = [sid for sid in enemies if not self.duel_between(challenger, sid)]
        if not new:
            self.announce_chat(f"[DUEL] {duel_name(p.name)} is already dueling all of {G15_TEAMS[5 - team]}"
                            if enemies else "[DUEL] Nobody on the other team to duel")
            return
        for sid in new:
            self.chat_duels.append({"sids": (challenger, sid), "score": {challenger: 0, sid: 0},
                                    "group": challenger, "group_team": G15_TEAMS[5 - team]})
        by = "" if starter in (None, challenger) else f" (by {duel_name(self.players[starter].name)})"
        self.announce_chat(f">>> [DUEL] {duel_name(p.name)} vs ALL OF {G15_TEAMS[5 - team]} ({len(enemies)}) <<<{by}")

    def duel_everyone(self, starter):
        """"!duel all, all": every player on RED duels every player on BLU."""
        teams = {sid: self.board_int(sid, "m_iTeam") for sid in self.board if sid in self.players}
        red = [sid for sid, t in teams.items() if t == 2]
        blu = [sid for sid, t in teams.items() if t == 3]
        if not red or not blu:
            self.announce_chat("[DUEL] Can't tell the teams yet. Try again in a few seconds")
            return
        new = [(r, b) for r in red for b in blu if not self.duel_between(r, b)]
        if not new:
            self.announce_chat("[DUEL] ALL vs ALL is already on")
            return
        for r, b in new:
            self.chat_duels.append({"sids": (r, b), "score": {r: 0, b: 0},
                                    "group": EVERYONE, "teams": {r: "RED", b: "BLU"}})
        self.announce_chat(f">>> [DUEL] ALL RED vs ALL BLU ({len(red)} vs {len(blu)}) <<< "
                        f"(by {duel_name(self.players[starter].name)})")

    def duel_name_of(self, sid):
        """A duelist's name, also once they've left the server."""
        if sid in self.players:
            self.duel_names[sid] = self.players[sid].name
        return self.duel_names.get(sid, "?")

    def duel_player_by_name(self, text):
        """Like duel_target, but among everyone in a running duel, here or not."""
        text = text.strip().strip("'\"@").lower()
        sids = {sid for d in self.chat_duels for sid in d["sids"]}
        named = {sid: self.duel_name_of(sid) for sid in sids}
        matches = [sid for sid, n in named.items() if n.lower() == text] or \
                  [sid for sid, n in named.items() if text in n.lower()]
        if len(matches) == 1:
            return matches[0], None
        if not matches:
            return None, f"nobody called '{text}' is in a duel"
        return None, f"'{text}' matches {', '.join(quoted(named[sid]) for sid in matches[:3])}. Type more of the name"

    def reset_duels(self, first, second, starter):
        """"!duel reset" puts every duel back to 0-0, "!duel hans, jan reset" one of them.
        The duels go on; "!duel stop" is what ends them."""
        duels = [d for d in self.chat_duels if first is None or set(d["sids"]) == {first, second}]
        if not duels:
            self.announce_chat("[DUEL] No duels running" if first is None else
                            f"[DUEL] {duel_name(self.duel_name_of(first))} and "
                            f"{duel_name(self.duel_name_of(second))} aren't dueling")
            return
        for duel in duels:
            duel["score"] = dict.fromkeys(duel["score"], 0)
            duel.pop("streak", None)
        by = duel_name(self.duel_name_of(starter))
        if first is None:
            self.announce_chat(f">>> [DUEL] all {len(duels)} duel score{'s' * (len(duels) != 1)} reset <<< (by {by})")
        else:
            self.announce_chat(f">>> [DUEL] {duel_name(self.duel_name_of(first))} 0-0 "
                            f"{duel_name(self.duel_name_of(second))} <<< score reset (by {by})")

    def stop_all_duels(self, starter):
        """"!duel stopall": ends every duel at once (ALL vs ALL included) in two
        lines at most, not one per duel."""
        if not self.chat_duels:
            self.announce_chat("[DUEL] No duels running")
            return
        everyone = [d for d in self.chat_duels if d.get("group") == EVERYONE]
        count = len(self.chat_duels)
        self.chat_duels = []
        if everyone:
            self.everyone_summary(everyone)
        self.announce_chat(f">>> [DUEL OVER] All {count} duel{'s' * (count != 1)} stopped <<< "
                        f"(by {duel_name(self.players[starter].name)})")

    def duel_kill(self, m, killer, victim):
        """A confirmed kill: announced when the two are dueling each other."""
        duel = self.duel_between(killer, victim) if killer and victim and killer != victim else None
        if not duel:
            return
        score = duel["score"]
        before = score[killer] - score[victim]
        score[killer] += 1
        streak = duel.setdefault("streak", [None, 0])
        streak[:] = [killer, streak[1] + 1] if streak[0] == killer else [killer, 1]
        group = duel.get("group")
        if group and len(self.announce_queue) >= DUEL_BACKLOG:
            return  # ALL vs ALL kills come faster than chat can say them: counted, not said
        k, v = self.duel_name_of(killer), self.duel_name_of(victim)
        lead = score[killer] - score[victim]
        category = ("first" if sum(score.values()) == 1 else "crit" if m["crit"] else "tied" if lead == 0 else
                    "lead" if before <= 0 < lead else "behind" if lead < 0 else "blowout" if lead >= 5 else
                    "streak" if streak[1] >= 3 else "ahead")
        self.announce_chat(self.duel_message(f">>> [DUEL] {{killer}} {score[killer]}-{score[victim]} {{victim}} <<< ",
                                          category, killer=k, victim=v))

    def duel_message(self, start, category, **names):
        """start + a DUEL_LINES line not used lately, as one chat message: lines that don't fit are
        skipped, and names are cut shorter (16, then 10 characters) before giving up
        on the line."""
        recent = self.duel_recent.setdefault(category, deque(maxlen=4))
        lines = [l for l in DUEL_LINES[category] if l not in recent]
        secrets.SystemRandom().shuffle(lines)
        for cut in (16, 10):
            short = {key: name if len(name) <= cut else name[:cut - 1].rstrip() + ".." for key, name in names.items()}
            for line in lines:
                text = (start + line).format(**short)
                if fits(text, CHAT_LIMIT):
                    recent.append(line)
                    return text
        return start.format(**short).rstrip()

    def end_duels(self, duels, why, sid=None):
        """Ends duels, each with its own line, except a "!duel all": that gets one
        summary line, and one of its opponents leaving doesn't end theirs (their
        score stays in the summary, and it carries on if they come back)."""
        groups, everyone = {}, []
        for duel in duels:
            owner = duel.get("group")
            if owner == EVERYONE:
                if why == "stopped":
                    self.chat_duels.remove(duel)
                    if not everyone:
                        self.announce_chat(f"[DUEL] {duel_name(self.players[sid].name)} dropped out of ALL vs ALL")
                    everyone.append(duel)
                elif why == "map ended":
                    everyone.append(duel)
                continue  # a player leaving keeps their score for the summary
            if owner is None or (why == "stopped" and sid != owner):
                self.end_duel(duel, why, sid)
            elif why == "left" and sid != owner:
                continue
            else:
                groups.setdefault(owner, []).append(duel)
        for owner, group in groups.items():
            for duel in group:
                self.chat_duels.remove(duel)
            reason ="" if why == "map ended" else f" ({'left' if why == 'left' else 'gave up'})"
            self.announce_chat(f">>> [DUEL OVER] {self.group_record(owner, group)} <<<{reason}")
        if why == "map ended" and everyone:
            for duel in everyone:
                self.chat_duels.remove(duel)
            self.everyone_summary(everyone)

    def group_record(self, owner, group):
        """"tomato vs ALL OF BLU: won 3, lost 1, tied 8" for one "!duel all"."""
        won = lost = 0
        for duel in group:
            other = next(s for s in duel["sids"] if s != owner)
            won += duel["score"][owner] > duel["score"][other]
            lost += duel["score"][owner] < duel["score"][other]
        name = self.duel_name_of(owner)
        return (f"{duel_name(name)} vs ALL OF {group[0]['group_team']}: "
                f"won {won}, lost {lost}, tied {len(group) - won - lost}")

    @staticmethod
    def everyone_record(duels):
        """Team kills, and duels won and lost per player, in ALL vs ALL."""
        team_kills, won, lost = Counter(), Counter(), Counter()
        for duel in duels:
            a, b = duel["sids"]
            for me, other in ((a, b), (b, a)):
                team_kills[duel["teams"][me]] += duel["score"][me]
                won[me] += duel["score"][me] > duel["score"][other]
                lost[me] += duel["score"][me] < duel["score"][other]
        return team_kills, won, lost

    def duel_entries(self):
        """Every running duel as one short text ("dan 7-4 Hank"), the one with the most kills
        first; ALL vs ALL and "!duel all" as one entry each. For "!duel scores" and the Duels page."""
        singles, groups, everyone = [], {}, []
        for duel in self.chat_duels:
            group = duel.get("group")
            (everyone if group == EVERYONE else groups.setdefault(group, []) if group else singles).append(duel)
        entries = []
        if everyone:
            team_kills = self.everyone_record(everyone)[0]
            entries.append(f"ALL vs ALL: RED {team_kills['RED']}-{team_kills['BLU']} BLU")
        entries += [self.group_record(owner, group) for owner, group in groups.items()]
        name = lambda sid: duel_name(self.duel_name_of(sid))
        for duel in sorted(singles, key=lambda d: -sum(d["score"].values())):
            a, b = sorted(duel["sids"], key=lambda sid: -duel["score"][sid])  # the leader first
            entries.append(f"{name(a)} {duel['score'][a]}-{duel['score'][b]} {name(b)}")
        return entries

    def duel_scores(self):
        """"!duel scores": every running duel in up to 3 messages."""
        entries = self.duel_entries()
        prefix = "[DUEL SCORES] "
        if not entries:
            self.announce_chat(prefix + "No duels running. Start one: !duel <name>")
            return
        messages = []
        while entries and len(messages) < 3:
            text = prefix + entries.pop(0)
            while entries and fits(f"{text} | {entries[0]} | +99 more", CHAT_LIMIT):
                text += " | " + entries.pop(0)
            messages.append(text)
        if entries:
            messages[-1] += f" | +{len(entries)} more"
        for text in messages:
            self.announce_chat(text)

    def everyone_summary(self, duels):
        """One line for all of ALL vs ALL: team kills and the player who won the most duels."""
        team_kills, won, _ = self.everyone_record(duels)
        name = lambda sid: duel_name(self.duel_name_of(sid))
        text = f">>> [DUEL OVER] RED {team_kills['RED']}-{team_kills['BLU']} BLU <<<"
        if won and (best := max(won, key=lambda sid: won[sid])) and won[best]:
            text += f" MVP {name(best)}"
        self.announce_chat(text)

    def end_duel(self, duel, why, sid=None):
        """Map end, someone left (sid) or typed "!duel stop" (sid): says who won."""
        self.chat_duels.remove(duel)
        a, b = duel["sids"]
        score = duel["score"]
        names = {s: self.duel_name_of(s) for s in (a, b)}
        if why == "map ended":
            if score[a] == score[b]:
                text = self.duel_message(f">>> [DUEL OVER] {{winner}} {score[a]}-{score[b]} {{loser}} <<< ", "draw",
                                         winner=names[a], loser=names[b])
            else:
                winner, loser = (a, b) if score[a] > score[b] else (b, a)
                text = self.duel_message(f">>> [DUEL OVER] {{winner}} beats {{loser}} {score[winner]}-{score[loser]} <<< ",
                                         "won", winner=names[winner], loser=names[loser])
        else:
            winner = b if sid == a else a
            # the score can favor the one who quit, so no "beats" here
            text = (f">>> [DUEL OVER] {duel_name(names[winner])} {score[winner]}-{score[sid]} {duel_name(names[sid])} <<< "
                    f"({duel_name(names[sid])} {'left' if why == 'left' else 'gave up'}, {duel_name(names[winner])} wins)")
        self.announce_chat(text)

    def forget_duels_after_tf2_closed(self):
        """Duels last as long as TF2 runs: once it's been gone a minute, they're over.
        Until then, every duelist's name is noted while they're here, for after they leave."""
        if self.rcon_lost_at and time.time() - self.rcon_lost_at > 60 and self.chat_duels:
            self.chat_duels, self.duel_names = [], {}
        for duel in self.chat_duels:
            for sid in duel["sids"]:
                if sid in self.players:
                    self.duel_names[sid] = self.players[sid].name
