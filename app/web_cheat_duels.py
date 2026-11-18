"""Web window state and actions for the Cheat check and Duels pages (see web_state.py).

Both read what the Tk pages show (screens.py _build_cheat_page and _build_ai_page) and call the
same App methods. SteamIDs go to the page as text: JavaScript numbers can't hold 64 bits."""

import os
import re

from web_state import action, page


# --- Cheat check ---------------------------------------------------------------------------------

def _strength(check):
    from demo_check import STRONG_CHECKS
    return check in STRONG_CHECKS


def meaning_entries(result):
    """demo_check.meaning_text as a list for the "What these mean" box: check, strong, what it means."""
    from demo_check import meaning_text
    entries = []
    for block in meaning_text(result).split("\n\n"):
        lines = block.split("\n")
        if lines and lines[0]:
            entries.append({"check": lines[0], "strong": _strength(lines[0]),
                            "about": lines[1].strip() if len(lines) > 1 else "",
                            "meaning": " ".join(line.strip() for line in lines[2:])})
    return entries


def _picked_player(app, sids):
    """The player picked in the Players list (App.demo_picked_sid, as the Tk list keeps it), or the first."""
    sid = getattr(app, "demo_picked_sid", None)
    return sid if sid in sids else (sids[0] if sids else None)


def _det_key(det):
    return f"{det['tick']}|{det['algorithm']}"


DEFAULT_STATE = "checks about once a minute"  # App.demo_state between checks: the switch already says it
LOG_RE = re.compile(r"\s{3,}")


def log_entries(app):
    """App.demo_log (newest first) as {"time", "demo", "read", "found", "after"}: the parts of each line."""
    entries = []
    for line in app.demo_log:
        parts = LOG_RE.split(line)
        time_, demo, read, found = (parts + ["", "", "", ""])[:4]
        after = parts[4].strip("()") if len(parts) > 4 else ""
        entries.append({"time": time_, "demo": demo, "read": read, "found": found, "after": after})
    return entries


def found_short(found):
    """A log line's "found A, B" as "found 2 players" (the names are in the table), "nothing found" as is."""
    if not found.startswith("found "):
        return found
    n = len(found[6:].split(", "))
    return f"found {n} player{'s' * (n != 1)}"


def recording_state(app):
    """The live recording, shortly: ("on", text) while TF2 records for a flagged player, ("off", text) while
    it waits for one, None when the switches above already say it all (check off, or every match)."""
    if not app.cfg["demo_check"] or not app.cfg["record_only_flagged"]:
        return None
    return ("on", "Recording: flagged player in the match") if app.recording else ("off", "Not recording")


CANT_KICK = "Votes only work on your own team"  # the Votekick hover on a player on the other team


def kick_state(app, picked, names):
    """The Votekick button for the player picked in the Players list: {"ok", "why"}, why = its hover.
    It greys out (and says why) when the vote can't work, as votekick_player would refuse it."""
    p = app.players.get(picked) if picked is not None else None
    if not p:
        return {"ok": False, "why": "Pick a player who's still in the server"}
    if app.team_of(p) == "ENEMY":
        return {"ok": False, "why": CANT_KICK}
    return {"ok": True, "why": f"Starts a vote to kick {names.get(picked, p.name)}"}


def demo_table(app):
    """What was found in the checked demo: map, length, file name and one row per player and check."""
    from demo_check import duration_text, found_rows
    view = app.demo_view
    if not view:
        return None
    result = view["result"]
    rows = [dict(r, sid=str(r["sid"]), you=r["sid"] == app.me) for r in found_rows(result, view["names"])]
    return {"map": result.get("map", "?"), "duration": duration_text(result.get("duration", 0)),
            "file": os.path.basename(view["demo"]), "rows": rows}


