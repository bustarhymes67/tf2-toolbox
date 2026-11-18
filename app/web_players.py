"""Web window state and actions for the Players page (see web_state.py): the filter chips, the
search box, the Columns menu, both teams' lists and the selected player's panel. Everything comes
from App's own methods (screens.py); this only turns it into JSON for web/pages/players.js."""
import base64
import os
import re
from collections import Counter

import cheat_score
from game_log import CLASS_MAX_HEALTH
from player_flags import flag_why, profile_flags
from screens import (BLANK_CELLS, COLUMN_NAMES, COLUMNS, FILTERS, HEADERS, HIDEABLE_COLUMNS, PICKABLE_COLUMNS,
                     PLAYER_ACTIONS, flag_tag, short_cell)
from settings import CLASS_ICONS_DIR, FLAGS_DIR, HP_FG, SEVERITY_FG
from tf2_icons import ICON_SIZE
from web_state import action, page

# The worst flag's severity as the mark's colour, the verdict over the panel and its words.
MARKS = {3: "red", 2: "org", 1: "yel"}
VERDICTS = {3: "CHEATER", 2: "SUSPICIOUS", 1: "WEAK FLAG"}
# player_flags.flag_why's levels, as the panel's strength boxes (the words stay the app's own).
STRENGTH_CLASS = {"weak": "weak", "medium": "medium", "strong": "strong", "proven": "strong",
                  "yours": "strong", "info": "info"}
SIDE_WORDS = {"YOU": "You", "ALLY": "Team", "ENEMY": "Enemy", "?": "Team not known"}
ACTION_METHODS = {key: method for _, entries in PLAYER_ACTIONS for key, _, method in entries}

DEMO_PROOF_FLAG, DEMO_WEAK_FLAG = r"^demo check: (looked past|turned 180)", r"^demo check: \d"
# The cheater score (cheat_score.py): which flags each clue key is about, so WHY FLAGGED can put the
# clue's multiplier on its flag. A clue whose text is a flag's own text matches that flag first.
CLUE_FLAGS = {
    "lists": r"^on .* lists?\b", "marked": r"^marked by you", "bot_name": r"copied someone's name",
    "bans": r"VAC ban|game ban", "community_ban": r"community banned", "server_bans": r"server bans?",
    "experience": r"^new account|^only \d", "profile": r"private profile|never set up|level 0|limited account",
    "profile_words": r"profile comment|^bio says", "friends": r"^secondhand cheater|^friends with (flagged|\d)",
    "demo_weak": DEMO_WEAK_FLAG, "hs_record": r"headshots in one life", "hs_rate": r"% headshots", "crit_rate": r"crit kills",
}
# Short words for the band chip in the Flags column.
BAND_SHORT = {"Clean": "CLEAN", "Watch": "WATCH", "Suspicious": "SUSP", "Likely": "LIKELY", "Proven": "PROVEN"}

# "Likely together": TF2 doesn't tell clients who is in a party with whom, so players on the same
# team who joined the server within this many seconds of each other are shown as a guess.
TOGETHER_SECONDS = 5
PARTY_MAX = 6  # TF2's biggest party: a bigger cluster is a map change (everyone rejoins at once)
TOGETHER_WHY = ("TF2 doesn't show other players' parties, so this is a guess: these players are on the same team "
                "and joined the server within 5 seconds of each other, which usually means they queued together "
                "as a party. Bot groups often join together the same way. It can be wrong: players who happened "
                "to join at the same moment look the same.")

_pictures = {}  # path -> (modified time, data: URI)


def picture(path):
    """A small PNG as a data: URI, or None while it isn't there. The window's page is served from
    web/ only, so pictures beside it (class_icons/, flags/) can't be linked to."""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    cached = _pictures.get(path)
    if not cached or cached[0] != mtime:
        try:
            with open(path, "rb") as f:
                cached = _pictures[path] = (mtime, "data:image/png;base64," + base64.b64encode(f.read()).decode())
        except OSError:
            return None
    return cached[1]


def class_icon(cls):
    return picture(os.path.join(CLASS_ICONS_DIR, f"{cls}-{ICON_SIZE}px.png")) if cls else None


