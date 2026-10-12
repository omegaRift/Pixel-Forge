"""Run Pixel Forge's test suites.

    .venv\\Scripts\\python tests\\run_all.py            every suite, then the layout check
    .venv\\Scripts\\python tests\\run_all.py gradient    only suites with "gradient" in their name

Each suite is a plain script of asserts, run in its own process. The window
suites use an invisible window (see harness.py): nothing appears on screen
and the mouse and focus are left alone. A suite that stalls - say on a
dialog box nobody stubbed - is ended after TIMEOUT seconds with every
thread's stack printed, so it can't hang the run.

Two suites need the built launcher ("Pixel Forge.exe", from
build-launcher.bat) and are skipped with a note without it; the AI checks
are skipped when the AI extras aren't installed.
"""

import subprocess
import sys
import time
from pathlib import Path

TESTS = Path(__file__).resolve().parent
TIMEOUT = 240  # seconds per suite

WATCHDOG = (
    "import faulthandler, runpy, sys\n"
    "seconds, script = int(sys.argv[1]), sys.argv[2]\n"
    "faulthandler.dump_traceback_later(seconds, exit=True)\n"
    "sys.argv = [script]\n"
    "runpy.run_path(script, run_name='__main__')\n"
)


def run(script: Path):
    started = time.time()
    done = subprocess.run([sys.executable, "-c", WATCHDOG, str(TIMEOUT), str(script)], cwd=TESTS,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (done.stdout or "") + (done.stderr or "")
    said = [line for line in (done.stdout or "").splitlines() if line.strip()]  # its own last word
    last = said[-1] if said else ""
    if done.returncode == 0 and last.startswith("SKIPPED"):  # (a suite that skipped only one part still passed)
        verdict = "skip"
    elif done.returncode == 0:
        verdict = "ok"
    else:
        verdict = "FAIL"
    return verdict, time.time() - started, last, out


def main():
    wanted = sys.argv[1:]
    suites = sorted(TESTS.glob("test_*.py")) + [TESTS / "layout_check.py"]
    if wanted:
        suites = [s for s in suites if any(w in s.stem for w in wanted)]
    failed, skipped = [], 0
    for script in suites:
        verdict, seconds, last, out = run(script)
        print(f"{verdict:4}  {script.stem:26} {seconds:5.0f}s  {last[:90]}", flush=True)
        skipped += verdict == "skip"
        if verdict == "FAIL":
            failed.append(script.stem)
            print("\n".join("      " + line for line in out.splitlines()[-25:]), flush=True)
    passed = len(suites) - len(failed) - skipped
    print(f"\n{passed} of {len(suites)} passed" + (f", {skipped} skipped" if skipped else "") +
          (f"; FAILED: {', '.join(failed)}" if failed else ""))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
