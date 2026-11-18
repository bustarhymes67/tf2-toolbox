"""Demo clues: how a player's aim moves, from the demo TF2 is recording.

demo-analysis (tools/demo-analysis.exe, Nocrex's v3 cli.exe, unchanged) has a non-default
algorithm, viewangles_to_csv, that the shipped program can run: `-a viewangles_to_csv`. It writes
./output/viewangles_to_csv.csv (relative to the folder it runs in) with one row per player per
tick while they are alive and in the recorder's view (PVS): tick, name, [U:1:x], position x/y/z,
yaw, pitch. That is all it gives. It has NO shots, NO kills, NO damage, NO teams and NO line of
sight (demo-analysis's own kill list is commented out in v3). So:

1. Aim smoothness ("demo_aim_lock"): human flicks speed up and slow down over several ticks and
   often overshoot and correct; an aimbot jumps to the spot and stops dead. Per player: of their
   fast flicks, how many end at full speed and are then still ("hard stops"). Compared with the
   other players in the same demo (robust z and a binomial tail against the lobby's rate), so the
   demo's angle precision (other players' yaw comes in steps of ~0.35 deg, pitch ~0.7 deg) and the
   server's tick rate hit everyone alike.
2. Flick-to-target time ("demo_fast_acquire"): NOT true reaction time. With no line of sight and no
   shot/kill ticks, the time from "an enemy becomes visible" to "the shot" can't be measured. What
   can: a flick that starts with a player well off the crosshair (10+ deg) and ends with the
   crosshair on them, staying on them for a few ticks. Its duration (still -> on target) is the
   motor part of a reaction. Landing on a body in ONE angle update is what an aimbot does; a much
   bigger share of those than the rest of the lobby raises the odds.

What would be needed for real reaction time: demo-analysis built with a custom algorithm that also
outputs player_death / player_hurt events (with ticks, attacker, victim) and the shots fired, plus
map geometry for line of sight. The shipped cli.exe can't do that, so it isn't faked here.

It runs after demo-analysis on the same demo: the tool and the maths both in separate processes at
idle priority (started from a background thread), cached per demo. Only small per-player statistics
are kept, in memory, for this session (the CSV is read and deleted at once; nothing is saved).
Other players' angles in a demo come in steps (yaw ~0.35 deg, pitch ~0.7 deg) and in updates 1-8
ticks apart (their frame rate / packet loss); the measures adapt to each player's update rate and
leave out players whose updates are too far apart to judge."""

import csv
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from array import array
from bisect import bisect_left
from types import SimpleNamespace

try:
    from cheat_score import Clue, register
except ImportError:  # cheat_score.py not there (yet): the analysis still works, nothing is registered
    from dataclasses import dataclass

    @dataclass
    class Clue:
        key: str
        lr: float
        text: str
        why: str
        proof: bool = False
        source: str = ""

    def register(fn):
        return fn

STEAM64_BASE = 76561197960265728
TICK_MS = 15                 # one server tick on Valve's servers
SID_RE = re.compile(r"^\[U:1:(\d+)\]$")

# --- reading the CSV ---------------------------------------------------------------------------
GAP_TICKS = 4.0      # more time than this between two samples: dead, out of view or lag; no speed across it
YIELD_ROWS = 20000   # rows between short sleeps, so the scanner's window keeps the CPU (Python's GIL)

# --- aim movement (degrees per tick of 15 ms) --------------------------------------------------
STILL = 0.8          # at or below: still. A bit over one pitch step (0.706 deg), so precision noise is "still"
FLICK_PEAK = 6.0     # a flick peaks at 6+ deg/tick (400 deg/s): fast, not tracking
FLICK_MIN_TURN = 10.0  # and turns 10+ deg in all
STRAIGHT = 0.5       # turn/path: under this it went there and back (that's Nocrex's angle_repeat, not counted here)
HARD_SHARE = 0.6     # a hard stop: the flick's last update still moves at 60%+ of its peak, then still
UPDATE_TICKS = 2.0   # other players' angles change at most this far apart while they turn (measured on a demo)
STILL_TICKS = 4.0    # "then still": no change over STILL for this long (longer than an update gap)
MIN_CADENCE_GAPS = 50  # angle changes needed to measure a player's update cadence
MAX_CADENCE = 4.0    # updates further apart than this (low frame rate, packet loss): too coarse to judge
OVERSHOOT_TICKS = 8  # looked for a correction this long after a flick
OVERSHOOT_DEG = 0.7  # moved back against the flick by at least this much