def country_flag(code):
    return picture(os.path.join(FLAGS_DIR, f"{code}.png")) if code else None


def worst(app, p):
    return max((s for s, _ in app.flags.get(p.sid, [])), default=-1)


def cell_json(app, p, column, cell):
    """One cell of a row: its text and colour, plus what the page draws for that column."""
    text, fg = cell[:2]
    out = {"t": text, "c": fg}
    if column == "Mark":
        severity = worst(app, p)
        out = {"m": MARKS.get(severity, "none"), "title": VERDICTS.get(severity, "no flags").lower()}
    elif column == "Ctry":
        out["img"] = country_flag(text) if text not in BLANK_CELLS else None
    elif column == "Class":
        out["img"] = class_icon(text)
    elif column == "Player":
        out = {"t": p.name, "you": p.sid == app.me}
    elif column == "HP":
        full = CLASS_MAX_HEALTH.get(app.player_class(p))
        if text.isdigit():
            hp = int(text)
            share = hp / full if full else (1 if hp > 100 else 0.5 if hp > 50 else 0.15)
            out.update(pct=round(min(share, 1) * 100, 1), max=full)
    elif column == "K/D":
        kills, deaths = app.board_text(p, "m_iScore"), app.board_text(p, "m_iDeaths")
        out = {"k": kills or "0", "d": deaths or "0"} if kills or deaths else {"t": ""}
    elif column == "Flags":
        flags = app.flags.get(p.sid, [])
        tag = flag_tag(flags[0][1], flags[0][0]) if flags else None
        out["tag"] = list(tag) if tag else None
    return out


def join_moment(p):
    """When they joined the server: status's connected time was measured at their last status line."""
    return p.last_seen - p.connected


def likely_groups(app):
    """[{"n": 1, "colour": "BLU", "sids": [...]}] for players on the same team who joined within
    TOGETHER_SECONDS of each other (of the group's first joiner), oldest group first. Only groups
    of 2 up to PARTY_MAX; players whose team colour isn't known aren't grouped."""
    teams = {}
    for p in app.players.values():
        colour = app.team_color(p)
        if colour:
            teams.setdefault(colour, []).append(p)
    found = []
    for colour, members in teams.items():
        members.sort(key=join_moment)
        cluster = []
        for p in members + [None]:
            if p is not None and cluster and join_moment(p) - join_moment(cluster[0]) <= TOGETHER_SECONDS:
                cluster.append(p)
                continue
            if 2 <= len(cluster) <= PARTY_MAX:
                found.append((join_moment(cluster[0]), colour, cluster))
            cluster = [p]
    found.sort(key=lambda f: (f[0], f[1]))
    return [{"n": i, "colour": colour, "sids": [str(p.sid) for p in cluster], "names": [p.name for p in cluster]}
            for i, (_, colour, cluster) in enumerate(found, 1)]


def lineup(app, group, strip):
    """The pills on a team's title line: how many of each class, then the rest of App's
    team_strip (average hours, new accounts)."""
    classes = Counter(filter(None, map(app.player_class, group))).most_common()
    pills = [[str(n), cls] for cls, n in classes]
    pills += [["", part] for part in strip.split(" · ")
              if part and not any(part == f"{n} {cls}" for cls, n in classes) and not part.endswith(" more")]
    return pills


def score_json(app, p, sc):
    """A row's score: the band chip and the tooltip's breakdown (None for you)."""
    if p.sid == app.me:
        return None
    b = cheat_score.breakdown(sc)
    b["short"] = BAND_SHORT.get(sc.band, "")
    return b


def flag_clue(text, clues):
    """The clue a flag is about, or None."""
    for c in clues:
        if c.text == text:
            return c
    for c in clues:
        pattern = CLUE_FLAGS.get(c.key)
        if pattern is None and c.proof and c.key.startswith("demo"):
            pattern = DEMO_PROOF_FLAG
        if pattern and re.search(pattern, text, re.I):
            return c
    return None


