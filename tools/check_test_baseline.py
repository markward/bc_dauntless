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

Skips: a gtest SKIP exits 0, so a gate that only reads failures stays green
over tests that never ran -- 74 asset-backed C++ tests did exactly that once BC
content moved out of the project. So when a BC content root is configured
(DAUNTLESS_GAME_DIR, else engine/paths.game_root()), any ctest SKIP that is not
baselined as "skip:ctest:<name>" in tests/known_failures.txt FAILS the gate,
and a baselined skip that now runs is reported for deletion. With no content
root, asset-backed tests legitimately skip: the count is printed, nothing fails.
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
_PYTEST_ERRORED = re.compile(r"^ERROR (\S+)")
# pytest always prints a counts summary ("12 passed, 1 failed in 3.2s",
# "no tests ran in 0.1s"). Its absence means the runner never got that far.
_PYTEST_RAN = re.compile(r"(\d+ (passed|failed|error|skipped|xfailed|xpassed)|no tests ran)")
# ctest summary blocks: "\t188 - FrameTest.Name (Failed)" / "(Subprocess aborted)"
# / "(Timeout)" under "FAILED", "(Skipped)" / "(Disabled)" under "did not run".
# The name is (.+?), not \S+: parameterised names carry spaces
# ("AllSamples/HeaderTest.X/48-byte object <E0-47 ...>"), and \S+ made a
# failing one invisible to the gate.
_CTEST_SUMMARY = re.compile(
    r"^\s*\d+ - (.+?) \((Failed|Subprocess aborted|Timeout|Child aborted|Skipped)\)\s*$")
_SKIP_PREFIX = "skip:"
# A test that only exercises an OPTIONAL mod (present only on machines where
# that mod happens to be installed) is never "pre-existing" or "fixed" in the
# skip:/failure sense -- its skip is legitimate exactly while its declared
# asset is absent. Form: "optional-mod:<ctest id> <path relative to the mods
# root>", e.g. "optional-mod:ctest:Foo.Bar CGSovereign/data/x.nif".
_OPTIONAL_MOD_PREFIX = "optional-mod:"


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


def split_baseline(known):
    """Split ledger ids into (known failures, known skips); skip ids lose the
    'skip:' prefix so they compare directly with parse_ctest's ids.

    'optional-mod:' lines are neither -- they are handled entirely separately
    (parse_optional_mod_entries / diff_optional_mod_skips) because their
    legitimacy depends on whether their declared mod asset exists, not on a
    fixed baseline membership test.
    """
    failures = set()
    skips = set()
    for k in known:
        if k.startswith(_OPTIONAL_MOD_PREFIX):
            continue
        if k.startswith(_SKIP_PREFIX):
            skips.add(k[len(_SKIP_PREFIX):])
        else:
            failures.add(k)
    return failures, skips


def parse_optional_mod_entries(known):
    """{ctest id: path relative to the mods root} for every 'optional-mod:'
    baseline line. The path never contains a space, so splitting off the
    LAST space-separated token survives a parameterised ctest id that does
    (parse_ctest already has to handle that same shape)."""
    entries = {}
    for k in known:
        if not k.startswith(_OPTIONAL_MOD_PREFIX):
            continue
        rest = k[len(_OPTIONAL_MOD_PREFIX):]
        ctest_id, sep, path = rest.rpartition(" ")
        if sep and ctest_id and path:
            entries[ctest_id] = path
    return entries


def diff_optional_mod_skips(skipped, entries, mods_root_path):
    """optional-mod ctest ids that skipped even though their declared asset
    IS present under `mods_root_path` -- a genuine regression, since the
    ledger form exists to explain skips caused by an ABSENT optional mod, not
    any other reason. An id whose asset is absent (the common case) is a
    legitimate skip and never appears here; an id that ran at all (present in
    `entries` but not in `skipped`) never appears here either -- nothing to
    report when it works, by design of the ledger form. A mods root that
    could not be resolved makes every skip legitimate, matching diff_skips'
    "no content root" posture.
    """
    if mods_root_path is None:
        return []
    new = []
    for ctest_id, rel in sorted(entries.items()):
        if ctest_id in skipped and os.path.exists(os.path.join(mods_root_path, rel)):
            new.append(ctest_id)
    return new