# --- flick onto a target ------------------------------------------------------------------------
ACQ_MIN_TURN = 15.0  # only flicks of 15+ deg
ACQ_FROM = 10.0      # the target was 10+ deg off the crosshair when the flick started
EYE = 68.0           # eye height over the feet (most classes; 65-75)
BODY = (20.0, 40.0, 60.0, 75.0)  # heights on the target's body the crosshair may be on
HALF_WIDTH = 24.0    # half a player's width: how far off-center still is "on them"
AIM_SLACK = 1.0      # deg: the angles' precision in the demo
HOLD_SAMPLES = 3     # stays on target for 3 samples...
HOLD_TICKS = 8.0     # ...within 8 ticks after the flick
HOLD_SLACK = 1.5     # deg, more slack while following a moving target
DIST = (100.0, 3000.0)  # units: closer or further says nothing about aim
ACQ_WINDOW = 30.0    # ticks (450 ms) from the flick's start to land on the target, corrections included
FAST_UPDATES = 1     # still -> on target in one angle update: "fast" (a snap)

# --- comparing with the lobby ---------------------------------------------------------------------
MIN_FLICKS, MIN_LOBBY_FLICKS = 30, 20      # judged flicks needed for the player / for each lobby player
MIN_ACQ, MIN_LOBBY_ACQ = 10, 5
MIN_LOBBY_PLAYERS = 4
# LR estimates (not measured): what share of cheaters vs honest players look like this.
# Hard stops: a rage aimbot makes them on most flicks; smoothed aimbots don't, and lag (choke, packet
# loss) can merge a human's slowing ticks into one, so it's kept weak: at most x4.
LOCK_LR_MAX = 4.0
# Snaps onto a target: a human's 15+ deg flick that lands and stays on a body usually takes several
# updates (on two real demos 1 in 12 to 1 in 5 took one); an aimbot's takes one. Lag merges updates too: at most x5.
FAST_LR_MAX = 5.0
# Lots of judged flicks that look like everyone else's: a mild hint of honest aim. Mild, because a
# closet cheater's smoothed aimbot looks human too.
HUMAN_LR, HUMAN_MIN_FLICKS = 0.9, 150
# The two clues measure related things (a snap onto a target is often a hard stop): when both are
# up, the smaller one only counts with this power, so they aren't counted twice.
OVERLAP_POWER = 0.5
HIGH_PING, HIGH_PING_SHARE = 150, 0.5      # ms; from there lag makes snaps too: half the effect

RECHECK_SECONDS = 240   # a demo still being recorded is read again at most this often

_lock = threading.Lock()       # one analysis at a time
_store_lock = threading.Lock()
RESULTS = {}                   # demo name -> {"stamp", "stats", "at", "error"}: this session only
_pending = {}                  # demo name -> path waiting for the background thread
_wake = threading.Event()
_thread = None


# --- geometry ---------------------------------------------------------------------------------

def direction(yaw, pitch):
    """Unit vector of a view (Source: yaw from +x towards +y, pitch positive looking down)."""
    y, p = math.radians(yaw), math.radians(pitch)
    cp = math.cos(p)
    return cp * math.cos(y), cp * math.sin(y), -math.sin(p)


def angle(a, b):
    """Degrees between two unit vectors."""
    return math.degrees(math.acos(max(-1.0, min(1.0, a[0] * b[0] + a[1] * b[1] + a[2] * b[2]))))


def wrap(deg):
    return (deg + 180.0) % 360.0 - 180.0