@page("Cheat check")
def cheat_state(app):
    from demo_check import count_checks, detection_details
    from screens import RECORD_ONLY_FLAGGED_ABOUT
    view = app.demo_view
    detections = view["result"].get("detections", []) if view else []
    names = view["names"] if view else {}
    counts = count_checks(detections)
    # The Players list, as refresh_demo_browser fills it: most detections first.
    sids = sorted(counts, key=lambda sid: -sum(counts[sid].values()))
    players = [{"sid": str(sid), "name": names.get(sid, str(sid)), "count": sum(counts[sid].values()),
                "strong": any(_strength(c) for c in counts[sid])} for sid in sids]
    picked = _picked_player(app, sids)
    dets = sorted((d for d in detections if d["player"] == picked), key=lambda d: d["tick"])
    det_list = [{"key": _det_key(d), "tick": d["tick"], "check": d["algorithm"], "strong": _strength(d["algorithm"])}
                for d in dets]
    keys = [d["key"] for d in det_list]
    det_key = getattr(app, "web_demo_det", None)
    det_key = det_key if det_key in keys else (keys[0] if keys else None)
    details, goto = "", ""
    if det_key:
        det = dets[keys.index(det_key)]
        text = detection_details(det, names, view["user_names"], view.get("pings"))
        details, _, rest = text.partition("\n\nIn TF2's console")
        goto = rest.strip().splitlines()[-1] if rest else ""
    # The FOUND bar: who was found (not you), the most detections first; what exactly is in the table.
    found = [sid for sid in sids if sid != app.me]
    bar = None
    if found:
        top = counts[found[0]]
        total, strong = sum(top.values()), sum(n for c, n in top.items() if _strength(c))
        what = f"{total} detection{'s' * (total != 1)}" + (f" ({strong} strong)" if strong else " (all weak)")
        if len(found) > 1:
            what += f" · +{len(found) - 1} more player{'s' * (len(found) > 2)}"
        # red only when something an unmodified game can't do was found; weak finds stay orange
        bar = {"who": names.get(found[0], str(found[0])), "what": what, "strong": bool(strong)}
    log = log_entries(app)
    shown = os.path.basename(view["demo"]) if view else ""
    for entry in log:
        entry["found"] = found_short(entry["found"])
        if entry["demo"] == shown:
            entry["demo"] = ""  # the table below names it
    rec = recording_state(app)
    return {
        "check": bool(app.cfg["demo_check"]), "keep": bool(app.cfg["demo_keep_only_cheaters"]),
        "record_only": bool(app.cfg["record_only_flagged"]), "record_about": RECORD_ONLY_FLAGGED_ABOUT,
        "state": "" if app.demo_state in (DEFAULT_STATE, "off") else app.demo_state,
        "recording": rec and {"on": rec[0] == "on", "text": rec[1]},
        "log": log,
        "found": bar,
        "table": demo_table(app),
        "meaning": meaning_entries(view["result"] if view else None),
        "players": players, "picked": str(picked) if picked is not None else None,
        "dets": det_list, "det": det_key, "details": details, "goto": goto,
        "kick": kick_state(app, picked, names),
    }


@action("cheat_toggle_check")
def _cheat_toggle_check(app):
    app.toggle_demo_check()


@action("cheat_toggle_keep")
def _cheat_toggle_keep(app):
    app.toggle_demo_keep()


@action("cheat_toggle_record")
def _cheat_toggle_record(app):
    app.toggle_record_only_flagged()


@action("cheat_check_now")
def _cheat_check_now(app):
    app.check_demo_now()


@action("cheat_votekick")
def _cheat_votekick(app):
    """For the player the page shows picked (the first one until another is clicked), as the Tk list."""
    view = app.demo_view
    if view and getattr(app, "demo_picked_sid", None) is None:
        from demo_check import count_checks
        counts = count_checks(view["result"].get("detections", []))
        app.demo_picked_sid = _picked_player(app, sorted(counts, key=lambda sid: -sum(counts[sid].values())))
    app.votekick_demo_player()


@action("cheat_copy")
def _cheat_copy(app):
    app.copy_demo_lines()


@action("cheat_export")
def _cheat_export(app):
    app.export_evidence()


@action("cheat_open")
def _cheat_open(app):
    app.open_detections_file()


@action("cheat_open_folder")
def _cheat_open_folder(app):
    app.open_demos_folder()


@action("cheat_pick_player")
def _cheat_pick_player(app, sid):
    """A click in the Players list: what the Tk list's selection does (Votekick acts on them too)."""
    app.demo_picked_sid = int(sid)
    app.web_demo_det = None  # their first detection


@action("cheat_open_profile")
def _cheat_open_profile(app, sid):
    """A double-click in the Players list: their Steam profile, like the Tk list."""
    app.demo_picked_sid = int(sid)
    app._demo_open_profile()


@action("cheat_pick_det")
def _cheat_pick_det(app, key):
    app.web_demo_det = str(key)


@action("cheat_copy_goto")
def _cheat_copy_goto(app):
    """The Copy button next to demo_gototick: copies that line."""
    goto = cheat_state(app)["goto"]
    if goto:
        app.copy(goto)
        app.notify("Copied")


# --- Duels -----------------------------------------------------------------------------------------

