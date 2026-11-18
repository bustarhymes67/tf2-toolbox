"""Demo aim clues (demo_clues.py) on made-up angle data: no real demo is in the repo."""
import csv
import importlib.util
import io
import math
import os
import sys
import tempfile
import time
import types
import unittest
from dataclasses import dataclass
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import demo_check
import demo_clues as dc

BASE = dc.STEAM64_BASE


def csv_text(rows):
    """viewangles_to_csv's format: rows (tick, account, x, y, z, yaw, pitch)."""
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow("tick,name,steam_id,origin_x,origin_y,origin_z,viewangle,pitchangle,va_delta,pa_delta".split(","))
    for tick, account, x, y, z, yaw, pitch in rows:
        w.writerow([tick, f'"p{account}"', f"[U:1:{account}]", x, y, z, yaw, pitch, 0, 0])
    return out.getvalue()


def track(yaws, start=0, pos=(0.0, 0.0, 0.0), pitch=0.0):
    """A Track with one sample per tick."""
    t = dc.Track()
    for i, yaw in enumerate(yaws):
        t.add(start + i, *pos, yaw % 360, pitch)
    return t


def still(yaw, n):
    return [yaw] * n


def human_flick(yaw):
    """Speeds up and slows down over six ticks: 3, 8, 12, 8, 4, 1.5 degrees."""
    out = []
    for step in (3, 8, 12, 8, 4, 1.5):
        yaw += step
        out.append(yaw)
    return out


def tracking(yaw, n=10, step=1.5):
    return [yaw + step * (i + 1) for i in range(n)]


def player(flick, cycles=40):
    """Per cycle: following a target slowly, still, a 30+ deg flick, still."""
    yaws, yaw = [], 0.0
    for _ in range(cycles):
        part = tracking(yaw) + still(yaw + 15, 10)
        yaw = part[-1]
        part += flick(yaw)
        yaw = part[-1]
        part += still(yaw, 10)
        yaws += part
    return yaws


def bot_flick(yaw):
    return [yaw + 36.5]  # the whole turn in one tick, then still


class ReadCsvTest(unittest.TestCase):
    def test_rows_in_one_tick_are_reversed_deduplicated_and_spread(self):
        rows = [(10, 5, 0, 0, 0, 10.0, 0.0),
                (12, 5, 2, 0, 0, 30.0, 0.0),  # newest first within tick 12 (how the tool writes them)
                (12, 5, 1, 0, 0, 20.0, 0.0),
                (12, 5, 1, 0, 0, 20.0, 0.0),  # an exact repeat
                (13, 5, 3, 0, 0, 40.0, 0.0),
                (13, 7, 9, 9, 9, 1.0, 2.0)]
        tracks = dc.read_tracks(io.StringIO(csv_text(rows)))
        t = tracks[BASE + 5]
        self.assertEqual(list(t.yaw), [10.0, 20.0, 30.0, 40.0])
        self.assertEqual(list(t.t), [10.0, 11.0, 12.0, 13.0])
        self.assertEqual(list(tracks[BASE + 7].pitch), [2.0])

    def test_bad_rows_are_skipped(self):
        text = csv_text([(1, 5, 0, 0, 0, 1.0, 0.0)]) + "2,x,BOT,0,0,0,1,1,0,0\n3,x,[U:1:5],0,0,0,nan,1,0,0\nbroken\n"
        self.assertEqual(len(dc.read_tracks(io.StringIO(text))[BASE + 5]), 1)

    def test_names_with_commas_and_quotes(self):
        text = ("tick,name,steam_id,origin_x,origin_y,origin_z,viewangle,pitchangle,va_delta,pa_delta\n"
                '4,"a, ""b""",[U:1:9],1,2,3,90,5,NaN,NaN\n')
        t = dc.read_tracks(io.StringIO(text))[BASE + 9]
        self.assertEqual((t.x[0], t.yaw[0], t.pitch[0]), (1.0, 90.0, 5.0))