class Track:
    """One player's samples in time order: t (ticks, float), x, y, z, yaw, pitch."""
    __slots__ = ("t", "x", "y", "z", "yaw", "pitch")

    def __init__(self):
        for name in self.__slots__:
            setattr(self, name, array("f"))

    def __len__(self):
        return len(self.t)

    def add(self, t, x, y, z, yaw, pitch):
        self.t.append(t), self.x.append(x), self.y.append(y), self.z.append(z)
        self.yaw.append(yaw), self.pitch.append(pitch)

    def view(self, i):
        return direction(self.yaw[i], self.pitch[i])

    def at(self, t, slack=1.0):
        """Index of the sample nearest to time t, within slack ticks, or None."""
        i = bisect_left(self.t, t)
        best = None
        for j in (i - 1, i):
            if 0 <= j < len(self.t) and abs(self.t[j] - t) <= slack and (best is None or abs(self.t[j] - t) < abs(self.t[best] - t)):
                best = j
        return best


def steam64(text):
    m = SID_RE.match(text.strip())
    return STEAM64_BASE + int(m[1]) if m else None


def read_tracks(lines):
    """{SteamID64: Track} from viewangles_to_csv's rows. Its rows are sorted by player then tick,
    but rows with the same tick come newest first (it pops its history before a stable sort), so
    each tick's rows are reversed. Exact repeats within a tick are dropped, and when one tick has
    several samples they are spread over the ticks before it (at most one tick apart)."""
    tracks, pending = {}, {}

    def flush(sid):
        tick, rows = pending.pop(sid)
        rows.reverse()
        unique = [r for i, r in enumerate(rows) if i == 0 or r != rows[i - 1]]
        track = tracks.setdefault(sid, Track())
        last = track.t[-1] if len(track) else None
        k = len(unique)
        step = 1.0 if last is None else min(1.0, (tick - last) / k)
        for j, r in enumerate(unique):
            track.add(tick - step * (k - 1 - j), *r)

    reader = csv.reader(lines)
    next(reader, None)  # the header
    for n, row in enumerate(reader):
        if n % YIELD_ROWS == YIELD_ROWS - 1:
            time.sleep(0.002)
        if len(row) < 8:
            continue
        sid = steam64(row[2])
        try:
            tick = int(row[0])
            values = tuple(float(v) for v in row[3:8])
        except ValueError:
            continue
        if sid is None or any(math.isnan(v) for v in values):
            continue
        if sid in pending and pending[sid][0] != tick:
            flush(sid)
        pending.setdefault(sid, (tick, []))[1].append(values)
    for sid in list(pending):
        flush(sid)
    return tracks


# --- flicks -------------------------------------------------------------------------------------

def segments(track):
    """(first, last) sample index of each stretch without a gap over GAP_TICKS."""
    out, first = [], 0
    for i in range(1, len(track)):
        if track.t[i] - track.t[i - 1] > GAP_TICKS:
            out.append((first, i - 1))
            first = i
    if len(track):
        out.append((first, len(track) - 1))
    return out


def moves_of(track, first, last, views):
    """[(index, turn deg)] of each angle change over STILL within one segment."""
    return [(i, a) for i in range(first + 1, last + 1) if (a := angle(views[i - 1], views[i])) > STILL]


def cadence(track, views=None):
    """How many ticks apart this player's angle updates come while they turn: the 75th percentile
    of the gaps between changes (gaps up to 8 ticks). Other players' angles don't change every tick
    even while they turn: they come with their usercmds, every 1-2 ticks at a normal frame rate,
    every 4-8 at a low one or with packet loss. None with too few changes to tell."""
    views = views or [track.view(i) for i in range(len(track))]
    gaps = []
    for first, last in segments(track):
        changes = [i for i, _ in moves_of(track, first, last, views)]
        gaps += [g for a, b in zip(changes, changes[1:]) if (g := track.t[b] - track.t[a]) <= 8]
    if len(gaps) < MIN_CADENCE_GAPS:
        return None
    gaps.sort()
    return gaps[int(0.75 * (len(gaps) - 1))]