def parse_ctest(out):
    """Return (failed ids, skipped ids) from ctest's summary blocks."""
    failed, skipped = set(), set()
    for line in out.splitlines():
        m = _CTEST_SUMMARY.match(line)
        if not m:
            continue
        (skipped if m.group(2) == "Skipped" else failed).add("ctest:" + m.group(1))
    return failed, skipped


def diff_skips(skipped, known_skips, content_configured):
    """Return (new skips, baselined skips that now run). Both are empty without
    a content root: every asset-backed test skips then, legitimately."""
    if not content_configured:
        return [], []
    return sorted(skipped - known_skips), sorted(known_skips - skipped)


def stale_baseline(known, current, suites_ran):
    """Baselined failures that did not fail -- judged only for suites that ran
    (a --ctest-only run cannot say a pytest line now passes)."""
    return sorted(k for k in known - current if k.split(":", 1)[0] in suites_ran)


def _engine_game_root():
    sys.path.insert(0, ROOT)
    from engine import paths
    return paths.game_root()


def content_root():
    """The BC content root the C++ tests should read, or None when there is
    none. DAUNTLESS_GAME_DIR wins when set (non-empty); else engine/paths.
    Either way it must be an existing directory to count as configured."""
    root = os.environ.get("DAUNTLESS_GAME_DIR", "")
    if not root:
        try:
            root = str(_engine_game_root())
        except Exception:
            return None
    return root if root and os.path.isdir(root) else None


def _engine_mods_root():
    sys.path.insert(0, ROOT)
    from engine import mods
    return mods.mods_root()


def mods_root():
    """Where optional-mod ledger entries resolve their paths, or None when
    resolution itself failed. DAUNTLESS_MODS_DIR wins when set (non-empty);
    else engine.mods.mods_root() -- the SAME rule native/tests/support/
    content_root.h's mods_root() applies in C++, so both sides agree on one
    answer. Unlike content_root(), the directory need not exist: an absent
    root just means every optional-mod path is absent under it, which
    diff_optional_mod_skips already treats as the legitimate-skip case."""
    root = os.environ.get("DAUNTLESS_MODS_DIR", "")
    if not root:
        try:
            root = str(_engine_mods_root())
        except Exception:
            return None
    return root