class FlickTest(unittest.TestCase):
    def test_a_human_flick_slows_down(self):
        found = dc.flicks(track(still(0, 10) + human_flick(0) + still(36.5, 10)))
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0]["judged"])
        self.assertFalse(found[0]["hard"])
        self.assertAlmostEqual(found[0]["turn"], 36.5, places=1)

    def test_an_aimbot_snap_stops_dead(self):
        found = dc.flicks(track(still(0, 10) + [36.5] + still(36.5, 10)))
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0]["hard"])

    def test_a_snap_and_back_is_not_a_flick(self):  # that's Nocrex's angle_repeat, not counted twice
        self.assertEqual(dc.flicks(track(still(0, 10) + [30, 0.2] + still(0.2, 10))), [])

    def test_slow_turns_and_tiny_jitter_are_not_flicks(self):
        self.assertEqual(dc.flicks(track(tracking(0, 30, 2.0) + still(60, 5))), [])
        self.assertEqual(dc.flicks(track([0, 0.35, 0, 0.35, 0] * 10)), [])  # the demo's angle steps

    def test_not_judged_without_time_after_it(self):
        found = dc.flicks(track(still(0, 10) + [36.5, 36.5]))
        self.assertFalse(found[0]["judged"])
        self.assertFalse(found[0]["hard"])

    def test_updates_every_other_tick_are_one_movement(self):
        # The same human flick, but the angle only changes every 2nd tick (a usercmd rate of 33/s).
        yaws, yaw = still(0, 10), 0
        for step in (4, 10, 16, 10, 5, 2):
            yaw += step
            yaws += [yaw, yaw]
        found = dc.flicks(track(yaws + still(yaw, 10)))
        self.assertEqual(len(found), 1)
        self.assertFalse(found[0]["hard"])

    def test_overshoot_is_noticed(self):
        found = dc.flicks(track(still(0, 10) + human_flick(0) + [36.5, 35.0, 34.5] + still(34.5, 10)))
        self.assertTrue(found[0]["corrected"])

    def test_cadence(self):
        every_tick = track(player(human_flick, cycles=10))
        self.assertEqual(dc.cadence(every_tick), 1.0)
        slow = dc.Track()
        for i in range(400):
            slow.add(i, 0, 0, 0, (i // 6) * 3.0 % 360, 0)  # changes every 6 ticks
        self.assertEqual(dc.cadence(slow), 6.0)
        self.assertIsNone(dc.cadence(track(still(0, 100))))


class AcquisitionTest(unittest.TestCase):
    def setUp(self):
        # The target stands 1000 units away at yaw 40 (same height); the shooter starts at yaw 0.
        self.target = track(still(0, 60), pos=(1000 * math.cos(math.radians(40)), 1000 * math.sin(math.radians(40)), 0))

    def acquire(self, yaws):
        shooter = track(yaws)
        tracks = {1: shooter, 2: self.target}
        return [a for f in dc.flicks(shooter) if (a := dc.acquisition(tracks, 1, shooter, f))]

    def test_a_snap_onto_a_target_lands_in_one_update(self):
        self.assertEqual(self.acquire(still(0, 10) + still(40, 20)), [(2, 1.0, 1)])

    def test_a_human_flick_takes_several_updates(self):
        yaws = still(0, 10) + [3, 11, 23, 31, 35, 37.5, 38.5, 39.5] + still(39.5, 20)
        found = self.acquire(yaws)
        self.assertEqual(len(found), 1)
        self.assertGreater(found[0][2], 3)

    def test_passing_over_a_target_is_not_landing_on_it(self):
        self.assertEqual(self.acquire(still(0, 10) + [40] + still(80, 20)), [])

    def test_a_target_already_on_the_crosshair_doesnt_count(self):
        self.target = track(still(0, 60), pos=(1000, 0, 0))  # at yaw 0: no flick needed
        self.assertEqual(self.acquire(still(0, 10) + [5] + still(0, 20)), [])


def stats(hard, flicks, acq=(), cadence=1.0):
    return {"flicks": flicks, "hard": hard, "corrected": 0, "all_flicks": flicks, "acq": list(acq),
            "cadence": cadence, "samples": 10000}


def snaps(snapped, total, target=BASE + 99):
    return [(target, 1.0 if i < snapped else 8.0, 1 if i < snapped else 5) for i in range(total)]


class FakeApp:
    def __init__(self, me=BASE + 1, teams=None):
        self.me, self.teams = me, teams or {}

    def team_color(self, p):
        return self.teams.get(p.sid, "")


def lobby():
    return {BASE + 10 + i: stats(8 + i, 100, snaps(1, 20)) for i in range(6)}


class ClueTest(unittest.TestCase):
    def clues(self, data, sid=BASE + 50, ping=50, app=None):
        return {c.key: c for c in dc.aim_clues(app or FakeApp(), NS(sid=sid, ping=ping), data)}

    def test_many_hard_stops_raise_the_odds(self):
        c = self.clues(lobby() | {BASE + 50: stats(70, 100)})["demo_aim_lock"]
        self.assertGreater(c.lr, 3.5)
        self.assertLessEqual(c.lr, dc.LOCK_LR_MAX)
        self.assertEqual(c.source, "demo")
        self.assertIn("70/100", c.text)
        self.assertFalse(c.proof)

    def test_lr_grows_smoothly(self):
        lrs = [self.clues(lobby() | {BASE + 50: stats(k, 100)}).get("demo_aim_lock", NS(lr=1.0)).lr
               for k in range(10, 80, 5)]
        self.assertEqual(lrs, sorted(lrs))
        self.assertTrue(any(1 < lr < dc.LOCK_LR_MAX for lr in lrs))  # in between, not a jump

    def test_too_few_flicks_or_players_say_nothing(self):
        self.assertEqual(self.clues(lobby() | {BASE + 50: stats(20, 25)}), {})
        small = {BASE + 10 + i: stats(8, 100) for i in range(3)} | {BASE + 50: stats(70, 100)}
        self.assertEqual(self.clues(small), {})

    def test_a_normal_player_gets_a_small_human_hint(self):
        c = self.clues(lobby() | {BASE + 50: stats(5, 200)})["demo_aim_lock"]
        self.assertEqual(c.lr, dc.HUMAN_LR)
        self.assertEqual(self.clues(lobby() | {BASE + 50: stats(5, 100)}), {})  # not enough flicks for that

    def test_high_ping_halves_it(self):
        data = lobby() | {BASE + 50: stats(70, 100)}
        low, high = self.clues(data)["demo_aim_lock"], self.clues(data, ping=200)["demo_aim_lock"]
        self.assertAlmostEqual(high.lr - 1, (low.lr - 1) * dc.HIGH_PING_SHARE)
        self.assertIn("ping 200 ms", high.text)

    def test_too_coarse_angles_are_not_judged(self):
        self.assertEqual(self.clues(lobby() | {BASE + 50: stats(70, 100, cadence=6.0)}), {})
        self.assertEqual(self.clues(lobby() | {BASE + 50: stats(70, 100, cadence=None)}), {})
        # nor are such players part of the lobby
        coarse = {BASE + 10 + i: stats(8, 100, cadence=7.0) for i in range(6)} | {BASE + 50: stats(70, 100)}
        self.assertEqual(self.clues(coarse), {})

    def test_you_are_never_judged_nor_the_baseline(self):
        data = lobby() | {BASE + 1: stats(70, 100)}
        self.assertEqual(self.clues(data, sid=BASE + 1), {})
        # the recorder's precise angles stay out of the others' baseline
        data = {BASE + 1: stats(0, 100)} | {BASE + 10 + i: stats(8, 100) for i in range(3)} | {BASE + 50: stats(70, 100)}
        self.assertEqual(self.clues(data), {})

    def test_snaps_onto_targets(self):
        c = self.clues(lobby() | {BASE + 50: stats(10, 100, snaps(15, 20))})["demo_fast_acquire"]
        self.assertGreater(c.lr, 4)
        self.assertIn("15/20", c.text)
        self.assertIn("not true reaction time", c.why)
        self.assertNotIn("demo_fast_acquire", self.clues(lobby() | {BASE + 50: stats(10, 100, snaps(2, 20))}))
        self.assertNotIn("demo_fast_acquire", self.clues(lobby() | {BASE + 50: stats(10, 100, snaps(8, 8))}))

    def test_teammates_dont_count_when_teams_are_known(self):
        mate = BASE + 98
        data = lobby() | {BASE + 50: stats(10, 100, snaps(15, 20, target=mate))}
        self.assertIn("demo_fast_acquire", self.clues(data))
        app = FakeApp(teams={BASE + 50: "RED", mate: "RED"})
        self.assertNotIn("demo_fast_acquire", self.clues(data, app=app))

    def test_both_up_are_not_counted_twice(self):
        c = self.clues(lobby() | {BASE + 50: stats(70, 100, snaps(15, 20))})
        lock, fast = c["demo_aim_lock"], c["demo_fast_acquire"]
        self.assertAlmostEqual(min(lock.lr, fast.lr), dc.LOCK_LR_MAX ** dc.OVERLAP_POWER, places=3)
        self.assertGreater(max(lock.lr, fast.lr), 4)

    def test_no_human_hint_next_to_a_snap_clue(self):
        c = self.clues(lobby() | {BASE + 50: stats(5, 200, snaps(15, 20))})
        self.assertNotIn("demo_aim_lock", c)
        self.assertIn("demo_fast_acquire", c)

    def test_unknown_player_or_no_demo(self):
        self.assertEqual(self.clues(lobby(), sid=BASE + 77), {})
        self.assertEqual(self.clues({}), {})


class StatsTest(unittest.TestCase):
    def test_binomial_tail(self):
        self.assertAlmostEqual(dc.binomial_tail(10, 0, 0.3), 1.0)
        self.assertAlmostEqual(dc.binomial_tail(2, 2, 0.5), 0.25)
        self.assertAlmostEqual(dc.binomial_tail(3, 2, 0.5), 0.5)
        self.assertLess(dc.binomial_tail(3000, 2000, 0.2), 1e-100)  # no overflow on long demos

    def test_end_to_end_from_csv(self):
        """Six humans and one aimbot in a made-up demo: only the aimbot gets the hard-stop clue."""
        rows = []
        for account in range(10, 16):
            rows += [(i, account, 0, 0, 0, y % 360, 0.0) for i, y in enumerate(player(human_flick))]
        rows += [(i, 50, 0, 0, 0, y % 360, 0.0) for i, y in enumerate(player(bot_flick))]
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "angles.csv")
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(csv_text(rows))
            data = dc.stats_from_csv(path)
            self.assertEqual(dc.stats_in_child(path, folder), data)  # the idle-priority child gives the same
        self.assertEqual(data[BASE + 50]["hard"], data[BASE + 50]["flicks"])
        self.assertEqual(data[BASE + 10]["hard"], 0)
        for account in (10, 50):
            got = self.clues_for(data, BASE + account)
            self.assertEqual(bool(got), account == 50, got)

    def clues_for(self, data, sid):
        return [c for c in dc.aim_clues(FakeApp(), NS(sid=sid, ping=40), data) if c.lr > 1]


class RunningTest(unittest.TestCase):
    def setUp(self):
        dc.forget()
        self.folder = tempfile.TemporaryDirectory()
        self.dem = os.path.join(self.folder.name, "2026-11-06_00-30-00.dem")
        with open(self.dem, "wb") as f:
            f.write(b"demo")

    def tearDown(self):
        dc.forget()
        self.folder.cleanup()

    def test_analysed_once_per_version_of_the_demo(self):
        runs = []
        runner = lambda path: runs.append(path) or {BASE + 5: stats(1, 10)}
        dc.analyse(self.dem, runner)
        dc.analyse(self.dem, runner)
        self.assertEqual(len(runs), 1)
        with open(self.dem, "ab") as f:
            f.write(b"more")
        dc.analyse(self.dem, runner)
        self.assertEqual(len(runs), 2)
        self.assertEqual(dc.latest_stats(), ("2026-11-06_00-30-00.dem", {BASE + 5: stats(1, 10)}))

    def test_a_failure_is_kept_quiet_and_keeps_the_last_stats(self):
        dc.analyse(self.dem, lambda path: {BASE + 5: stats(1, 10)})
        with open(self.dem, "ab") as f:
            f.write(b"more")

        def broken(path):
            raise RuntimeError("tool crashed")
        dc.analyse(self.dem, broken)  # doesn't raise
        self.assertEqual(dc.RESULTS["2026-11-06_00-30-00.dem"]["error"], "tool crashed")
        self.assertEqual(dc.latest_stats()[1], {BASE + 5: stats(1, 10)})
        dc.analyse(os.path.join(self.folder.name, "gone.dem"), broken)  # a missing demo: nothing happens

    def test_newest_demo_is_the_current_match(self):
        dc.analyse(self.dem, lambda path: {BASE + 5: stats(1, 10)})
        newer = os.path.join(self.folder.name, "2026-11-06_01-00-00.dem")
        with open(newer, "wb") as f:
            f.write(b"demo")
        dc.analyse(newer, lambda path: {BASE + 6: stats(2, 10)})
        self.assertEqual(dc.latest_stats()[0], "2026-11-06_01-00-00.dem")

    def test_request_runs_in_the_background_at_most_every_few_minutes(self):
        runs = []

        def slow(path):
            time.sleep(0.2)
            runs.append(path)
            return {}
        started = time.time()
        dc.request(self.dem, slow)
        self.assertLess(time.time() - started, 0.1)  # returned at once
        for _ in range(50):
            if runs:
                break
            time.sleep(0.05)
        self.assertEqual(runs, [self.dem])
        with open(self.dem, "ab") as f:
            f.write(b"more")
        dc.request(self.dem, slow)  # analysed a moment ago: not again yet
        time.sleep(0.4)
        self.assertEqual(len(runs), 1)

    def test_demo_worker_hook(self):
        with mock.patch.object(dc, "analyse") as analyse, mock.patch.object(dc, "request") as request:
            demo_check.aim_check(self.dem, finished=True)
            demo_check.aim_check(self.dem, finished=False)
        analyse.assert_called_once_with(self.dem)
        request.assert_called_once_with(self.dem)

    def test_runs_the_tool_with_viewangles_to_csv_at_idle_priority(self):
        seen = {}

        def fake_run(args, cwd=None, capture_output=True, timeout=0, creationflags=0):
            if args[0] != "tool.exe":
                return NS(returncode=1, stderr=b"")  # the child Python: not here, so it's done in-process
            seen.update(args=args, cwd=cwd, flags=creationflags)
            if args[0] == "tool.exe":
                with open(os.path.join(cwd, "output", "viewangles_to_csv.csv"), "w", encoding="utf-8") as f:
                    f.write(csv_text([(1, 5, 0, 0, 0, 1.0, 0.0)]))
            return NS(returncode=0 if args[0] == "tool.exe" else 1, stderr=b"")
        with mock.patch.object(dc.subprocess, "run", fake_run):
            result = dc.run_angles(self.dem, tool="tool.exe")
        self.assertIn(BASE + 5, result)
        self.assertEqual(seen["args"][1:], ["-i", os.path.abspath(self.dem), "-q", "-a", "viewangles_to_csv"])
        self.assertEqual(seen["flags"], dc.IDLE_FLAGS)
        self.assertFalse(os.path.exists(seen["cwd"]))  # the CSV and its folder are gone

    def test_tool_failure_raises_for_analyse(self):
        with mock.patch.object(dc.subprocess, "run", lambda *a, **k: NS(returncode=101, stderr=b"panicked: bad demo")):
            with self.assertRaisesRegex(RuntimeError, "bad demo"):
                dc.run_angles(self.dem, tool="tool.exe")


class RegisterTest(unittest.TestCase):
    def test_registers_with_cheat_score(self):
        """With a stand-in cheat_score (the real one is another task's): aim_clues is registered."""
        registered = []

        @dataclass
        class Clue:
            key: str
            lr: float
            text: str
            why: str
            proof: bool = False
            source: str = ""
        stub = types.ModuleType("cheat_score")
        stub.Clue, stub.register = Clue, registered.append
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "demo_clues.py")
        with mock.patch.dict(sys.modules, {"cheat_score": stub}):
            spec = importlib.util.spec_from_file_location("demo_clues_copy", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        self.assertEqual([f.__name__ for f in registered], ["aim_clues"])
        data = lobby() | {BASE + 50: stats(70, 100)}
        self.assertIsInstance(module.aim_clues(FakeApp(), NS(sid=BASE + 50, ping=0), data)[0], Clue)


if __name__ == "__main__":
    unittest.main()