def flicks(track, views=None, update=None):
    """The flicks in one track: dicts with start/end sample, peak and turn (deg), whether it was
    judged (enough time seen after it), a hard stop, and corrected (overshoot).

    Speed is measured per update: the turn since the last sample over the time since the last
    change, counted as at most `update` ticks (the player's cadence, at least UPDATE_TICKS); a
    movement ends when nothing changed for longer than that, and "still after it" means no change
    over STILL for twice that (at least STILL_TICKS)."""
    views = views or [track.view(i) for i in range(len(track))]
    update = max(UPDATE_TICKS, update or 0)
    still_ticks = max(STILL_TICKS, 2 * update)
    found = []
    for first, last in segments(track):
        moves, changed = [], first
        for i, turn in moves_of(track, first, last, views):
            moves.append((i, turn / max(min(track.t[i] - track.t[changed], update), 0.5)))
            changed = i
        j = 0
        while j < len(moves):
            run = [moves[j]]
            j += 1
            while j < len(moves) and track.t[moves[j][0]] - track.t[run[-1][0]] <= update:
                run.append(moves[j])
                j += 1
            start, end = run[0][0] - 1, run[-1][0]
            speeds = [sp for _, sp in run]
            peak, turn = max(speeds), angle(views[start], views[end])
            path = sum(angle(views[i - 1], views[i]) for i, _ in run)
            if peak < FLICK_PEAK or turn < FLICK_MIN_TURN or turn < STRAIGHT * path:
                continue
            next_move = track.t[moves[j][0]] if j < len(moves) else None
            still_for = (next_move if next_move is not None else track.t[last]) - track.t[end]
            judged = still_for >= still_ticks or next_move is not None
            hard = still_for >= still_ticks and speeds[-1] >= HARD_SHARE * peak
            found.append({"start": start, "end": end, "peak": peak, "turn": turn, "judged": judged,
                          "hard": hard, "corrected": corrected(track, start, end)})
    return found


def corrected(track, start, end):
    """True when the aim went past where the flick ended and came back (an overshoot and its
    correction), looking OVERSHOOT_TICKS past the flick: along the flick's direction, the furthest
    point is OVERSHOOT_DEG or more beyond where the aim settled."""
    cos_p = math.cos(math.radians(track.pitch[start]))

    def offset(j):
        return wrap(track.yaw[j] - track.yaw[start]) * cos_p, track.pitch[j] - track.pitch[start]

    j = end
    while j + 1 < len(track) and track.t[j + 1] - track.t[end] <= OVERSHOOT_TICKS and track.t[j + 1] - track.t[j] <= GAP_TICKS:
        j += 1
    fx, fy = offset(j)
    norm = math.hypot(fx, fy)
    if not norm:
        return False
    along = [(x * fx + y * fy) / norm for x, y in map(offset, range(start, j + 1))]
    return max(along) - along[-1] >= OVERSHOOT_DEG


def aim_error(track, i, other, k):
    """(deg the crosshair of track's sample i is off other's body at sample k, distance)."""
    ex, ey, ez = track.x[i], track.y[i], track.z[i] + EYE
    view = track.view(i)
    best, dist = 180.0, 0.0
    for h in BODY:
        dx, dy, dz = other.x[k] - ex, other.y[k] - ey, other.z[k] + h - ez
        d = math.sqrt(dx * dx + dy * dy + dz * dz)
        if d < 1e-6:
            continue
        err = angle(view, (dx / d, dy / d, dz / d))
        if err < best:
            best, dist = err, d
    return best, dist


def on_target_slack(dist):
    return math.degrees(math.atan2(HALF_WIDTH, dist)) + AIM_SLACK


def held_on(track, j, other):
    """True when the crosshair stays on other for HOLD_SAMPLES samples after sample j."""
    held, t = 0, track.t[j]
    j += 1
    while j < len(track) and held < HOLD_SAMPLES and track.t[j] - t <= HOLD_TICKS:
        k = other.at(track.t[j])
        if k is None:
            return False
        err, d = aim_error(track, j, other, k)
        if err > on_target_slack(d) + HOLD_SLACK:
            return False
        held += 1
        j += 1
    return held >= HOLD_SAMPLES


