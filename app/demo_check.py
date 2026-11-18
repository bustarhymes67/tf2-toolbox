"""The live cheat check: about once a minute, demo-analysis reads the demo TF2 is recording, and
once a demo is finished it's kept only when something was found in it.

demo-analysis (tools/demo-analysis.exe) is Nocrex's open-source checker, built unchanged from
https://github.com/Nocrex/demo-analysis at tag v3 (commit 7e3abad); see tools/README.md. It only
reads the demo file TF2 writes by itself, so nothing touches the game's memory."""

import json
import os
import re
import subprocess
import threading
import time
from collections import Counter

from game_log import STEAM64_BASE
from settings import HERE

DEMO_TOOL = os.path.join(HERE, "tools", "demo-analysis.exe")
DEMO_CHECK_SECONDS = 60
CHECK_NOW = threading.Event()  # set by the Check now button: the worker stops waiting
DEMO_RECORDING = 300       # seconds: the newest demo, written to more recently than this, is still being recorded
DEMO_TICK = 0.015          # seconds per demo tick on Valve's servers
DEMO_NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.dem$")  # TF2's own names, not renamed copies
# Checks an unmodified game can't trigger, whatever the ping: the strong evidence.
STRONG_CHECKS = {
    "nocrex/oob_pitch": "looked past the game's 89° limit",
    "viewangles_180degrees": "turned 180° in one tick",
}
# Patterns cheats make, but that high ping or packet loss can make too.
WEAK_CHECKS = {
    "doubletap": "double taps",
    "nocrex/angle_repeat": "one-tick aim jumps",
    "angle_history": "aim flicks",
    "nocrex/aimsnap": "aim snaps",
    "backtrack": "backtrack hits",
}


# What each check looks for, in plain words, from demo-analysis's own code (src/algorithms, tag v3).
CHECK_MEANING = {
    "nocrex/oob_pitch": "Aimed further up or down than TF2 allows (past 89.999 degrees). The game never sends "
                        "that by itself: only a modified game does, for anti-aim.",
    "viewangles_180degrees": "Turned around 180 degrees from one tick to the next.",
    "nocrex/angle_repeat": "The aim jumped away and came back to almost exactly the same spot (within 0.028 "
                           "degrees) over 3 ticks: how an aimbot snaps to a target and back.",
    "angle_history": "The aim held almost still (under 0.5 degrees), then flicked 10 degrees or more, "
                     "within 4 ticks.",
    "nocrex/aimsnap": "A snap of 10 degrees or more in the middle of tiny aim movements, within 5 ticks.",
    "doubletap": "Two hits faster than the weapon can fire (for example a Scout's scattergun under 17 ticks "
                 "apart): a fire-rate exploit.",
    "backtrack": "Hit a target where it was a few ticks earlier, from 200 to 600 units away: abusing the "
                 "game's lag compensation.",
}


def meaning_text(result=None):
    """The "What these mean" box: every check in this result (or every known check while there is
    no result yet), strong or weak, and what it looks for."""
    found = {d["algorithm"] for d in (result or {}).get("detections", [])}
    checks = [c for c in CHECK_MEANING if c in found] + sorted(found - set(CHECK_MEANING)) if found else list(CHECK_MEANING)
    blocks = []
    for check in checks:
        strength = "STRONG: an unmodified game can't do this" if check in STRONG_CHECKS else \
            "weak: lag or packet loss can cause it too"
        blocks.append(f"{check}\n  {strength}\n  {CHECK_MEANING.get(check, 'No description for this check.')}")
    return "\n\n".join(blocks)


def demos_dir(cfg):
    """TF2's demo folder: the demos folder next to console.log unless set."""
    return cfg["demos_dir"] or os.path.join(os.path.dirname(cfg["log_path"]), "demos")


def run_tool(path):
    """demo-analysis's result for one demo: {"detections", "duration" (ticks read), "map", ...};
    a detection is {"tick", "algorithm", "player", "data"}. It runs at the lowest priority, so
    the game keeps the CPU."""
    flags = getattr(subprocess, "IDLE_PRIORITY_CLASS", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    done = subprocess.run([DEMO_TOOL, "-i", path, "-q"], capture_output=True, timeout=300, creationflags=flags)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or "failed")
    return json.loads(done.stdout)


