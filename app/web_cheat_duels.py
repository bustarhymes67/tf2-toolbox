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


def short_paths(summary):
    """The summary without the folders in its "Saved:" line: only the file's name (no user names on the page)."""
    return "\n".join(f"Saved: {os.path.basename(line[7:])}" if line.startswith("Saved: ") else line
                     for line in summary.split("\n"))


@page("Cheat check")
def cheat_state(app):
    from demo_check import check_order, count_checks, detection_details
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
    # The FOUND bar: who was found (not you), the most detections first, and what on the first.
    found = [sid for sid in sids if sid != app.me]
    bar = None
    if found:
        top = counts[found[0]]
        what = [f"{n} {c.removeprefix('nocrex/')} ({'strong' if _strength(c) else 'weak'})"
                for c, n in sorted(top.items(), key=lambda kv: check_order(*kv))]
        if len(found) > 1:
            what.append(f"+{len(found) - 1} more player{'s' * (len(found) > 2)}")
        bar = {"who": names.get(found[0], str(found[0])), "what": " · ".join(what)}
    return {
        "check": bool(app.cfg["demo_check"]), "keep": bool(app.cfg["demo_keep_only_cheaters"]),
        "record_only": bool(app.cfg["record_only_flagged"]), "record_about": RECORD_ONLY_FLAGGED_ABOUT,
        "recording": app.recording, "record": app.record_text(),
        "state": f"Cheat check: {app.demo_state}",
        "log": list(app.demo_log),
        "found": bar,
        "summary": short_paths(app.demo_summary) or "Nothing found yet.",
        "meaning": meaning_entries(view["result"] if view else None),
        "players": players, "picked": str(picked) if picked is not None else None,
        "dets": det_list, "det": det_key, "details": details, "goto": goto,
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
LOCKS = ("off", "on", "muted")  # the Who can mute Heavy choices: Anyone, Stays on, Stays muted


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
    }
    if heavy:
        name, model = app.model_shown()
        left, limit = ai_quota.left(model), ai_quota.daily_limit(model)
        state.update({
            "model": {"value": app.cfg["ai_model"], "name": name, "label": ai_quota.label(model),
                      "left": left, "limit": limit, "choices": [list(c) for c in model_choices()]},
            "lock": app.cfg["ai_lock"] or "off",
            "tokens": {"columns": list(TOKEN_COLUMNS), "rows": [list(r) for r in token_rows(app.ai_models()[0][1])],
                       "note": TOKEN_NOTE},
            "token_window": bool(app.cfg["token_panel"]),
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


@action("duels_token_window")
def _duels_token_window(app):
    app.toggle_token_panel()