def acquisition(tracks, sid, track, flick):
    """(target SteamID64, ticks, updates) when this flick brought the crosshair onto a player who was
    10+ deg off when it started, and it stayed on them: ticks and angle updates from the last still
    moment before the flick to the first moment on target, the corrections after the flick included.
    One update means it landed in a single step."""
    if flick["turn"] < ACQ_MIN_TURN:
        return None
    s, e = flick["start"], flick["end"]
    t0 = track.t[s]
    best = None
    for other_sid, other in tracks.items():
        if other_sid == sid:
            continue
        k0, k1 = other.at(t0), other.at(track.t[e])
        if k0 is None or k1 is None or aim_error(track, s, other, k0)[0] < ACQ_FROM:
            continue
        err1, dist = aim_error(track, e, other, k1)
        if not DIST[0] <= dist <= DIST[1] or err1 > ACQ_FROM / 2:  # the flick didn't go to them
            continue
        j = s + 1
        while j < len(track) and track.t[j] - t0 <= ACQ_WINDOW and track.t[j] - track.t[j - 1] <= GAP_TICKS:
            k = other.at(track.t[j]) if j >= e else None
            if k is not None:
                err, d = aim_error(track, j, other, k)
                if err <= on_target_slack(d):
                    if held_on(track, j, other) and (best is None or track.t[j] - t0 < best[1]):
                        updates = sum(angle(track.view(i - 1), track.view(i)) > STILL for i in range(s + 1, j + 1))
                        best = (other_sid, track.t[j] - t0, updates)
                    break
            j += 1
    return best


def player_stats(tracks):
    """{SteamID64: {"flicks", "hard", "corrected", "all_flicks", "acq": [(target, ticks, updates)],
    "cadence", "samples"}}."""
    stats = {}
    for sid, track in tracks.items():
        time.sleep(0.001)
        views = [track.view(i) for i in range(len(track))]
        cad = cadence(track, views)
        found = flicks(track, views, cad)
        judged = [f for f in found if f["judged"]]
        acq = []
        for f in found:
            a = acquisition(tracks, sid, track, f)
            if a:
                acq.append(a)
        stats[sid] = {"flicks": len(judged), "hard": sum(f["hard"] for f in judged),
                      "corrected": sum(f["corrected"] for f in found), "all_flicks": len(found),
                      "acq": acq, "cadence": cad, "samples": len(track)}
    return stats


# --- running it -----------------------------------------------------------------------------------

def demo_tool():
    import demo_check
    return demo_check.DEMO_TOOL


IDLE_FLAGS = getattr(subprocess, "IDLE_PRIORITY_CLASS", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)


def stats_from_csv(csv_path):
    with open(csv_path, encoding="utf-8", errors="replace", newline="") as f:
        return player_stats(read_tracks(f))


def stats_in_child(csv_path, folder):
    """The stats worked out by a separate Python at idle priority, so the scanner's own Python
    (its window) doesn't share the work. None when that can't run (then it's done here)."""
    if not os.path.basename(sys.executable or "").lower().startswith("python"):
        return None
    out = os.path.join(folder, "stats.json")
    try:
        done = subprocess.run([sys.executable, "-I", os.path.abspath(__file__), csv_path, out], capture_output=True,
                              timeout=600, creationflags=IDLE_FLAGS)
        if done.returncode != 0:
            return None
        with open(out, encoding="utf-8") as f:
            return stats_from_json(json.load(f))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def stats_to_json(stats):
    return {str(sid): v for sid, v in stats.items()}


def stats_from_json(data):
    return {int(sid): dict(v, acq=[tuple(a) for a in v["acq"]]) for sid, v in data.items()}


def run_angles(path, tool=None):
    """Runs demo-analysis's viewangles_to_csv on one demo at idle priority in a temporary folder
    and returns the per-player stats; the CSV is deleted at once."""
    tool = tool or demo_tool()
    folder = tempfile.mkdtemp(prefix="tf2scanner-aim-")
    try:
        os.makedirs(os.path.join(folder, "output"))
        done = subprocess.run([tool, "-i", os.path.abspath(path), "-q", "-a", "viewangles_to_csv"], cwd=folder,
                              capture_output=True, timeout=300, creationflags=IDLE_FLAGS)
        out = os.path.join(folder, "output", "viewangles_to_csv.csv")
        if done.returncode != 0 or not os.path.isfile(out):
            raise RuntimeError((done.stderr.decode("utf-8", "replace").strip().splitlines() or ["failed"])[-1])
        stats = stats_in_child(out, folder)
        return stats if stats is not None else stats_from_csv(out)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def stamp_of(path):
    try:
        return os.path.getsize(path), os.path.getmtime(path)
    except OSError:
        return None


