"""TF2 Toolbox (this file kept its old name, tf2_lobby_scanner.py).

Asks TF2 for the player list every few seconds over RCON (the same way TF2 Bot
Detector does) and checks every player against Steam (account age, TF2 hours,
VAC/game bans), steamhistory.net (community server bans), community cheater
lists and your own marks. Flagged players pop up as an alert at the top of the
screen. Profile comments and bios are searched for words like "cheater".

It also starts the chat translator overlay (tf2_translator.py), so one window
runs both.

Press F9 (anywhere, even in game) to show/hide the player list:
  drag the header   move it (position is saved when you hide it)
  click a player    votekick, copy/say their scan results in chat, mark as
                    cheater, copy SteamID, open profile

Needs these TF2 launch options (the script prints them with your password):
  -condebug -conclearlog -g15 -usercon +ip 0.0.0.0 +rcon_password <pw> +hostport 27069 +net_start
"""

import json
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
import webbrowser
from collections import Counter, deque
import tf2_translator
from tf2_translator import claim_instance, hotkey_listener, key_to_vk, parse_chat, single_instance, start_translator, tail

import settings
from settings import (BG, BORDER, HERE, FAKE_IPS_PATH, MARKS_PATH, SECRETS_PATH, SEEN_PATH, launch_options, load_config, load_secrets,
    load_json, save_config, save_json, FONT_LABEL, FONT_UI, FONT_UI_BOLD, HP_FG, MUTED, TEXT2, mono_family)
from game_log import (G15_DONE, G15_RE, G15_TEAMS, GC_TEAM_COLOR, HOSTNAME_RE, IDLE_KICK, KILL_RE, LOBBY_HEADER_RE,
    PLAYERS_RE,
    LOBBY_MEMBER_RE, MAP_RE, NOT_A_WEAPON, NO_LOBBY_RE, PENDING, STATUS_HEADER_RE, STATUS_RE,
    STEAM64_BASE, WEAPON_CLASS, CLASS_MAX_HEALTH, connected_seconds, current_match_lines, is_sniper_weapon, my_steamid,
    server_label, to_steam64)
from player_flags import (Player, RANDOM_CRIT_WEAPONS, crit_flag, evaluate, friend_flags, headshot_flag,
    name_thieves)
from lookups import (class_icons_worker, download_avatar, download_flag, lists_worker, lookup_worker, profile_worker,
    rcon_worker)
from chat import CHAT_LIMIT, ChatLimit, ChatMixin, console_safe, split_chat
from duels import DuelsMixin
from info_commands import InfoCommandsMixin
from hud import HudMixin
from ai import AIMixin, AI_CHAT_LOG
from screens import ScreensMixin, Toast, TokenPanel, on_a_screen
from ui_shapes import round_window_corners
from demo_check import (CHECK_NOW, DEMO_TOOL, STRONG_CHECKS, copy_lines, export_evidence, meaning_text, save_cheater_ticks, count_checks, demo_flags, demo_worker, demos_dir,
                        detections_path, save_detections, summary_text)

# One match's chat lines and kill times kept for the live cheater clues: plenty for a match, and a
# bound so a spam bot can't grow them without end.
MATCH_CHAT_MAX = 3000
MATCH_KILLS_MAX = 5000