def count_checks(detections):
    """{SteamID64: Counter(check name: detections)}."""
    counts = {}
    for d in detections:
        counts.setdefault(d["player"], Counter())[d["algorithm"]] += 1
    return counts


HIGH_PING = 150  # ms: from here on lag can make the weak checks' patterns by itself


def ping_note(ping):
    """What a player's ping means for the weak checks, or "" when it says nothing."""
    return f"ping {ping} ms: lag alone can cause these" if ping and ping >= HIGH_PING else ""


def demo_flags(counts, ping=0):
    """A player's flags from their counts: one per strong check, and the weak ones together,
    with a warning when their ping is high enough to cause those by itself."""
    flags = [(3, f"demo check: {about} ({counts[name]}x)") for name, about in STRONG_CHECKS.items() if counts[name]]
    weak = [f"{counts[name]} {about}" for name, about in WEAK_CHECKS.items() if counts[name]]
    if weak:
        note = ping_note(ping)
        flags.append((1, f"demo check: {', '.join(weak)}" + (f" ({note})" if note else "")))
    return flags


# A player in TF2's status list: '#   2206 "last man"   [U:1:444555666]   04:41 ...'
STATUS_NAME_RE = re.compile(r'^#\s+(?P<userid>\d+)\s+"(?P<name>.*)"\s+\[U:1:(?P<account>\d+)\]')


def names_from_log(log_path):
    """({SteamID64: name}, {user id: name}) for everyone in console.log's status lists, the latest
    name winning. Someone found by the check may have left before the scanner saw them, and some
    checks name their victim by user id (the number in front of a name in status)."""
    by_sid, by_userid = {}, {}
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = STATUS_NAME_RE.match(line)
                if m:
                    by_sid[STEAM64_BASE + int(m["account"])] = m["name"]
                    by_userid[int(m["userid"])] = m["name"]
    except OSError:
        pass
    return by_sid, by_userid


def detections_path(dem_path):
    """Where a demo's detections are saved: next to it, as <demo>_detections.json."""
    return dem_path[:-4] + "_detections.json"