def analyse(path, runner=None):
    """Analyses one demo now (in the calling thread) unless it's unchanged since its last analysis.
    Used for a finished demo, before it may be deleted. Never raises."""
    name = os.path.basename(path)
    with _lock:
        stamp = stamp_of(path)
        if stamp is None:
            return
        with _store_lock:
            if RESULTS.get(name, {}).get("stamp") == stamp:
                return
        try:
            stats, error = (runner or run_angles)(path), None
        except Exception as e:  # noqa: BLE001 - it runs inside demo_worker, which must keep going
            stats, error = None, str(e)
        with _store_lock:
            old = RESULTS.get(name, {})
            RESULTS[name] = {"stamp": stamp, "stats": stats if stats is not None else old.get("stats"),
                             "at": time.time(), "error": error}


def request(path, runner=None):
    """Asks the background thread to analyse a demo still being recorded: at most every
    RECHECK_SECONDS per demo. Returns at once."""
    global _thread
    name = os.path.basename(path)
    with _store_lock:
        last = RESULTS.get(name, {}).get("at", 0)
        if time.time() - last < RECHECK_SECONDS:
            return
        _pending[name] = (path, runner)
        if _thread is None or not _thread.is_alive():
            _thread = threading.Thread(target=_worker, daemon=True, name="demo-clues")
            _thread.start()
    _wake.set()


def _worker():
    while True:
        _wake.wait(60)
        _wake.clear()
        while True:
            with _store_lock:
                if not _pending:
                    break
                name = next(iter(_pending))
                path, runner = _pending.pop(name)
            analyse(path, runner)


def latest_stats():
    """(demo name, stats) of the newest demo analysed this session (TF2's names sort by date)."""
    with _store_lock:
        done = [(name, r["stats"]) for name, r in RESULTS.items() if r.get("stats") is not None]
    return max(done, default=(None, None))


def forget():
    with _store_lock:
        RESULTS.clear()
        _pending.clear()


# --- statistics -------------------------------------------------------------------------------------

def binomial_tail(n, k, p):
    """P(X >= k) for X ~ Binomial(n, p), in log space so large n doesn't overflow."""
    if k <= 0:
        return 1.0
    if p <= 0:
        return 0.0
    if p >= 1:
        return 1.0
    lp, lq = math.log(p), math.log1p(-p)
    terms = [math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * lp + (n - i) * lq
             for i in range(k, n + 1)]
    top = max(terms)
    return min(1.0, math.exp(top) * sum(math.exp(t - top) for t in terms))


def median(values):
    s = sorted(values)
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def ramp(x, low, high):
    """0 at low, 1 at high, smooth (smoothstep) in between."""
    u = max(0.0, min(1.0, (x - low) / (high - low)))
    return u * u * (3 - 2 * u)


def lobby_test(k, n, others):
    """Compares k of n with the other players' (k, n): (lr progress 0..1, rate, lobby median,
    robust z, tail probability). Progress needs both a rare binomial tail at the lobby's rate
    (2 -> 6 in -log10) and a robust z (3 -> 6), so one odd number can't do it alone."""
    rates = [ok / on for ok, on in others]
    med = median(rates)
    mad = 1.4826 * median([abs(r - med) for r in rates])
    pooled = sum(ok for ok, _ in others) / sum(on for _, on in others)
    p0 = min(0.95, max(med, pooled, 0.01))
    spread = max(mad, math.sqrt(p0 * (1 - p0) / n), 0.02)
    rate = k / n
    z = (rate - med) / spread
    tail = binomial_tail(n, k, p0)
    progress = min(ramp(-math.log10(max(tail, 1e-300)), 2.0, 6.0), ramp(z, 3.0, 6.0))
    return progress, rate, med, z, tail


def team_of(app, sid):
    try:
        return app.team_color(SimpleNamespace(sid=sid)) or ""
    except Exception:
        return ""


def lag_note(player):
    ping = getattr(player, "ping", 0) or 0
    return f" (ping {ping} ms: lag can do this too)" if ping >= HIGH_PING else ""


