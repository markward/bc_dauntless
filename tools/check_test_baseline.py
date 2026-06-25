"""Run the full test suite (pytest + C++ ctest) and diff the failures against a
checked-in baseline of known-acceptable failures (tests/known_failures.txt).

This is the gate that stops orphaned tests from slipping through mislabeled as
"pre-existing". The standard runner (scripts/run_tests.sh) is pytest-only, so
C++ regressions were invisible; and the known-failing set lived in prose, which
drifted. This makes both suites part of one run and the ledger machine-checked.

A failure is acceptable ONLY if it is listed in the baseline. Anything else is
a regression introduced by the current tree.

Exit codes:
  0  no NEW failures (every failure was in the baseline)
  1  NEW failure(s) not in the baseline  -> regression(s) to fix
  2  harness/setup error (could not run a suite)

Usage:
  uv run python tools/check_test_baseline.py            # build C++, run both
  uv run python tools/check_test_baseline.py --no-build # skip cmake build
  uv run python tools/check_test_baseline.py --pytest-only
  uv run python tools/check_test_baseline.py --ctest-only

Note: where BC game/ assets are absent, asset-dependent tests SKIP (not fail),
so this gate is safe to run anywhere; it just verifies fewer tests.
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(ROOT, "tests", "known_failures.txt")
BUILD_DIR = os.path.join(ROOT, "build")
CEILING_MB = os.environ.get("CEILING_MB", "4000")

_PYTEST_FAILED = re.compile(r"^FAILED (\S+)")
# ctest summary block: "\t188 - FrameTest.Name (Failed)" / "(Subprocess aborted)" / "(Timeout)"
_CTEST_FAILED = re.compile(r"^\s*\d+ - (\S+) \((?:Failed|Subprocess aborted|Timeout|Child aborted)\)")


def _load_baseline():
    """Return the set of baselined ids ('pytest:<nodeid>' / 'ctest:<name>')."""
    known = set()
    if not os.path.isfile(BASELINE):
        return known
    with open(BASELINE, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            known.add(line)
    return known


def _run(cmd, **kw):
    print("  $ " + " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, **kw)


def run_pytest():
    """Run the full pytest suite under the RSS watchdog; return set of failed ids."""
    print("== pytest ==", flush=True)
    cmd = [
        "uv", "run", "python", "tools/pytest_rss_watchdog.py", CEILING_MB, "--",
        "uv", "run", "pytest", "tests", "-q", "-rf", "--tb=no", "-p", "no:cacheprovider",
    ]
    proc = _run(cmd)
    out = proc.stdout + proc.stderr
    failed = {"pytest:" + m.group(1) for m in map(_PYTEST_FAILED.match, out.splitlines()) if m}
    # rc 99 == watchdog OOM kill; surface it as a harness error, not a clean pass.
    if proc.returncode == 99:
        print("  !! pytest watchdog killed the run (RSS ceiling) — incomplete", flush=True)
        return failed, True
    # A non-zero rc with no parsed failures means something broke (collection error).
    if proc.returncode not in (0, 1) and not failed:
        sys.stdout.write(out[-2000:])
        print("  !! pytest exited %d with no parseable failures" % proc.returncode, flush=True)
        return failed, True
    print("  pytest: %d failure(s)" % len(failed), flush=True)
    return failed, False


def run_ctest():
    """Run the C++ ctest suite; return set of failed ids. (Build separately.)"""
    print("== ctest ==", flush=True)
    if not os.path.isfile(os.path.join(BUILD_DIR, "CTestTestfile.cmake")):
        print("  !! no ctest configuration in build/ — run cmake first", flush=True)
        return set(), True
    proc = _run(["ctest", "--test-dir", "build", "--output-on-failure"])
    out = proc.stdout + proc.stderr
    failed = {"ctest:" + m.group(1) for m in map(_CTEST_FAILED.match, out.splitlines()) if m}
    print("  ctest: %d failure(s)" % len(failed), flush=True)
    return failed, False


def build_native():
    print("== build (cmake --build build -j) ==", flush=True)
    proc = _run(["cmake", "--build", "build", "-j"])
    if proc.returncode != 0:
        sys.stdout.write((proc.stdout + proc.stderr)[-3000:])
        print("  !! native build failed", flush=True)
        return False
    print("  build ok", flush=True)
    return True


def main():
    args = set(sys.argv[1:])
    do_pytest = "--ctest-only" not in args
    do_ctest = "--pytest-only" not in args
    do_build = "--no-build" not in args and do_ctest

    known = _load_baseline()
    current = set()
    harness_error = False

    if do_build and not build_native():
        return 2
    if do_pytest:
        f, err = run_pytest()
        current |= f
        harness_error = harness_error or err
    if do_ctest:
        f, err = run_ctest()
        current |= f
        harness_error = harness_error or err

    new_failures = sorted(current - known)
    fixed_baseline = sorted(known - current) if not harness_error else []

    print("\n" + "=" * 70)
    if fixed_baseline:
        print("BASELINE NOW PASSING — delete these lines from tests/known_failures.txt:")
        for t in fixed_baseline:
            print("  - " + t)
        print("-" * 70)
    if new_failures:
        print("NEW FAILURES (not in baseline) — these are REGRESSIONS to fix:")
        for t in new_failures:
            print("  ✗ " + t)
        print("=" * 70)
        return 1
    if harness_error:
        print("HARNESS ERROR — a suite could not be run to completion (see above).")
        print("=" * 70)
        return 2
    print("OK — no new failures. %d known failure(s) still baselined." % len(current & known))
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