DUEL_RE = re.compile(r"^(?P<a>.+) (?P<sa>\d+)-(?P<sb>\d+) (?P<b>.+)$")
LOCKS = ("off", "on", "muted")  # App.cfg["ai_lock"] (None = "off"), see ai.py ai_chat / refuse_ai_command
# The !badbot / !goodbot choice, named by what it does (ai.py): "off" lets anyone in chat mute
# (!badbot) or wake (!goodbot) Heavy; "on" and "muted" let only your own commands through (others
# get a no from Heavy) and keep Heavy talking or quiet until you change it.
LOCK_QUESTION = "Who can use !badbot and !goodbot"
LOCK_OPTIONS = (
    ("off", "Everyone", "Anyone in chat can mute Heavy with !badbot and wake him with !goodbot."),
    ("on", "Only you, Heavy talks", "Heavy keeps talking: others get a no from Heavy. Your own !badbot still mutes him."),
    ("muted", "Only you, Heavy quiet", "Heavy stays quiet: others get a no from Heavy. Your own !goodbot still wakes him."),
)


def _duel_side(app, name):
    """ "b" or "r": the team colour of a duelist by the name duel_entries shows, "" when not known."""
    from chat import duel_name
    if name in ("RED", "BLU"):
        return name[0].lower()
    for sid in app.players:
        if duel_name(app.duel_name_of(sid)) == name:
            return {2: "r", 3: "b"}.get(app.board_int(sid, "m_iTeam"), "")
    return ""


def duel_rows(app):
    """App.duel_entries as rows: {"a", "sa", "sb", "b", "ta", "tb", "label"} for a score, else {"text"}."""
    rows = []
    for entry in app.duel_entries():
        label = ""
        if entry.startswith("ALL vs ALL: "):
            label, entry = "ALL vs ALL", entry[len("ALL vs ALL: "):]
        m = DUEL_RE.match(entry)
        if m:
            rows.append({"a": m["a"], "sa": m["sa"], "sb": m["sb"], "b": m["b"], "label": label,
                         "ta": _duel_side(app, m["a"]), "tb": _duel_side(app, m["b"])})
        else:
            rows.append({"text": (label + ": " if label else "") + entry})
    return rows


def stop_preview(app):
    """The exact lines Stop all duels would post in chat (what "!duel stopall" says), for its hover:
    App.stop_all_duels run with its chat lines caught instead of sent. [] when it would post nothing."""
    if not app.chat_duels or app.me not in app.players:
        return []
    lines, duels, had = [], app.chat_duels, "announce_chat" in vars(app)
    old = vars(app).get("announce_chat")
    app.announce_chat = lambda text, command="say": lines.append(text)
    try:
        app.chat_duels = list(duels)
        app.stop_all_duels(app.me)
    finally:
        app.chat_duels = duels
        if had:
            app.announce_chat = old
        else:
            del app.announce_chat
    return lines


@page("Duels")
def duels_state(app):
    from ai import TOKEN_COLUMNS, TOKEN_NOTE, ai_quota, model_choices, token_rows
    from screens import DUEL_COMMANDS
    heavy = bool(app.cfg["heavy_talks"])
    state = {
        "heavy": heavy,
        "title": "HoovyGPT + Duels" if heavy else "Duels",
        "about": "Players start a duel by typing !duel and a name in chat.",
        "on": bool(app.ai_on),
        "text": "OFF" if not app.ai_on else "MUTED (!badbot)" if app.ai_muted else "ON",
        "duels": duel_rows(app),
        "commands": [list(c) for c in DUEL_COMMANDS],
        "stop_preview": stop_preview(app),
    }
    if heavy:
        name, model = app.model_shown()
        left, limit = ai_quota.left(model), ai_quota.daily_limit(model)
        state.update({
            "model": {"value": app.cfg["ai_model"], "name": name, "label": ai_quota.label(model),
                      "left": left, "limit": limit, "choices": [list(c) for c in model_choices()]},
            "lock": app.cfg["ai_lock"] or "off",
            "lock_question": LOCK_QUESTION, "lock_options": [list(o) for o in LOCK_OPTIONS],
            "tokens": {"columns": list(TOKEN_COLUMNS), "rows": [list(r) for r in token_rows(app.ai_models()[0][1])],
                       "note": TOKEN_NOTE},
        })
    return state


@action("duels_toggle")
def _duels_toggle(app):
    app.toggle_ai()


@action("duels_stop")
def _duels_stop(app):
    app.stop_duels_from_page()


@action("duels_model")
def _duels_model(app, model):
    """A pick in the Model dropdown: what the Tk Model menu does."""
    from ai import model_choices
    if model in {value for value, _ in model_choices()}:
        app.pick_model(model)


@action("duels_lock")
def _duels_lock(app, lock):
    if lock in LOCKS:
        app.pick_lock(None if lock == "off" else lock)