def lag_scaled(lr, player):
    ping = getattr(player, "ping", 0) or 0
    return 1 + (lr - 1) * HIGH_PING_SHARE if ping >= HIGH_PING and lr > 1 else lr


def judgeable(v):
    """True when a player's angle updates come often enough in this demo to judge their flicks."""
    return v.get("cadence") is not None and v["cadence"] <= MAX_CADENCE


def aim_clues(app, player, stats=None):
    """The two demo aim clues for one player, from the newest demo analysed (or stats given)."""
    if stats is None:
        stats = latest_stats()[1]
    me = getattr(app, "me", None)
    sid = player.sid
    if not stats or sid == me or sid not in stats or not judgeable(stats[sid]):
        return []
    mine = stats[sid]
    # The recorder (you) is left out: the demo has your own angles at full precision.
    others = {s: v for s, v in stats.items() if s not in (sid, me) and judgeable(v)}

    lock = None
    lobby = [(v["hard"], v["flicks"]) for v in others.values() if v["flicks"] >= MIN_LOBBY_FLICKS]
    if mine["flicks"] >= MIN_FLICKS and len(lobby) >= MIN_LOBBY_PLAYERS:
        progress, rate, med, z, tail = lobby_test(mine["hard"], mine["flicks"], lobby)
        lr = lag_scaled(1 + (LOCK_LR_MAX - 1) * progress, player)
        if lr > 1.01:
            lock = Clue("demo_aim_lock", lr,
                        f"aim stopped dead after {mine['hard']}/{mine['flicks']} fast flicks ({rate:.0%}; "
                        f"others here {med:.0%}){lag_note(player)}",
                        "Human flicks slow down over several updates and often overshoot; an aimbot jumps onto "
                        "the spot and stops at once. Compared with everyone else in this demo.", source="demo")
        elif mine["flicks"] >= HUMAN_MIN_FLICKS and rate <= med:
            lock = Clue("demo_aim_lock", HUMAN_LR,
                        f"aim slowed down normally after fast flicks (only {mine['hard']}/{mine['flicks']} "
                        f"stopped dead; others here {med:.0%})",
                        "Lots of fast flicks that slow down like everyone else's: a small hint of human aim "
                        "(a smoothed aimbot can look like this too).", source="demo")

    def enemy_of(s, target):  # teammates are left out when both teams are known
        a, b = team_of(app, s), team_of(app, target)
        return not (a and b and a == b)

    def counts(v, s):
        updates = [u for target, _, u in v["acq"] if enemy_of(s, target)]
        return sum(u <= FAST_UPDATES for u in updates), len(updates)

    fast = None
    k, n = counts(mine, sid)
    lobby = [c for c in (counts(v, s) for s, v in others.items()) if c[1] >= MIN_LOBBY_ACQ]
    if n >= MIN_ACQ and len(lobby) >= MIN_LOBBY_PLAYERS:
        progress, rate, med, z, tail = lobby_test(k, n, lobby)
        lr = lag_scaled(1 + (FAST_LR_MAX - 1) * progress, player)
        if lr > 1.01:
            fast = Clue("demo_fast_acquire", lr,
                        f"{k}/{n} flicks onto a player landed in a single step ({rate:.0%}; "
                        f"others here {med:.0%}){lag_note(player)}",
                        "Flick-to-target time, not true reaction time (the demo has no line of sight or shots): "
                        f"a human's {ACQ_MIN_TURN:.0f}+ degree flick onto a body usually takes several angle "
                        "updates and a correction; an aimbot's takes one.", source="demo")

    if lock and fast:
        if lock.lr < 1:
            lock = None  # a snap clue is up: no "human aim" bonus
        else:  # related (a snap onto a target is often a hard stop): the smaller one counts only partly
            small = min(lock, fast, key=lambda c: c.lr)
            small.lr = small.lr ** OVERLAP_POWER
    return [c for c in (lock, fast) if c]


register(aim_clues)


if __name__ == "__main__":  # the child of stats_in_child: demo_clues.py <csv> <stats.json>
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        json.dump(stats_to_json(stats_from_csv(sys.argv[1])), f)