def reasons_json(app, p, sc):
    """WHY FLAGGED: each flag with its strength and, when the score used it, the clue's multiplier
    (once per clue); then the clues no flag shows (e.g. many hours lowering the odds)."""
    reasons, used = [], set()
    for sev, text in app.flags.get(p.sid, []) + profile_flags(p.profile):
        level, why = flag_why(sev, text)
        c = flag_clue(text, sc.clues)
        lr = None
        if c and c.key not in used:
            used.add(c.key)
            lr = cheat_score.lr_text(c.lr)
        reasons.append({"level": level.upper(), "cls": STRENGTH_CLASS.get(level, "weak"), "text": text, "why": why,
                        "lr": lr, "up": bool(c and c.lr >= 1)})
    rest = [c for c in sc.clues if c.key not in used]
    for c in rest:
        if not cheat_score.is_small(c):
            reasons.append({"level": "SCORE", "cls": "info", "text": c.text, "why": c.why,
                            "lr": cheat_score.lr_text(c.lr), "up": c.lr >= 1})
    small = cheat_score.small_row(rest)  # the tiny ones (x0.9-x1.1) as one line, like the tooltip
    if small:
        reasons.append({"level": "SCORE", "cls": "info", "text": small["text"], "why": small["why"],
                        "lr": small["lr"], "up": small["up"]})
    return reasons


def team_block(app, key, side, cells, groups, scores):
    """One of App.team_sides' halves as a block on the page."""
    title, _, entries, strip = side
    if not entries:
        return None
    players = [e[1] for e in entries if e[0] == "player"]
    # Before a "TEAM NOT KNOWN YET" line: this team's own players (the title counts only those).
    cut = next((i for i, e in enumerate(entries) if e[0] == "team"), len(entries))
    own = [e[1] for e in entries[:cut]]
    colour = next((c for c in map(app.team_color, own) if c), "")
    name = title.split(" · ")[0].split("     ")[0].strip()
    group_of = {sid: g["n"] for g in groups for sid in g["sids"]}
    rows = []
    for e in entries:
        if e[0] == "team":
            rows.append({"sub": e[1]})
            continue
        p = e[1]
        rows.append({"sid": str(p.sid), "sel": p.sid == app.selected, "grp": group_of.get(str(p.sid)),
                     "score": score_json(app, p, scores[p.sid]),
                     "cells": [cell_json(app, p, c, cell) for c, cell in zip(COLUMNS, cells[p.sid])]})
    return {"key": key, "name": name, "colour": colour, "count": len(own),
            "flagged": sum(1 for p in own if worst(app, p) >= 1), "lineup": lineup(app, players, strip), "rows": rows,
            "groups": sum(1 for g in groups if colour and g["colour"] == colour)}


def together(p, groups):
    """{"n": group number, "names": the others in it} for the panel, or None outside any group."""
    g = next((g for g in groups if str(p.sid) in g["sids"]), None)
    return g and {"n": g["n"], "names": [name for sid, name in zip(g["sids"], g["names"]) if sid != str(p.sid)]}


def panel(app, groups, scores):
    """The selected player's panel, or None while nobody is selected."""
    p = app.players.get(app.selected)
    if not p:
        return None
    severity = worst(app, p)
    team = app.team_of(p)
    hp, hp_fg = app.health_cell(p)
    kills, deaths = app.board_int(p.sid, "m_iScore"), app.board_int(p.sid, "m_iDeaths")
    sc = scores.get(p.sid) or cheat_score.score(app, p)
    reasons = reasons_json(app, p, sc)
    # player_details without the team and class the line above already shows.
    about = app.player_details(p).split(" · ")
    about = [part for part in about if part not in (team, app.player_class(p))]
    enabled = app.applicable(p)
    marked = str(p.sid) in app.marks
    muted = p.sid in app.cfg["speak_muted"]
    labels = {"mark": "Unmark" if marked else "Mark cheater", "mute": "Unmute !speak" if muted else "Mute !speak"}
    return {
        "sid": str(p.sid), "name": p.name, "you": p.sid == app.me, "enemy": team == "ENEMY",
        "verdict": VERDICTS.get(severity), "mark": MARKS.get(severity),
        "side": SIDE_WORDS[team], "cls": app.player_class(p), "about": " · ".join(about),
        "kd": f"{kills}/{deaths}" if kills is not None or deaths is not None else "",
        "ratio": f"{(kills or 0) / max(1, deaths or 0):.2f}" if kills is not None or deaths is not None else "",
        "hp": hp, "hp_c": hp_fg, "reasons": reasons, "score": score_json(app, p, sc),
        "together": together(p, groups),
        "actions": [[[key, labels.get(key, text), key in enabled] for key, text, _ in entries]
                    for _, entries in PLAYER_ACTIONS],
    }


