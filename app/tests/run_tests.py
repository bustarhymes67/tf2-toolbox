"""Runs the tests faster: each test file in its own process, several at once.

    python run_tests.py            every test file, in parallel (before a push)
    python run_tests.py --quick    only the fast core tests (logic, no windows): seconds
    python run_tests.py --times    also lists how long each file took (slowest first)
    python run_tests.py test_x     only these files

A file counts as slow when it plays a made-up match with the toolbox's windows (helpers.Game);
--quick leaves those out. Exit code 1 when anything failed."""
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
WORKERS = max(2, min(8, (os.cpu_count() or 4) - 1))


def test_files():
    return sorted(n[:-3] for n in os.listdir(HERE) if n.startswith("test_") and n.endswith(".py"))


def slow(name):
    """Plays a match with the real windows (helpers.Game): the part that takes the time."""
    with open(os.path.join(HERE, name + ".py"), encoding="utf-8") as f:
        text = f.read()
    return "Game(" in text or "web_preview" in text


def run(name):
    start = time.time()
    # The app folder on the path, as "discover" gave every file (some files rely on another one adding it).
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(filter(None, [os.path.dirname(HERE), os.environ.get("PYTHONPATH")])))
    p = subprocess.run([sys.executable, "-m", "unittest", name], cwd=HERE, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    return name, p.returncode, p.stderr, time.time() - start


def main():
    args = sys.argv[1:]
    quick, times = "--quick" in args, "--times" in args
    names = [a for a in args if not a.startswith("--")] or test_files()
    if quick:
        names = [n for n in names if not slow(n)]
    start = time.time()
    failed, took = [], []
    with ThreadPoolExecutor(WORKERS) as pool:
        for i, (name, code, err, secs) in enumerate(pool.map(run, names), 1):
            took.append((secs, name))
            last = err.strip().splitlines()[-1] if err.strip() else ""
            print(f"[{i * 100 // len(names):3d}%] {'ok  ' if code == 0 else 'FAIL'} {name} ({secs:.0f}s) {last}", flush=True)
            if code:
                failed.append((name, err))
    for name, err in failed:
        print(f"\n===== {name} =====\n{err[-4000:]}")
    if times:
        print("\nSlowest files:")
        for secs, name in sorted(took, reverse=True)[:15]:
            print(f"  {secs:6.1f}s  {name}")
    print(f"\n{len(names) - len(failed)}/{len(names)} files passed in {time.time() - start:.0f}s"
          f" ({'quick' if quick else 'all'}, {WORKERS} at once)")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