def _run(cmd, **kw):
    print("  $ " + " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, **kw)


def run_pytest():
    """Run the full pytest suite under the RSS watchdog; return set of failed ids."""
    print("== pytest ==", flush=True)
    cmd = [
        "uv", "run", "python", "tools/pytest_rss_watchdog.py", CEILING_MB, "--",
        "uv", "run", "pytest", "tests", "-q", "-rfE", "--tb=no", "-p", "no:cacheprovider",
    ]
    proc = _run(cmd)
    out = proc.stdout + proc.stderr
    lines = out.splitlines()
    failed = {"pytest:" + m.group(1) for m in map(_PYTEST_FAILED.match, lines) if m}
    # Errors (e.g. fixture/setup errors) fail a test just as surely as an
    # assertion failure, but pytest reports them under a separate "ERROR"
    # marker and its exit code with only errors present is still 1 — the same
    # code as "there were failures". Fold errors into the same set so they are
    # diffed against the baseline identically to failures, rather than being
    # invisible to a gate that only ever looked for "^FAILED ".
    failed |= {"pytest:" + m.group(1) for m in map(_PYTEST_ERRORED.match, lines) if m}
    # rc 99 == watchdog OOM kill; surface it as a harness error, not a clean pass.
    if proc.returncode == 99:
        print("  !! pytest watchdog killed the run (RSS ceiling) — incomplete", flush=True)
        return failed, True
    # A non-zero rc with no parsed failures means something broke (collection error).
    if proc.returncode not in (0, 1) and not failed:
        sys.stdout.write(out[-2000:])
        print("  !! pytest exited %d with no parseable failures" % proc.returncode, flush=True)
        return failed, True
    # Positive evidence the suite actually ran. rc==1 is pytest's "there were
    # failures", but it is also what a crashed wrapper returns, so rc alone
    # cannot tell "no failures" from "nothing ran" -- and the difference is a
    # green gate over an unrun suite. The RSS watchdog used to die on import
    # under Windows (os.setsid) and this reported "pytest: 0 failure(s)" with
    # 3 tests failing underneath.
    if not _PYTEST_RAN.search(out):
        sys.stdout.write(out[-2000:])
        print("  !! pytest produced no summary line - the suite did not run",
              flush=True)
        return failed, True
    print("  pytest: %d failure(s)" % len(failed), flush=True)
    return failed, False


def run_ctest(root, mods_root_path=None):
    """Run the C++ ctest suite; return (failed ids, skipped ids, harness error).
    (Build separately.) `root` is exported so asset-backed tests find BC;
    `mods_root_path` likewise for tests behind an optional mod."""
    print("== ctest ==", flush=True)
    if not os.path.isfile(os.path.join(BUILD_DIR, "CTestTestfile.cmake")):
        print("  !! no ctest configuration in build/ — run cmake first", flush=True)
        return set(), set(), True
    env = dict(os.environ)
    if root:
        env["DAUNTLESS_GAME_DIR"] = root
    if mods_root_path:
        env["DAUNTLESS_MODS_DIR"] = mods_root_path
    proc = _run(["ctest", "--test-dir", "build", "--output-on-failure"], env=env)
    out = proc.stdout + proc.stderr
    failed, skipped = parse_ctest(out)
    print("  ctest: %d failure(s), %d skipped" % (len(failed), len(skipped)), flush=True)
    return failed, skipped, False


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

    baseline_raw = _load_baseline()
    known, known_skips = split_baseline(baseline_raw)
    optional_mod_entries = parse_optional_mod_entries(baseline_raw)
    current = set()
    skipped = set()
    harness_error = False
    root = content_root() if do_ctest else None
    mods_root_path = mods_root() if do_ctest else None

    if do_build and not build_native():
        return 2
    if do_pytest:
        f, err = run_pytest()
        current |= f
        harness_error = harness_error or err
    if do_ctest:
        f, skipped, err = run_ctest(root, mods_root_path)
        current |= f
        harness_error = harness_error or err

    new_failures = sorted(current - known)
    suites_ran = {s for s, on in (("pytest", do_pytest), ("ctest", do_ctest)) if on}
    fixed_baseline = [] if harness_error else stale_baseline(known, current, suites_ran)
    # optional-mod ids are judged entirely by diff_optional_mod_skips, never
    # by the generic skip:/delete-me machinery -- pull them out of `skipped`
    # first, or an absent-mod skip (legitimate) reads as an unbaselined new
    # skip, and a present-mod skip that later starts running (also
    # legitimate: "nothing to report") reads as a stale baseline line to
    # delete, which the ledger form explicitly promises never happens.
    optional_mod_ids = set(optional_mod_entries)
    new_skips, running_skips = ([], []) if harness_error else \
        diff_skips(skipped - optional_mod_ids, known_skips, root is not None)
    new_optional_mod_skips = [] if harness_error else \
        diff_optional_mod_skips(skipped, optional_mod_entries, mods_root_path)
    new_skips = sorted(new_skips + new_optional_mod_skips)
    fixed_baseline += ["skip:" + t for t in running_skips]

    print("\n" + "=" * 70)
    if fixed_baseline:
        print("BASELINE NOW PASSING — delete these lines from tests/known_failures.txt:")
        for t in fixed_baseline:
            print("  - " + t)
        print("-" * 70)
    if do_ctest and not harness_error:
        if root is None:
            print("⚠ NO BC CONTENT ROOT — %d ctest test(s) SKIPPED, asset-backed "
                  "tests did not run." % len(skipped))
        else:
            print("ctest: %d skipped with BC content at %s (%d baselined)."
                  % (len(skipped), root, len(skipped & known_skips)))
        print("-" * 70)
    if new_skips:
        print("NEW SKIPS (BC content IS configured, so these should have run) —")
        print("route the test through native/tests/support/content_root.h, or")
        print("baseline it as 'skip:<id>' in tests/known_failures.txt WITH a reason:")
        for t in new_skips:
            print("  ⊘ " + t)
        print("-" * 70)
    if new_failures:
        print("NEW FAILURES (not in baseline) — these are REGRESSIONS to fix:")
        for t in new_failures:
            print("  ✗ " + t)
        print("=" * 70)
        return 1
    if new_skips:
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