class App(ChatMixin, DuelsMixin, InfoCommandsMixin, HudMixin, AIMixin, ScreensMixin):
    """The scanner itself: it reads TF2's output in handle_line, takes results from the background
    threads in handle_event, and keeps the list of players. Chat, duels, the AI and the screen
    are in the other files, as mixins: parts of this class that live elsewhere."""

    def __init__(self, cfg, lines, events, toggles, commands, lookups, profile_lookups=None,
                 history=None):
        """Sets up all state and builds the window. The queues connect it to the background threads:
        lines = TF2's output, events = lookup results, toggles = F9 presses, commands = console
        commands for TF2, lookups and profile_lookups = players still to look up."""
        self.profile_lookups = profile_lookups or queue.Queue()
        self.cfg = cfg
        self.lines, self.events, self.toggles = lines, events, toggles
        self.commands, self.lookups = commands, lookups
        self.players = {}         # sid -> Player
        self.flags = {}           # sid -> [(severity, text)]
        self.lobby_team = {}      # sid -> TF_GC_TEAM_*
        self.kills = {}           # sid -> [sniper kills, headshots] from the kill feed
        self.duels = {}           # sid -> [your kills on them, their kills on you]
        self.crits = {}           # sid -> [random-crit weapon kills, of which crits]
        self.gardens = {}         # sid -> Market Gardener crit kills (only crits while rocket-jumping)
        self.g15 = {}             # scoreboard slot -> {field: value} from g15_dumpplayer
        self.board = {}           # sid -> that slot's fields (TF2's exact team, kills, deaths...)
        self.board_prev = {}      # sid -> (kills, deaths) at the previous scoreboard read
        self.board_streaks = {}   # sid -> [current, best] killstreak from TF2's counters
        self.pending_deaths = []  # kill-feed deaths waiting to be confirmed by the scoreboard
        self.fake_deaths = {}     # sid -> Dead Ringer fakes caught this match
        self.classes = {}         # sid -> class, from the weapon of their latest kill
        self.streaks = {}         # sid -> [current killstreak, best this match]
        self.weapons = {}         # sid -> Counter of kills per weapon
        self.all_crits = {}       # sid -> [all kills, of which crits] for Say crits
        self.chat_queue = deque()      # your own chat actions: first in line, see send_next_chat
        self.announce_queue = deque()  # (queued at, command, text): lines the scanner says by itself
        self.chat_unconfirmed = deque()  # (sent at, text): sent, but not seen in TF2's console yet
        self.chat_sent_count = self.chat_refused_count = 0
        self.chat_sending = False
        self.chat_sent = deque(maxlen=20)  # lines the scanner said, so their echo isn't taken for yours
        self.chat_limit = ChatLimit()      # TF2's spam limit, fed by the scanner's lines and yours
        self.pair_kills = Counter()  # (killer sid, victim sid) -> kills this match
        self.chat_duels = []         # {"sids": (a, b), "score": {sid: kills}}, plus "group" for !duel all
        self.duel_recent = {}        # DUEL_LINES category -> its last 4 lines said, not repeated yet
        self.duel_names = {}         # sid -> name, for duelists who left the server (duels outlive servers)
        self.rcon_lost_at = None     # when TF2 stopped answering: a minute of that means it closed
        self.last_death = {}         # sid -> (time, killer name) of their latest death, for rage-quits
        self.connected_before = set()  # who was on TF2's scoreboard last read
        self.first_blood_open = False  # True only after seeing a map start live
        self.ai_on = False             # HoovyGPT: off every launch, so it never runs by surprise
        self.ai_muted = False          # anyone's "!badbot" in chat; "!goodbot" undoes it
        self.ai_refused_at = 0.0       # when a locked HoovyGPT last turned down a command
        self.ai_refusals = deque(maxlen=3)  # refusals said lately, not repeated yet
        self.chat_log = deque(maxlen=AI_CHAT_LOG)  # (time, "name: message", HoovyGPT's own?)
        self.ai_said = deque(maxlen=20)  # our own replies, never answered when they echo back
        self.map_name = ""             # from status
        self.hostname = ""             # the server's name, from status ("" off a server)
        self.server_slots = None       # (humans, max players) from status's "players :" line
        self.ai_asking = False         # a question is with the model
        self.ai_asked_at = 0.0         # when that question was typed
        self.ai_wants_question = False  # that question's reply is meant to ask something back
        self.ai_waiting = None         # the newest chat line, until the model is free for it
        self.ai_reply = []             # the one reply waiting for TF2's spam limit: (command, text)
        self.ai_reply_at = 0.0         # when its question was typed
        self.lists = {}
        self.cheater_ids = set()  # list entries marked cheater/exploiter (not just "suspicious")
        self.flag_images = {}     # country code -> tk.PhotoImage
        self.class_images = {}    # class -> tk.PhotoImage of TF2's scoreboard icon
        self.flags_requested = set()
        self.fake_ips = {}  # Steam ID -> fake IPv4, this match only (chat.fake_ip_of); never saved
        self.forget_live_clues()  # this match's chat, name changes, spawns and kill times (live_clues.py)
        self.avatar_images = {}   # sid -> tk.PhotoImage of their Steam avatar, next to their name
        self.avatars_requested = set()  # (sid, picture address) already asked for
        self.marks = load_json(MARKS_PATH, {})
        self.me = my_steamid()
        self.snapshot = 0
        self.alerted = set()      # (sid, flag text) already shown as a toast
        self.rcon_state = "starting"
        self.api_state = "ok" if cfg["steam_api_key"] else "no key"
        self.sh_state = "ok" if cfg["steamhistory_api_key"] else "no key"
        self.lists_state = "loading"
        self.demo_state = "starting"
        self.demo_counts = {}     # demo name -> {SteamID64: Counter(check: detections)}, this session
        self.demo_marked = set()  # demos the cheat check bookmarked, so TF2 keeps them
        self.demo_log = deque(maxlen=6)  # the last checks, newest first, for the Status page
        self.demo_view = None     # what the Cheat check tab shows: {"demo", "result", "names", "user_names"}
        self.demo_summary = ""    # its summary, like demo-analysis's command line
        self.demo_user_names = {}  # user id -> name, for checks that name their victim by user id
        self.demo_pings = {}      # sid -> last ping seen, kept for players who have left since
        self.idle_rejoined_at = 0.0  # when "retry" was last typed after an idle kick
        self.translator_lines = None  # the translator's chat queue, when it runs inside the scanner
        self.demo_alerted = {}    # (demo, sid) -> detections already alerted about
        self.demo_names = {}      # sid -> name, kept for players who have left since
        self.recording = False    # our ds_record runs (record_only_flagged); TF2 stops it when the match ends
        self.flagged_gone_at = None  # when the last flagged player left while recording
        self.match_joined_at = 0.0   # when the map last loaded: ds_record waits RECORD_AFTER_JOIN after it
        self.left_server = False     # "Disconnect" seen, and no server joined since
        self.selected = None
        self.feedback = ""
        self.visible = True
        self.dirty = True
        self.drag = None

        self.started_at = time.time()
        self.web = None           # the web window (web_ui.WebWindow) when the window is a web page
        self.web_actions = None   # clicks from the web page, run here on App's thread
        self.web_pushed_at = 0.0
        self.root = root = tk.Tk()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg=BG, highlightthickness=1, highlightbackground=BORDER, highlightcolor=BORDER)
        if not on_a_screen(cfg["x"] + 40, cfg["y"] + 10):
            cfg["x"], cfg["y"] = 20, 20  # its monitor isn't connected now: back to the main screen
        root.geometry(f"+{cfg['x']}+{cfg['y']}")
        self.font = (FONT_UI, 10)
        self.bold = (FONT_UI_BOLD, 10)
        self.small = (FONT_UI, 9)
        self.mono = (mono_family(root), 9)        # numbers, commands, ticks
        self.label_font = (FONT_LABEL, 10)        # uppercase labels and buttons

        self._build_shell()
        self.table.bind("<MouseWheel>", self._scroll)
        # Row widgets are created once and then only updated (screens.Side): rebuilding ~150
        # labels on every click made selecting a player lag.
        self.actions_state = None
        self.sort_column = None   # None = the default order (flagged players first)
        self.sort_descending = False
        self.search = ""          # what's typed in the search box, lowercase: only names with it show
        self._build_table()
        self._build_players_page()
        self._build_cheat_page()
        self._build_ai_page()
        self._build_chat_page()
        self._build_status_page()
        self._build_help_page()
        self.show_page(self.cfg["page"])
        self.width_spacer.config(width=self.window_width())
        # The table grows with long names and flags, or the window was resized: lay it out again.
        self.table.bind("<Configure>", self._table_resized)
        self._build_resize_handles()
        self.show_body()

        root.update_idletasks()
        round_window_corners(root)
        self.toast = Toast(root, (FONT_UI_BOLD, 12), (FONT_LABEL, 9))
        self.hud_init()
        self.token_panel = TokenPanel(root, cfg, self.toggle_token_panel)
        self.set_visible(False)
        for line in history or []:
            self.handle_line(line, live=False)

    # --- window -----------------------------------------------------------------

    def quit(self):
        """Stops the scanner and the translator inside it."""
        if self.web:
            x, y, w, h = self.web.where()
            self.cfg.update(x=x, y=y, web_width=w, web_height=h)
        else:
            self.cfg["x"], self.cfg["y"] = self.root.winfo_x(), self.root.winfo_y()
        save_config(self.cfg)
        self.root.destroy()

    # --- input from TF2 -----------------------------------------------------------

    def handle_line(self, line, live=True):
        """live=False for lines read back from earlier in the match: they update
        the player list and stats, but never say anything in chat."""
        if STATUS_HEADER_RE.search(line):
            # A new status listing starts: drop whoever wasn't in the previous one.
            for sid in [s for s, p in self.players.items() if p.snapshot < self.snapshot]:
                del self.players[sid]
            self.snapshot += 1
            self.dirty = True
        elif m := STATUS_RE.search(line):
            sid = to_steam64(m["sid"])
            p = self.players.get(sid)
            if p is None:
                p = self.players[sid] = Player(sid, m["sid"], 0, "", 0, 0)
                if self.cfg["steam_api_key"] or self.cfg["steamhistory_api_key"]:
                    self.lookups.put(sid)
                if self.cfg["profile_keywords"]:
                    self.profile_lookups.put(sid)
            elif p.name and p.name != m["name"]:
                self.name_changes.setdefault(sid, []).append(p.name)  # renamed mid-match (live_clues)
            p.userid, p.name, p.ping = int(m["userid"]), m["name"], int(m["ping"])
            p.connected, p.snapshot = connected_seconds(m["connected"]), self.snapshot
            p.last_seen = time.time()
            self.dirty = True
        elif LOBBY_HEADER_RE.search(line):
            self.lobby_team = {}
        elif m := LOBBY_MEMBER_RE.search(line):
            self.lobby_team[to_steam64(m["sid"])] = m["team"]
            self.dirty = True
        elif NO_LOBBY_RE.search(line):
            self.lobby_team = {}
        elif m := MAP_RE.match(line):
            self.map_name = m[1]
        elif m := HOSTNAME_RE.match(line):
            self.hostname = m[1]
            self.dirty = True
        elif m := PLAYERS_RE.match(line):
            self.server_slots = (int(m[1]), int(m[3]))
            self.dirty = True
        elif "Client reached server_spawn" in line:
            self.new_match()
        elif line.startswith("Disconnect"):
            self.fake_ips.clear()  # you left the server: its players' fake IPs go with it
            self.forget_live_clues()
            self.forget_server()
            self.recording = False  # TF2 stops a recording when you leave
            self.left_server = True
        elif line.endswith(IDLE_KICK):
            # TF2 logs idle kicks, so those leaves aren't mistaken for rage-quits.
            if sid := self.sid_by_name(line[:-len(IDLE_KICK)]):
                self.last_death.pop(sid, None)
        elif line == G15_DONE:
            self.scoreboard_read()
        elif m := G15_RE.match(line):
            self.g15.setdefault(int(m[2]), {})[m[1]] = m[3]
            self.dirty = True
        elif chat := parse_chat(line):  # before kills: "x :  I killed y with z." is chat
            me = self.players.get(self.me)
            if len(self.match_chat) < MATCH_CHAT_MAX:  # for live_clues: who said what, this match only
                self.match_chat.append((time.time(), self.sid_by_name(chat[0]), chat[0], chat[1]))
            # The translator reads chat from here, not from the file. Your own lines aren't passed on:
            # they're mostly the scanner's "X said: ..." posts, which would each cost a Google request.
            if live and self.translator_lines is not None and not (me and chat[0] == me.name):
                self.translator_lines.put(line)
            if live:
                self.note_my_chat(*chat)
                self.duel_command(*chat)
                self.translate_command(*chat)
                self.who_command(*chat)
                self.info_command(*chat)
                self.kick_command(*chat)
                self.ai_chat(*chat)
                self.log_chat(*chat)  # after: the question isn't part of its own context
        elif m := KILL_RE.match(line):
            killer, victim = self.sid_by_name(m["killer"]), self.sid_by_name(m["victim"])
            self.apply_kill(m, killer, 1)
            if killer and m["killer"] != m["victim"] and m["weapon"] in WEAPON_CLASS:
                self.classes[killer] = WEAPON_CLASS[m["weapon"]]  # their latest kill = current class
            if victim in self.streaks:
                self.streaks[victim][0] = 0  # dying ends the streak; the best stays
                self.dirty = True
            if live and victim in self.board:
                # Checked against the scoreboard once TF2 had time to count the death.
                self.pending_deaths.append({"time": time.time(), "m": m, "killer": killer, "victim": victim,
                                            "deaths": self.board_int(victim, "m_iDeaths")})
            elif live:
                self.duel_kill(m, killer, victim)
            if live:
                if killer and victim and killer != victim and len(self.kill_times) < MATCH_KILLS_MAX:
                    self.kill_times.append((time.time(), killer, victim, m["weapon"]))  # for spawn kills
                if victim and m["killer"] != m["victim"]:
                    self.last_death[victim] = (time.time(), m["killer"])  # for rage-quits
                self.ez_kill(m)
                self.humiliation(m)
                self.country_beef_kill(m)
                self.ez_extras(m)
            if m["killer"] != m["victim"]:
                self.first_blood_open = False  # history kills close it too: you joined mid-match

    def apply_kill(self, m, killer, sign):
        """Counts a kill-feed kill into the per-player stats (sign=-1 takes it back out)."""
        for tracked, counts in ((is_sniper_weapon(m["weapon"]), self.kills),
                                (m["weapon"] in RANDOM_CRIT_WEAPONS, self.crits)):
            if killer and tracked:
                stats = counts.setdefault(killer, [0, 0])
                stats[0] += sign
                stats[1] += sign * bool(m["crit"])
        if killer and m["killer"] != m["victim"]:
            total = self.all_crits.setdefault(killer, [0, 0])
            total[0] += sign
            total[1] += sign * bool(m["crit"])
            if m["weapon"] == "market_gardener" and m["crit"]:
                self.gardens[killer] = self.gardens.get(killer, 0) + sign
            if m["weapon"] not in NOT_A_WEAPON:
                self.weapons.setdefault(killer, Counter())[m["weapon"]] += sign
            if sign > 0:
                streak = self.streaks.setdefault(killer, [0, 0])
                streak[0] += 1
                streak[1] = max(streak[1], streak[0])
        self.count_duel(m["killer"], m["victim"], sign)
        victim = self.sid_by_name(m["victim"])
        if killer and victim and killer != victim:
            self.pair_kills[(killer, victim)] += sign  # who killed whom, for country scores
        for counts in (self.kills, self.crits, self.all_crits):  # a taken-back only kill leaves nothing
            if killer in counts and counts[killer][0] <= 0:
                del counts[killer]
        if killer in self.weapons:
            self.weapons[killer] = +self.weapons[killer]  # drops weapons at 0
        self.dirty = True

    def scoreboard_read(self):
        """A fresh scoreboard arrived: catch fake deaths, update killstreaks and
        spot rage-quits."""
        self.refresh_board()
        self.check_rage_quits()
        now = time.time()
        for sid, fields in self.board.items():
            # Respawns: TF2 prints none, so a dead -> alive flip between two reads (3 s apart) is the spawn.
            alive = fields.get("m_bAlive") == "true"
            if alive and self.alive_before.get(sid) is False:
                self.spawn_times.setdefault(sid, []).append(now)
            self.alive_before[sid] = alive
        still_pending = []
        for d in self.pending_deaths:
            if now - d["time"] < 1:
                still_pending.append(d)  # TF2 may not have counted it yet
                continue
            deaths = self.board_int(d["victim"], "m_iDeaths")
            if deaths is not None and d["deaths"] is not None and deaths <= d["deaths"]:
                # The feed said they died, TF2 never counted it: a Dead Ringer fake.
                self.apply_kill(d["m"], d["killer"], -1)
                self.fake_deaths[d["victim"]] = self.fake_deaths.get(d["victim"], 0) + 1
            else:
                self.duel_kill(d["m"], d["killer"], d["victim"])  # waits for this so Dead Ringers don't count
        self.pending_deaths = still_pending
        # Killstreaks from TF2's own kill and death counters: fakes can't inflate them.
        for sid in self.board:
            kills, deaths = self.board_int(sid, "m_iScore"), self.board_int(sid, "m_iDeaths")
            if kills is None or deaths is None:
                continue
            before = self.board_prev.get(sid)
            streak = self.board_streaks.setdefault(sid, [0, 0])
            if before:
                if deaths > before[1]:
                    streak[0] = 0
                elif kills > before[0]:
                    streak[0] += kills - before[0]
                streak[1] = max(streak[1], streak[0])
            self.board_prev[sid] = (kills, deaths)
        self.dirty = True

    def new_match(self):
        """You joined a server or the map changed: this-match stats start over, like
        TF2's own scoreboard. Duel scores carry on across matches. Nothing about the players
        is kept from one match to the next: their fake IPs are drawn again."""
        self.fake_ips.clear()
        self.forget_live_clues()
        self.forget_server()  # the next status names the server again
        self.recording, self.flagged_gone_at = False, None  # a new map ends TF2's recording
        self.match_joined_at = time.time()
        self.left_server = False
        for stats in (self.kills, self.crits, self.all_crits, self.gardens, self.classes,
                      self.streaks, self.weapons, self.g15, self.board, self.board_prev,
                      self.board_streaks, self.fake_deaths, self.pair_kills):
            stats.clear()
        self.pending_deaths = []  # chat duels carry on: they last until TF2 closes or "!duel reset"
        self.connected_before = set()  # a map change isn't everyone leaving
        self.last_death = {}
        self.first_blood_open = True   # a fresh map: its first kill is first blood
        self.table_widest = 0          # new players, new names: the table may get narrower
        self.dirty = True

    def forget_live_clues(self):
        """This match's raw data for the live cheater clues (live_clues.py), kept in memory only and
        dropped when the match ends or you leave, like fake_ips."""
        self.match_chat = []    # (time, sid or None, name, message)
        self.name_changes = {}  # sid -> their earlier names this match
        self.spawn_times = {}   # sid -> times the scoreboard showed them alive again after being dead
        self.alive_before = {}  # sid -> alive at the previous scoreboard read
        self.kill_times = []    # (time, killer sid, victim sid, weapon), live kill-feed kills

    def forget_server(self):
        """You left the server, or joined another: its name and player count go."""
        self.hostname, self.server_slots = "", None
        self.dirty = True

    def server_text(self):
        """(short label, "10/24") for the title bar; each "" when not known."""
        slots = f"{self.server_slots[0]}/{self.server_slots[1]}" if self.server_slots else ""
        return server_label(self.hostname), slots

    def sid_by_name(self, name):
        """The kill feed names players, not SteamIDs: None for names two players share."""
        sids = [p.sid for p in self.players.values() if p.name == name]
        return sids[0] if len(sids) == 1 else None

    def prune_stale(self):
        """Clears the list after leaving a server (status stops listing anyone)."""
        if self.rcon_state != "connected":
            return  # without RCON, status only runs when you type it
        cutoff = time.time() - max(30, 3 * self.cfg["scan_seconds"])
        stale = [sid for sid, p in self.players.items() if p.last_seen < cutoff]
        for sid in stale:
            del self.players[sid]
        if stale:
            self.dirty = True

    WEB_PUSH_SECONDS = 0.3  # how often the web page gets the state while it's shown

    def web_tick(self):
        """With the web window: runs its clicks here, and sends it the state (only what changed
        is sent, see web_ui.WebWindow.push)."""
        if not self.web:
            return
        import web_state
        while not self.web_actions.empty():
            name, args = self.web_actions.get()
            web_state.run_action(self, name, args)
            self.web_pushed_at = 0.0  # show the result at once
        if self.visible and time.time() - self.web_pushed_at >= self.WEB_PUSH_SECONDS:
            self.web_pushed_at = time.time()
            self.web.push(web_state.build(self))

    def reload_keys(self, now=None):
        """Picks up keys saved while the scanner runs (by the setup, or pasted into the secrets
        file): every few seconds, only when that file changed. Players already in the list are
        looked up again with the new key."""
        now = time.time() if now is None else now
        if now < getattr(self, "keys_checked", 0) + KEYS_CHECK_SECONDS:
            return
        self.keys_checked = now
        try:
            stamp = os.path.getmtime(settings.SECRETS_PATH)  # looked up now: the tests point it elsewhere
        except OSError:
            return
        if stamp == getattr(self, "keys_stamp", None):
            return
        self.keys_stamp = stamp
        stored = load_secrets()
        changed = [k for k in ("steam_api_key", "steamhistory_api_key", "gemini_api_key", "groq_api_key",
                                "deepl_api_key")
                   if stored.get(k) and stored[k] != self.cfg.get(k)]
        for key in changed:
            self.cfg[key] = stored[key]
        if "steam_api_key" in changed:
            self.api_state = "ok"
        if "steamhistory_api_key" in changed:
            self.sh_state = "ok"
        if {"steam_api_key", "steamhistory_api_key"} & set(changed):
            for sid in self.players:
                self.lookups.put(sid)
        if changed:
            found = "New key found: " + ", ".join(k.replace("_api_key", "") for k in changed)
            self.notify(found)
            self.toast.show(found, 0)  # over the game too: the window is usually hidden
            self.dirty = True

    def handle_event(self, event):
        """Takes one result from a background thread; event[0] says what kind it is."""
        kind = event[0]
        if kind == "summary" and (url := event[2].get("avatar")) and (event[1], url) not in self.avatars_requested:
            self.avatars_requested.add((event[1], url))
            threading.Thread(target=download_avatar, args=(event[1], url, self.events), daemon=True).start()
        if kind == "rcon":
            if event[1] != "connected" and self.rcon_state == "connected":
                self.rcon_lost_at = time.time()
            elif event[1] == "connected":
                self.rcon_lost_at = None
                if self.rcon_state != "connected":
                    self.sync_record_mode()
            self.rcon_state = event[1]
        elif kind == "api":
            self.api_state = event[1]
        elif kind == "sh":
            self.sh_state = event[1]
        elif kind == "class_icons":
            for cls, path in event[1].items():
                try:
                    self.class_images[cls] = tk.PhotoImage(file=path)
                except tk.TclError:
                    pass  # that class keeps showing its name
            self.redraw_rows()
        elif kind == "flag":
            _, code, path = event
            try:
                self.flag_images[code] = tk.PhotoImage(file=path)
            except tk.TclError:
                return  # not a usable picture: the code stays as text
            # Rows that show this country must redraw to swap the code for the flag.
            self.redraw_rows()
        elif kind == "avatar":
            _, sid, path = event
            try:
                self.avatar_images[sid] = tk.PhotoImage(file=path)
            except tk.TclError:
                return  # not a usable picture: the row keeps just the name
        elif kind == "summary" and (code := event[2].get("loccountrycode")) \
                and code not in self.flags_requested:
            self.flags_requested.add(code)
            threading.Thread(target=download_flag, args=(code, self.events), daemon=True).start()
            if event[1] in self.players:
                self.players[event[1]].summary = event[2]
        elif kind == "ai":
            self.ai_answered(*event[1:])
        elif kind == "translate_say":
            self.say_translated(*event[1:])
        elif kind == "translate_failed":
            self.notify(f"Couldn't translate {event[1]}'s !speak: {event[2]}")
        elif kind == "demo":
            self.demo_checked(*event[1:])
        elif kind == "demo_state":
            self.demo_state = event[1]
        elif kind == "ai_ready":
            self.ai_ready(event[1], event[2])
        elif kind == "lists":
            self.lists = event[1]
            self.cheater_ids = {sid for sid, entry in self.lists.items()
                                if entry["attributes"] & {"cheater", "exploiter"}}
            self.lists_state = f"{len(self.cheater_ids)} cheaters known"
        elif event[1] in self.players:  # summary / bans / sourcebans / hours / friends / level
            setattr(self.players[event[1]], kind, event[2])
            if kind == "friends":
                self.save_mark_friends(self.players[event[1]])
        self.dirty = True

    # --- TF2's scoreboard (g15_dumpplayer), with the kill feed as fallback ---------------

    def refresh_board(self):
        """Maps connected scoreboard slots to players by Steam account."""
        self.board = {}
        for slot, fields in self.g15.items():
            account = fields.get("m_iAccountID", "0")
            if account.isdigit() and int(account) and fields.get("m_bConnected") == "true":
                self.board[STEAM64_BASE + int(account)] = fields

    def board_int(self, sid, field):
        value = self.board.get(sid, {}).get(field)
        return int(value) if value is not None and value.lstrip("-").isdigit() else None

    def health_cell(self, p):
        """("💀", ...) when dead, else their health colored by how hurt they are,
        from TF2's scoreboard. The scoreboard has no max health, so it comes from
        their class; with no class known, plain HP thresholds are used."""
        fields = self.board.get(p.sid)
        if not fields:
            return "", TEXT2
        if fields.get("m_bAlive") == "false":
            return "💀", MUTED
        hp = self.board_int(p.sid, "m_iHealth")
        if hp is None:
            return "", TEXT2
        full = CLASS_MAX_HEALTH.get(self.player_class(p))
        share = hp / full if full else (1 if hp > 100 else 0.5 if hp > 50 else 0)
        color = HP_FG["over"] if share > 1 else HP_FG["high"] if share >= 0.66 else HP_FG["mid"] if share >= 0.33 else HP_FG["low"]
        return str(hp), color  # blue = overhealed, green, orange, red

    def board_text(self, p, field):
        value = self.board_int(p.sid, field)
        return "" if value is None else str(value)

    def player_class(self, p):
        return self.classes.get(p.sid, "")

    def player_streak(self, p):
        """(current, best this match) killstreak: TF2's counters when available, else the feed."""
        return tuple(self.board_streaks.get(p.sid) or self.streaks.get(p.sid, (0, 0)))

    def team_color(self, p):
        """RED/BLU, from the scoreboard (any server) or the matchmaking lobby."""
        return (G15_TEAMS.get(self.board_int(p.sid, "m_iTeam"))
                or GC_TEAM_COLOR.get(self.lobby_team.get(p.sid), ""))

    def team_of(self, p):
        """A player's side as seen from you: "YOU", "ALLY", "ENEMY", or "?" while it isn't known yet."""
        if p.sid == self.me:
            return "YOU"
        mine, theirs = self.team_color(self.players.get(self.me) or p), self.team_color(p)
        if self.me not in self.players or not mine or not theirs:
            return "?"
        return "ALLY" if mine == theirs else "ENEMY"

    def keep_names(self):
        """The names of the players here now stay as they are in a translation ("tomato"
        isn't a hair salon)."""
        tf2_translator.KEEP_NAMES = {p.name.strip() for p in self.players.values() if len(p.name.strip()) >= 3}

    def reevaluate(self):
        """Works out every player's flags again from everything known right now."""
        self.refresh_board()
        players = list(self.players.values())
        thieves = name_thieves(players)
        base = {p.sid: [] if p.sid == self.me else
                evaluate(p, self.cfg, self.lists, self.marks, thieves) for p in players}
        worst = {sid: max((s for s, _ in flags), default=-1) for sid, flags in base.items()}
        known_cheaters = self.cheater_ids | {int(k) for k in self.marks}
        mark_friends = {int(k): set(m.get("friends", ())) for k, m in self.marks.items()}
        for p in players:
            flags = base[p.sid]
            if p.sid != self.me:
                flags += friend_flags(p, players, known_cheaters, worst, mark_friends, self.cheater_name)
                if p.sid in self.kills and (hs := headshot_flag(self.kills[p.sid], self.cfg)):
                    flags.append(hs)
                if p.sid in self.crits and (crit := crit_flag(self.crits[p.sid], self.cfg)):
                    flags.append(crit)
                flags += demo_flags(self.demo_checks_of(p.sid), p.ping)
                flags.sort(reverse=True)
            self.flags[p.sid] = flags
            for severity, text in flags:
                # Counts change ("9/11 headshots"), the alert shouldn't repeat for each one.
                key = (p.sid, re.sub(r"\d+", "#", text))
                if severity >= 2 and key not in self.alerted:
                    self.alerted.add(key)
                    team = self.team_of(p)
                    where = {"ALLY": " · your team", "ENEMY": " · enemy team"}.get(team, "")
                    self.toast.show(f"⚠ {p.name}: {text}{where}", severity)

    # --- the live cheat check (demo_check.py) ---------------------------------------------

    def demo_checks_of(self, sid):
        """What the cheat check found on this player in every demo this session, added up."""
        total = Counter()
        for counts in self.demo_counts.values():
            total.update(counts.get(sid, {}))
        return total

    def demo_checked(self, name, result, outcome, log_names=None, user_names=None):
        """A result from demo_worker: demo-analysis's output for one demo. outcome: None while
        recording, "kept" or "deleted" when finished. Anything found in a demo being recorded
        bookmarks it, which also stops TF2 deleting it, and is saved next to it as a file."""
        detections = result.get("detections", [])
        seconds_read = result.get("duration", 0) * 0.015
        self.demo_counts[name] = count_checks(detections)
        found = {sid for sid in self.demo_counts[name] if sid != self.me}
        # Names from console.log for players who have left; the players here now have the latest.
        self.demo_names.update(log_names or {})
        self.demo_names.update((sid, p.name) for sid, p in self.players.items())
        self.demo_user_names.update(user_names or {})
        self.demo_user_names.update((p.userid, p.name) for p in self.players.values())
        if found and outcome != "deleted":
            path = os.path.join(demos_dir(self.cfg), name)
            saved = None
            try:
                names = {sid: self.demo_names.get(sid, "?") for sid in self.demo_counts[name]}
                save_detections(path, result, names)
                saved = detections_path(path)
                save_cheater_ticks(demos_dir(self.cfg), name, result, names, {self.me})
            except OSError as e:
                print(f"Couldn't save the cheat check's detections: {e}")
            self.show_demo_result(name, result, dict(self.demo_names), dict(self.demo_user_names),
                                  time.strftime("%H:%M:%S"), saved)
        # Strong finds get an alert from reevaluate, like every serious flag; weak ones get one here.
        for sid in found:
            total = sum(self.demo_counts[name][sid].values())
            if total > self.demo_alerted.get((name, sid), 0):
                self.demo_alerted[(name, sid)] = total
                if not STRONG_CHECKS.keys() & self.demo_counts[name][sid].keys():
                    text = demo_flags(self.demo_counts[name][sid])[0][1]
                    self.toast.show(f"⚠ {self.demo_names.get(sid, sid)}: {text} (weak)", 1)
        if found and outcome is None and name not in self.demo_marked and self.rcon_state == "connected":
            self.demo_marked.add(name)
            who = ", ".join(self.players[sid].name for sid in found if sid in self.players) or "a player"
            self.commands.put(f'ds_mark "cheat check: {console_safe(who)[:60]}"')
        names = [self.demo_names.get(sid, str(sid)) for sid in found]
        result = f"found {', '.join(names)}" if names else "nothing found"
        after = {"deleted": "finished, deleted", "kept": "finished, kept"}.get(outcome, "")
        line = f"{time.strftime('%H:%M:%S')}   {name}   {seconds_read / 60:.1f} min read   {result}"
        self.demo_log.appendleft(line + (f"   ({after})" if after else ""))
        self.demo_state = "checks about once a minute"
        self.reevaluate()

    def show_demo_result(self, demo, result, names, user_names, checked_at, saved_to=None):
        """Puts a cheat check result on the Cheat check tab."""
        self.demo_pings.update((sid, p.ping) for sid, p in self.players.items() if p.ping)
        self.demo_view = {"demo": demo, "result": result, "names": names, "user_names": user_names,
                          "pings": dict(self.demo_pings), "saved": saved_to}
        self.demo_summary = summary_text(demo, result, names, checked_at, saved_to)
        self.demo_meaning = meaning_text(result)
        lines = copy_lines(result, names, {self.me})
        if lines:  # what Copy gives, here too, to select and copy part of it
            self.demo_summary += "\n\nOne line per player (what Copy gives):\n" + "\n".join(lines)
        self.dirty = True

    # --- reconnecting before an idle kick --------------------------------------------------

    def retry_before_idle_kick(self):
        """Every tick: when you haven't touched mouse or keyboard for IDLE_RETRY_AT seconds (10 s
        before TF2's 3-minute idle kick) while on a server, types "retry" so you reconnect before
        the kick. Again after another IDLE_RETRY_AT seconds if you're still away."""
        if not self.cfg["idle_rejoin"] or self.rcon_state != "connected" or not self.players:
            return
        now = time.time()
        if seconds_since_input() >= IDLE_RETRY_AT and now - self.idle_rejoined_at >= IDLE_RETRY_AT:
            self.idle_rejoined_at = now
            self.commands.put("retry")
            self.toast.show("Idle for almost 3 minutes: typed retry before the kick", 1)

    def toggle_idle_rejoin(self):
        self.cfg["idle_rejoin"] = not self.cfg["idle_rejoin"]
        save_config(self.cfg)
        self.update_idle_button()

    def update_idle_button(self):
        on = self.cfg["idle_rejoin"]
        self.idle_button.show("ON" if on else "OFF", on)

    def votekick_demo_player(self):
        """The Votekick button on the Cheat check tab: for the player picked there."""
        p = self.players.get(self.demo_picked_sid)
        if not p:
            self.notify("Pick a player who's still in the server")
            return
        self.votekick_player(p)

    def copy_demo_lines(self):
        """The Copy button: one line per player found, each fitting one TF2 chat message."""
        lines = copy_lines(self.demo_view["result"], self.demo_view["names"], {self.me}) if self.demo_view else []
        if not lines:
            self.notify("Nothing found yet, so there's nothing to copy")
            return
        self.copy("\n".join(lines))
        self.notify(f"Copied {len(lines)} line{'s' * (len(lines) != 1)}")

    def evidence_player(self):
        """Who EXPORT EVIDENCE is for: the player picked in the Cheat check's list, else the one
        found with the most detections (never you). None when nobody was found."""
        counts = count_checks(self.demo_view["result"].get("detections", [])) if self.demo_view else {}
        if self.demo_picked_sid in counts:
            return self.demo_picked_sid
        found = sorted((sid for sid in counts if sid != self.me), key=lambda sid: -sum(counts[sid].values()))
        return found[0] if found else None

    def export_evidence(self):
        """The EXPORT EVIDENCE button: a folder next to the demos with the demo, its detections and
        report.txt for one player, opened in Explorer."""
        sid = self.evidence_player()
        if sid is None:
            self.notify("Nothing found yet, so there's no evidence to save")
            return
        view = self.demo_view
        name = view["names"].get(sid) or self.demo_names.get(sid) or str(sid)
        try:
            folder = export_evidence(demos_dir(self.cfg), view["demo"], view["result"], sid, name, view.get("saved"))
        except OSError as e:
            self.notify(f"Couldn't save the evidence: {e.strerror or type(e).__name__}")  # no paths on screen
            return
        self.notify(f"Evidence saved: {os.path.basename(folder)}")
        try:
            os.startfile(folder)
        except OSError:
            pass  # saved anyway; the feedback names the folder

    def open_detections_file(self):
        """The Open... button: shows a saved <demo>_detections.json, from this or an earlier match."""
        from tkinter import filedialog
        path = filedialog.askopenfilename(initialdir=demos_dir(self.cfg), title="Open a cheat check result",
                                          filetypes=[("Cheat check results", "*_detections.json")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                result = json.load(f)
            names = {int(sid): name for sid, name in result.get("players", {}).items()}
        except (OSError, ValueError) as e:
            self.notify(f"Couldn't open it: {e}")
            return
        demo = os.path.basename(path).replace("_detections.json", ".dem")
        self.show_demo_result(demo, result, names, dict(self.demo_user_names), "earlier (opened from a file)", path)

    def open_demos_folder(self):
        try:
            os.startfile(demos_dir(self.cfg))
        except OSError as e:
            self.notify(f"Couldn't open the demos folder: {e}")

    def check_demo_now(self):
        """The Check now button: the worker stops waiting for its next minute."""
        CHECK_NOW.set()
        self.notify("Checking the demo now")

    def toggle_demo_check(self):
        self.cfg["demo_check"] = not self.cfg["demo_check"]
        save_config(self.cfg)
        self.update_demo_buttons()

    def toggle_record_only_flagged(self):
        self.cfg["record_only_flagged"] = not self.cfg["record_only_flagged"]
        save_config(self.cfg)
        self.sync_record_mode()
        self.update_demo_buttons()

    def sync_record_mode(self):
        """Tells TF2 (over RCON, as the launch option +ds_enable does at start) whether it records
        every match (ds_enable 2) or only when the scanner says ds_record (ds_enable 0). Only with
        the cheat check on and demo-analysis installed: without them nothing is recorded for it."""
        if self.cfg["demo_check"] and os.path.exists(DEMO_TOOL):
            self.commands.put(f"ds_enable {0 if self.cfg['record_only_flagged'] else 2}")

    def flagged_in_match(self):
        """True when someone other than you has a serious flag (severity 2 or more) or your mark."""
        return any(sid != self.me and (str(sid) in self.marks
                                       or max((s for s, _ in self.flags.get(sid, [])), default=-1) >= 2)
                   for sid in self.players)

    def record_flagged_tick(self, now=None):
        """Every tick, with record_only_flagged: types ds_record once when a flagged player is in the
        match and nothing is recording, and ds_stop when none has been there for RECORD_STOP_AFTER
        seconds. TF2 names the demo itself (YYYY-MM-DD_HH-MM-SS.dem), so the cheat check finds it."""
        now = time.time() if now is None else now
        if self.rcon_state != "connected" or not self.players or self.left_server:
            self.recording, self.flagged_gone_at = False, None  # off a server: TF2 stopped by itself
            return
        if not (self.cfg["demo_check"] and self.cfg["record_only_flagged"]):
            return
        if self.flagged_in_match():
            self.flagged_gone_at = None
            if not self.recording and now - self.match_joined_at >= RECORD_AFTER_JOIN:
                self.recording = True
                self.commands.put("ds_record")
                self.dirty = True
        elif self.recording:
            if self.flagged_gone_at is None:
                self.flagged_gone_at = now
            elif now - self.flagged_gone_at >= RECORD_STOP_AFTER:
                self.recording, self.flagged_gone_at = False, None
                self.commands.put("ds_stop")
                self.dirty = True

    def record_text(self):
        """The recording line on the Cheat check page."""
        if not self.cfg["demo_check"]:
            return "Recording: off (the cheat check is off)"
        if not self.cfg["record_only_flagged"]:
            return "Recording: every match (TF2 records by itself)"
        if self.recording:
            return "Recording: on — flagged player in the match"
        return "Recording: not recording"

    def toggle_demo_keep(self):
        self.cfg["demo_keep_only_cheaters"] = not self.cfg["demo_keep_only_cheaters"]
        save_config(self.cfg)
        self.update_demo_buttons()

    def update_demo_buttons(self):
        for button, on in ((self.demo_check_button, self.cfg["demo_check"]),
                           (self.demo_keep_button, self.cfg["demo_keep_only_cheaters"]),
                           (self.demo_record_button, self.cfg["record_only_flagged"])):
            button.show("ON" if on else "OFF", on)

    def toggle_mark(self):
        """The Mark cheater / Unmark button: your own marks are saved in marks.json."""
        p = self.players.get(self.selected)
        if not p:
            return
        key = str(p.sid)
        if key in self.marks:
            del self.marks[key]
            self.notify("Unmarked")
        else:
            self.marks[key] = {"name": p.name, "reason": "cheater", "time": int(time.time())}
            self.save_mark_friends(p)
            self.notify(self.mark_note(p))
        save_json(MARKS_PATH, self.marks)
        self.dirty = True  # their flags change, and their friends'

    def save_mark_friends(self, p):
        """Keeps a marked player's friend list with the mark, so their friends are
        flagged as secondhand cheaters in later games too, even without them there."""
        mark = self.marks.get(str(p.sid))
        if mark is not None and isinstance(p.friends, set) and mark.get("friends") != sorted(p.friends):
            mark["friends"] = sorted(p.friends)
            save_json(MARKS_PATH, self.marks)

    def cheater_name(self, sid):
        """A player's name: in this lobby, as you marked them, or as a cheater list last saw them."""
        p = self.players.get(sid)
        return (p.name if p else "") or self.marks.get(str(sid), {}).get("name") or self.lists.get(sid, {}).get("name", "")

    def mark_note(self, p):
        """What marking p says: which known cheaters they're friends with."""
        if p.friends is PENDING:
            return "Marked. Their friend list is still loading"
        if not isinstance(p.friends, set):
            return "Marked. Their friend list is private"
        cheaters = sorted(p.friends & (self.cheater_ids | {int(k) for k in self.marks}) - {p.sid})
        if not cheaters:
            return "Marked. None of their friends are known cheaters"
        described = []
        for sid in cheaters:
            name = self.cheater_name(sid)
            if str(sid) in self.marks:
                described.append(f"{name} (marked by you)")
            elif name:
                n = len(self.lists[sid]["sources"])
                described.append(f"{name} (on {n} cheater list{'s' if n > 1 else ''})")
        more = max(0, len(described) - 5) + len(cheaters) - len(described)  # cut off, or unnamed
        return (f"Marked. Friends with {len(cheaters)} other cheater{'s' if len(cheaters) > 1 else ''}: "
                + ", ".join(described[:5]) + (f" +{more} more" if more > 0 else ""))

    def open_steamhistory(self):
        p = self.players.get(self.selected)
        if p:
            webbrowser.open(f"https://steamhistory.net/id/{p.sid}")

    # --- main loop ---------------------------------------------------------------------

    def run(self):
        """The main loop: every 150 ms it handles whatever came in from TF2 and the threads,
        then redraws the list if anything changed."""
        def tick():
            while not self.toggles.empty():
                self.toggles.get()
                self.set_visible(not self.visible)
            while not self.lines.empty():
                self.handle_line(self.lines.get())
            while not self.events.empty():
                self.handle_event(self.events.get())
            self.prune_stale()
            self.forget_duels_after_tf2_closed()
            self.retry_before_idle_kick()
            self.record_flagged_tick()
            if self.dirty:
                self.dirty = False
                self.reevaluate()
                self.keep_names()
                if self.selected not in self.players:
                    self.selected = None
                if self.visible:
                    self.render()
            self.check_refused_chat()
            self.reload_keys()
            self.web_tick()
            self.toast.tick()
            self.hud_tick()
            self.root.after(150, tick)

        def keep_on_top():
            for w in (self.root, self.toast.win, self.hud.win):
                w.attributes("-topmost", True)
                w.lift()
            self.root.after(2000, keep_on_top)

        tick()
        keep_on_top()
        self.token_panel_loop()
        self.root.mainloop()


RECORD_STOP_AFTER = 60  # seconds without a flagged player before our recording stops
RECORD_AFTER_JOIN = 10  # seconds after a map loads before ds_record: TF2 is still loading it
KEYS_CHECK_SECONDS = 5  # how often the secrets file is checked for new keys
IDLE_RETRY_AT = 170       # seconds without input: 10 s before the 3-minute kick (mp_idlemaxtime 3)


def seconds_since_input():
    """Seconds since your last mouse or keyboard input anywhere in Windows (GetLastInputInfo)."""
    import ctypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
    info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    return ((ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000


def forget_old_player_memory():
    """Earlier versions remembered players across matches (seen_players.json, fake_ips.json).
    Nothing is kept past a match any more: those files are deleted once, if they're still here."""
    old = [path for path in (SEEN_PATH, SEEN_PATH and SEEN_PATH + ".tmp", FAKE_IPS_PATH)
           if path and os.path.isfile(path)]
    for path in old:
        try:
            os.remove(path)
        except OSError as e:
            print(f"Couldn't delete {path}: {e}")
    if old:
        print("Deleted the player memory of an earlier version: "
              + ", ".join(os.path.basename(p) for p in old) + ". Players are only remembered during a match now.")


def main():
    """Starts it all: reads the settings, starts the background threads and hotkeys, then runs the App."""
    if sys.stdout is None:
        # Started without a console window (pythonw): keep messages and errors in a file.
        sys.stdout = sys.stderr = open(os.path.join(HERE, "scanner.log"), "w", encoding="utf-8",
                                       buffering=1)
    single_instance("tf2_lobby_scanner", "TF2 Toolbox is already running.\n"
                                         "Press F9 to show it.")
    cfg = load_config()
    tf2_translator.KEYS = cfg  # the DeepL key, also one saved while it runs (reload_keys)
    forget_old_player_memory()
    print("TF2 Toolbox running. Press F9 for its window; its X stops it.\n")
    print("TF2 launch options needed (Steam > TF2 > Properties > Launch options):")
    # The password stays out of scanner.log; it's in the secrets file.
    print("  " + re.sub(r"(\+rcon_password )\S+", r"\1<hidden>", launch_options(cfg)) + "\n")
    if not cfg["steam_api_key"]:
        print("No Steam API key yet: hours, account age and VAC bans are skipped.")
        print("  Get one free at https://steamcommunity.com/dev/apikey")
    if not cfg["steamhistory_api_key"]:
        print("No steamhistory.net key yet: community server bans are skipped.")
        print("  Get one free by logging in with Steam at https://steamhistory.net")
    if not (cfg["steam_api_key"] and cfg["steamhistory_api_key"]):
        print(f"  Paste them into {SECRETS_PATH} as STEAM_API_KEY=... and STEAMHISTORY_API_KEY=...\n")
    print(f"Press {cfg['toggle_key']} to show/hide the player list.")

    lines, events, toggles = queue.Queue(), queue.Queue(), queue.Queue()
    commands, lookups, profile_lookups = queue.Queue(), queue.Queue(), queue.Queue()
    history = current_match_lines(cfg["log_path"])
    threading.Thread(target=rcon_worker, args=(cfg, lines, commands, events), daemon=True).start()
    threading.Thread(target=tail, args=(cfg["log_path"], lines), daemon=True).start()
    threading.Thread(target=lists_worker, args=(cfg["lists"], events), daemon=True).start()
    threading.Thread(target=class_icons_worker, args=(cfg["log_path"], events), daemon=True).start()
    # Always on: it checks for keys per batch, so keys added while the scanner runs work at once.
    threading.Thread(target=lookup_worker, args=(cfg, lookups, events), daemon=True).start()
    threading.Thread(target=profile_worker, args=(cfg, profile_lookups, events), daemon=True).start()
    threading.Thread(target=demo_worker, args=(cfg, events), daemon=True).start()
    vk = key_to_vk(cfg["toggle_key"])
    threading.Thread(target=hotkey_listener, args=(vk, lambda: toggles.put(1)), daemon=True).start()
    def start(web=None, web_actions=None):
        """Builds App and runs it. With the web window, on its own thread (web_ui.run)."""
        app = App(cfg, lines, events, toggles, commands, lookups, profile_lookups, history)
        if web:
            app.web, app.web_actions = web, web_actions
            app.root.withdraw()  # the web window shows the list; Tk keeps the HUD, alerts and overlay
        # The chat translator runs inside the scanner, unless it's already open on its own.
        if claim_instance("tf2_chat_translator"):
            app.translator_lines = queue.Queue()
            app.translator = start_translator(master=app.root, chat_lines=app.translator_lines)
            app.translator[0].on_say = app.say_translation
            app.translator[0].on_add = app.translated
        else:
            print("The translator is already running in its own window, so it isn't started twice.")
        app.run()

    import web_ui
    if cfg["web_ui"] and web_ui.available():
        web_ui.run(cfg, start)
        os._exit(0)  # Tk lived on the other thread: skip Python's clean-up, which would touch it from here
    else:
        if cfg["web_ui"]:
            print("pywebview isn't installed: using the classic window. Run 1 - Install.bat to get the new one.")
        start()


if __name__ == "__main__":
    main()