def save_detections(dem_path, result, names):
    """Saves demo-analysis's result as the GUI's "Save detections" would, plus the players' names."""
    data = dict(result, players={str(sid): name for sid, name in names.items()})
    with open(detections_path(dem_path), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# The copy line's words for each check.
COPY_TAG = "[demo-analysis by Nocrex]"  # starts every copied line: the checker that found it
COPY_LINK = "github.com/MegaAntiCheat"   # ends every copied line: where the checker lives
CHAT_BYTES = 127                         # what TF2 takes in one chat message
STRONG_SHORT = {"nocrex/oob_pitch": "anti-aim", "viewangles_180degrees": "spinbot"}


def check_order(check, count):
    """Strong checks first, then the most detections."""
    return check not in STRONG_CHECKS, -count, check


def clean_data(data):
    """A detection's data without the zero-width spaces demo-analysis puts in its keys to keep their order."""
    return {key.replace("\u200b", ""): value for key, value in data.items()}


def summary_text(demo_name, result, names, checked_at, saved_to=None):
    """Like demo-analysis's command-line summary, with each player's name next to their ID."""
    ticks = result.get("duration", 0)
    seconds = round(ticks * DEMO_TICK)
    detections = result.get("detections", [])
    lines = [f"Map: {result.get('map', '?')}",
             f"Duration: {seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02} ({ticks} ticks), checked {checked_at}",
             f"Demo: {demo_name}"]
    if saved_to:
        lines.append(f"Saved: {saved_to}")
    lines.append(f"Total detections: {len(detections)}")
    by_check = by_algorithm_text(result, names)
    if by_check:
        lines += ["", by_check]
    return "\n".join(lines)


def by_algorithm_text(result, names, skip=()):
    """The "Detections by algorithm" block: per check how many players and detections, strong
    checks first, and each player's name, Steam ID and count. "" when nothing was found."""
    by_check = {}
    for det in result.get("detections", []):
        if det["player"] not in skip:
            by_check.setdefault(det["algorithm"], Counter())[det["player"]] += 1
    if not by_check:
        return ""
    lines = ["Detections by algorithm:"]
    for check, players in sorted(by_check.items(), key=lambda kv: check_order(kv[0], sum(kv[1].values()))):
        n = sum(players.values())
        strength = f"STRONG ({STRONG_SHORT[check]})" if check in STRONG_SHORT else "weak"
        lines.append(f"  {check}: {len(players)} player{'s' * (len(players) != 1)}, {n} detection{'s' * (n != 1)}   {strength}")
        lines += [f"    {names.get(sid, '?')} ({sid}): {k}" for sid, k in players.most_common()]
    return "\n".join(lines)


def copy_lines(result, names, skip=()):
    """One line per player found, most detections first, each fitting one TF2 chat message:
    "[demo-analysis by Nocrex]: PLAYER: name | oob_pitch 23 STRONG, angle_repeat 22 | github.com/MegaAntiCheat"."""
    lines = []
    counts = count_checks(result.get("detections", []))
    for sid, checks in sorted(counts.items(), key=lambda kv: -sum(kv[1].values())):
        if sid in skip:
            continue
        parts = [f"{check.removeprefix('nocrex/')} {n}" + (" STRONG" if check in STRONG_CHECKS else "")
                 for check, n in sorted(checks.items(), key=lambda kv: check_order(*kv))]
        lines.append(fit_copy_line(names.get(sid, "?"), parts))
    return lines


def fit_copy_line(name, parts):
    """The copied line for one player, cut to CHAT_BYTES: as many checks as fit, cutting a long
    name before dropping a check; the dropped ones (the smallest) become "+N more"."""
    line = ""
    for keep in range(len(parts), 0, -1):
        found = ", ".join(parts[:keep]) + (f" +{len(parts) - keep} more" if keep < len(parts) else "")
        for shown in [name] + ([name[:15] + "…"] if len(name) > 16 else []):
            line = f"{COPY_TAG}: PLAYER: {shown} | {found} | {COPY_LINK}"
            if len(line.encode("utf-8")) <= CHAT_BYTES:
                return line
    while len(line.encode("utf-8")) > CHAT_BYTES:
        line = line[:-1]
    return line


CHEATERS_TXT = "cheaters.txt"  # in the demos folder: one block per demo with a cheater
CHEATERS_HEAD = ("Cheaters found by demo-analysis by Nocrex (github.com/MegaAntiCheat), one block per demo.\n"
                 "While a demo plays, jump to a tick in TF2's console with: demo_gototick <tick>\n")
DEMO_BLOCK_RE = re.compile(r"^=== (\S+\.dem) ===$")


def cheaters_txt_path(folder):
    return os.path.join(folder, CHEATERS_TXT)


def cheater_block(demo_name, result, names, skip=()):
    """One demo's block: the demo's file name, then each player found with the ticks of each check."""
    ticks = {}
    for det in result.get("detections", []):
        if det["player"] not in skip:
            ticks.setdefault(det["player"], {}).setdefault(det["algorithm"], []).append(det["tick"])
    if not ticks:
        return ""
    lines = [f"=== {demo_name} ==="]
    for sid, checks in sorted(ticks.items(), key=lambda kv: -sum(map(len, kv[1].values()))):
        lines.append(f"{names.get(sid, '?')} ({sid})")
        for check, found in sorted(checks.items(), key=lambda kv: check_order(kv[0], len(kv[1]))):
            strong = " STRONG" if check in STRONG_CHECKS else ""
            lines.append(f"  {check.removeprefix('nocrex/')}{strong}: ticks {', '.join(map(str, sorted(found)))}")
    return "\n".join(lines) + "\n"


def save_cheater_ticks(folder, demo_name, result, names, skip=()):
    """Updates the one cheaters.txt: this demo's block is replaced when it's there (a demo still
    being recorded is checked again and again), else added at the end."""
    path = cheaters_txt_path(folder)
    blocks, current = {}, None
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                m = DEMO_BLOCK_RE.match(line.rstrip("\n"))
                if m:
                    current = m[1]
                    blocks[current] = ""
                if current:
                    blocks[current] += line
    except FileNotFoundError:
        pass
    block = cheater_block(demo_name, result, names, skip)
    if block:
        blocks[demo_name] = block
    else:
        blocks.pop(demo_name, None)
    with open(path, "w", encoding="utf-8") as f:
        f.write(CHEATERS_HEAD + "".join("\n" + b.rstrip("\n") + "\n" for b in blocks.values()))


EVIDENCE_CREDIT = "Found by demo-analysis by Nocrex (github.com/Nocrex/demo-analysis)"
EVIDENCE_NAME_CHARS = 40  # the player's name in the folder's name is cut to this


def safe_file_part(text):
    """text usable in a Windows folder name: no \\ / : * ? " < > | or control characters, no
    dots or spaces at the end, cut to EVIDENCE_NAME_CHARS. "player" when nothing is left."""
    text = re.sub(r'[\\/:*?"<>|\x00-\x1f\x7f]', "", text)
    text = " ".join(text.split())[:EVIDENCE_NAME_CHARS].rstrip(" .")
    return text or "player"


def evidence_folder_name(name, demo_name):
    """ "evidence <player name> <demo date>": the demo's date is its TF2 name without .dem."""
    stem = demo_name[:-4] if demo_name.lower().endswith(".dem") else demo_name
    return f"evidence {safe_file_part(name)} {safe_file_part(stem)}"


def evidence_report(sid, name, demo_name, result, demo_missing=False):
    """report.txt of an evidence folder: who, which demo, and per check how many detections, how
    strong, what it means, every tick, and the command to jump to the first one."""
    ticks = result.get("duration", 0)
    seconds = round(ticks * DEMO_TICK)
    by_check = {}
    for det in result.get("detections", []):
        if det["player"] == sid:
            by_check.setdefault(det["algorithm"], []).append(det["tick"])
    lines = ["Cheat check evidence", "",
             f"Player: {name}",
             f"SteamID64: {sid}",
             f"Profile: https://steamcommunity.com/profiles/{sid}",
             f"Map: {result.get('map', '?')}",
             f"Demo: {demo_name}"]
    if demo_missing:
        lines.append("  The demo file is gone (deleted or moved), so it isn't in this folder.")
    lines += [f"Duration: {seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02} ({ticks} ticks)",
              f"Detections: {sum(map(len, by_check.values()))}"]
    for check, found in sorted(by_check.items(), key=lambda kv: check_order(kv[0], len(kv[1]))):
        found.sort()
        strength = "STRONG: an unmodified game can't do this" if check in STRONG_CHECKS else \
            "weak: lag or packet loss can cause it too"
        lines += ["",
                  f"{check}: {len(found)} detection{'s' * (len(found) != 1)}, {strength}",
                  f"  What it means: {CHECK_MEANING.get(check, 'No description for this check.')}",
                  f"  Ticks: {', '.join(map(str, found))}",
                  f"  In TF2's console while playing the demo: demo_gototick {found[0]}"]
    lines += ["", EVIDENCE_CREDIT]
    return "\n".join(lines) + "\n"


def export_evidence(folder, demo_name, result, sid, name, detections_file=None):
    """Makes the evidence folder for one player next to the demos: a copy of the demo (if it's
    still there), its saved detections (if there are any) and report.txt. Returns its path."""
    import shutil
    target = os.path.join(folder, evidence_folder_name(name, demo_name))
    os.makedirs(target, exist_ok=True)
    dem_path = os.path.join(folder, demo_name)
    demo_missing = not os.path.isfile(dem_path)
    if not demo_missing:
        shutil.copy2(dem_path, os.path.join(target, demo_name))
    saved = detections_file if detections_file and os.path.isfile(detections_file) else detections_path(dem_path)
    if os.path.isfile(saved):
        shutil.copy2(saved, os.path.join(target, os.path.basename(saved)))
    with open(os.path.join(target, "report.txt"), "w", encoding="utf-8") as f:
        f.write(evidence_report(sid, name, demo_name, result, demo_missing))
    return target


def detection_details(det, names, user_names, pings=None):
    """One detection as text, as gui.exe shows it, with names instead of numbers, the player's
    ping, and the console command to jump to it in the demo."""
    details = {"player": names.get(det["player"], "?"), "steamid": det["player"], "tick": det["tick"],
               "check": det["algorithm"], "strength": "STRONG" if det["algorithm"] in STRONG_CHECKS else "weak"}
    ping = (pings or {}).get(det["player"])
    if ping:
        note = ping_note(ping) if det["algorithm"] not in STRONG_CHECKS else ""
        details["ping"] = f"{ping} ms" + (f" ({note.split(': ', 1)[1]})" if note else "")
    data = clean_data(det.get("data", {}))
    if isinstance(data.get("victim"), int):
        data["victim"] = f"{user_names.get(data['victim'], '?')} (user {data['victim']})"
    details.update(data)
    return (json.dumps(details, indent=2, ensure_ascii=False) +
            f"\n\nIn TF2's console, while playing the demo:\ndemo_gototick {max(0, det['tick'] - 200)}")


def has_bookmark(dem_path):
    """True when TF2's .json next to the demo has a bookmark (yours, or one the check made)."""
    try:
        with open(dem_path[:-4] + ".json", encoding="utf-8") as f:
            return any(e.get("name") == "Bookmark" for e in json.load(f).get("events", []))
    except (OSError, ValueError):
        return False


def tidy_finished(dem_path, detections, keep_only_cheaters):
    """What happens to a finished demo: "kept" when something was found or it's bookmarked,
    "deleted" (with its .json) when keep_only_cheaters is on and neither, else "kept"."""
    if detections or has_bookmark(dem_path) or not keep_only_cheaters:
        return "kept"
    for path in (dem_path, dem_path[:-4] + ".json", detections_path(dem_path)):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
    return "deleted"


def aim_check(path, finished):
    """The aim clues (demo_clues.py) on the same demo: a demo being recorded is queued for their own
    background thread (at most every few minutes); a finished one is read now, before it may be
    deleted. Nothing here raises."""
    try:
        import demo_clues
    except ImportError:
        return
    if finished:
        demo_clues.analyse(path)
    else:
        demo_clues.request(path)


def demo_worker(cfg, events):
    """Background thread: checks the demo being recorded every DEMO_CHECK_SECONDS, and each demo
    once more when it's finished. Only demos seen being recorded while the scanner ran are ever
    deleted, so older ones are left alone."""
    if not os.path.exists(DEMO_TOOL):
        events.put(("demo_state", "tools\\demo-analysis.exe is missing"))
        return
    watched = set()  # demos seen being recorded
    checked = {}     # demo name -> ((size, modified), result) of its last check
    while True:
        if not cfg["demo_check"]:
            events.put(("demo_state", "off"))
            CHECK_NOW.wait(5)
            CHECK_NOW.clear()
            continue
        folder = demos_dir(cfg)
        try:
            names = [n for n in os.listdir(folder) if DEMO_NAME_RE.match(n)]
        except OSError:
            names = []
        # Only the newest demo can be the one being recorded. An older one, or one nothing was written
        # to for 5 minutes, is finished: TF2 doesn't write every second, so a short pause isn't the end.
        newest = max(names, default=None, key=lambda n: os.path.getmtime(os.path.join(folder, n)))
        recording = {newest} if newest and time.time() - os.path.getmtime(os.path.join(folder, newest)) < DEMO_RECORDING else set()
        for name in sorted(recording | (watched - recording)):
            path = os.path.join(folder, name)
            finished = name not in recording
            if finished and not os.path.exists(path):  # TF2's own auto-delete got there first
                watched.discard(name)
                checked.pop(name, None)
                continue
            try:
                stamp = os.path.getsize(path), os.path.getmtime(path)
            except OSError:
                continue
            # Nothing new written (in a menu, dead, between rounds): its last result still stands.
            # A recording demo is then skipped; a finished one uses that result for its last check.
            if checked.get(name, (None,))[0] == stamp:
                if not finished:
                    continue
                result = checked[name][1]
            else:
                events.put(("demo_state", "checking..."))
                try:
                    result = run_tool(path)
                except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as e:
                    events.put(("demo_state", f"couldn't read {name}: {e}"))
                    continue
                checked[name] = stamp, result
            aim_check(path, finished)
            outcome = None
            if finished:
                watched.discard(name)
                checked.pop(name, None)
                outcome = tidy_finished(path, result["detections"], cfg["demo_keep_only_cheaters"])
            else:
                watched.add(name)
            names = names_from_log(cfg["log_path"]) if result["detections"] else ({}, {})
            events.put(("demo", name, result, outcome, *names))
        if not recording and not watched:
            events.put(("demo_state", "waiting for TF2 to record a demo (it starts when you join a match)"))
        CHECK_NOW.wait(DEMO_CHECK_SECONDS)
        CHECK_NOW.clear()