@page("Players")
def players_state(app):
    """The same list App.render draws: chips with counts, who's shown, which columns, both teams."""
    everyone = app.sorted_players()
    others = [p for p in everyone if p.sid != app.me]
    scores = {p.sid: cheat_score.score(app, p) for p in everyone}

    def matches(p, name):
        # Cheaters: the old rule (a red flag or your mark) or the score's band Likely / Proven.
        return cheat_score.is_cheater(app, p, scores[p.sid]) if name == "cheaters" else app.matches_filter(p, name)
    counts = {name: sum(matches(p, name) for p in others) for name, _ in FILTERS[1:]}
    counts["all"] = len(everyone)
    chosen = app.cfg["player_filter"]
    players = [p for p in everyone if p.sid == app.me or matches(p, chosen)]
    if app.search:
        players = [p for p in players if app.search in p.name.casefold()]
    empty = "" if players else ("Nobody here matches that." if everyone
                                else "Waiting for TF2…  Start the game and this fills up by itself."
                                if app.rcon_state != "connected" else "No players yet (join a server)")
    cells = {p.sid: tuple(short_cell(c, cell) for c, cell in zip(COLUMNS, app.row_cells(p))) for p in players}
    picked = set(app.cfg["columns"]) | {"Mark", "Player"}
    shown = [c for i, c in enumerate(COLUMNS) if c in picked
             and not (c in HIDEABLE_COLUMNS and all(row[i][0] in BLANK_CELLS for row in cells.values()))]
    groups = likely_groups(app)
    teams = []
    if players:
        sides = app.team_sides(players)
        teams = [b for b in (team_block(app, key, side, cells, groups, scores) for key, side in sides.items()) if b]
    return {
        "filter": chosen,
        "filters": [{"key": key, "text": text, "n": counts.get(key, 0)} for key, text in FILTERS],
        "search": app.search,
        "columns": [{"key": c, "name": COLUMN_NAMES.get(c, c), "on": c in app.cfg["columns"]} for c in PICKABLE_COLUMNS],
        "all_columns": list(COLUMNS),
        "shown": shown,
        "headers": {c: HEADERS.get(c, c) for c in COLUMNS},
        "sort": [app.sort_column, app.sort_descending] if app.sort_column else None,
        "empty": empty,
        "teams": teams,
        "hp_colours": HP_FG,
        "severity_colours": {str(k): v for k, v in SEVERITY_FG.items()},
        "groups": groups,
        "together_why": TOGETHER_WHY,
        "panel": panel(app, groups, scores),
    }


# --- what the page's clicks do ----------------------------------------------------------------

@action("players_filter")
def _filter(app, name):
    if name in dict(FILTERS):
        app.set_filter(name)


@action("players_search")
def _search(app, text):
    app.set_search(str(text))


@action("players_column")
def _column(app, column):
    if column in PICKABLE_COLUMNS:
        app.toggle_column(column)


@action("players_sort")
def _sort(app, column):
    if column in COLUMNS:
        app.sort_by(column)


@action("players_select")
def _select(app, sid):
    """A click on a row: selects them, or deselects them when they already were (App.select)."""
    sid = int(sid)
    if sid in app.players:
        app.select(sid)


@action("players_deselect")
def _deselect(app):
    if app.selected is not None:
        app.select(app.selected)


@action("players_lobby")
def _lobby(app, which):
    """The toolbar's Say in chat buttons."""
    {"summary": app.say_lobby_summary, "kill_race": app.say_kill_race}[which]()


@action("players_act")
def _act(app, key):
    """A button in the selected player's panel, only when it applies to them (as the Tk panel
    greys out the rest)."""
    p = app.players.get(app.selected)
    if p and key in ACTION_METHODS and key in app.applicable(p):
        getattr(app, ACTION_METHODS[key])()

