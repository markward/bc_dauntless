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

In-process pass: ctest runs every case in its own process from the build dir,
which hides cross-test state leaks AND anything that only loads from the
project-root CWD the game runs from -- together they once hid a real renderer
bug. So after ctest the gate runs each gtest binary ONCE, whole, from the
project root, and reports its failures as "inproc:<name>" (baselineable like
any other id). Skip with --no-inproc.

Tiers (spec docs/superpowers/specs/2026-11-06-two-tier-test-gate-design.md):
  --tier full   (default; scripts/gate_full.sh): everything below, plus the
                peak-RSS budget, merge-catchable vs deep-only attribution of
                each new failure, and the merge tier's projected cost.
  --tier merge  (scripts/gate_merge.sh): pytest minus the deep list
                (-m "not deep"), and each gtest binary once in-process minus
                deep_gtest.txt -- no per-case ctest. In-process skips are
                gated like ctest skips (mapped to their ctest names).
Artefacts (logs, per-test durations, each binary's gtest output) go to
$GATE_ARTEFACT_DIR, else a fresh temp directory; the path is printed.

Usage:
  uv run python tools/check_test_baseline.py            # build C++, run both
  uv run python tools/check_test_baseline.py --no-build # skip cmake build
  uv run python tools/check_test_baseline.py --pytest-only
  uv run python tools/check_test_baseline.py --ctest-only
  uv run python tools/check_test_baseline.py --no-inproc   # ctest, but skip the in-process pass

Skips: a gtest SKIP exits 0, so a gate that only reads failures stays green
over tests that never ran -- 74 asset-backed C++ tests did exactly that once BC
content moved out of the project. So when a BC content root is configured
(DAUNTLESS_GAME_DIR, else engine/paths.game_root()), any ctest SKIP that is not
baselined as "skip:ctest:<name>" in tests/known_failures.txt FAILS the gate,
and a baselined skip that now runs is reported for deletion. With no content
root, asset-backed tests legitimately skip: the count is printed, nothing fails.
"""
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.helpers import gate_tiers as gt  # noqa: E402

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

# gtest's per-case result line; the summary list repeats it without the timing.
_GTEST_FAILED = re.compile(r"^\[  FAILED  \] (\S+?)(?:, where GetParam\(\) = .*)? \(\d+ ms\)$")
_GTEST_DONE = re.compile(r"^\[==========\] \d+ tests? from \d+ test suites? ran\.")
INPROC_TIMEOUT_S = 900
# The full gate fails when pytest's peak RSS passes this (the watchdog's
# CEILING_MB SIGKILL stays as the host's safety net above it). Measured
# 2026-11-06 after the per-test reset fix: 2,903 MB for the whole suite in
# one process (was 4,308 MB); 3,300 MB leaves ~14% headroom. See
# docs/reference/architecture/test-suite-memory.md.
RSS_BUDGET_MB = float(os.environ.get("PYTEST_RSS_BUDGET_MB", "3300"))
MERGE_BUDGET_S = 300.0
_PEAK_RSS = re.compile(r"WATCHDOG DONE peak_rss=([\d.]+) MB")
_GTEST_SKIPPED = re.compile(r"^\[  SKIPPED \] (\S+) \(\d+ ms\)$")
# Filled by the runs, read by main()'s report.
RUN_INFO = {}


def parse_peak_rss(out):
    m = None
    for m in _PEAK_RSS.finditer(out):
        pass
    return float(m.group(1)) if m else None


def parse_gtest_skips(out):
    return {m.group(1) for m in map(_GTEST_SKIPPED.match, out.splitlines()) if m}


def gtest_prefixes(ctest_json):
    """{executable: ctest TEST_PREFIX} -- ctest names a case prefix + its
    gtest name (combat_tests: "combat_"), so an in-process skip maps back to
    the ctest id the ledger's skip:/optional-mod: lines use."""
    out = {}
    for t in json.loads(ctest_json).get("tests", []):
        cmd = t.get("command") or []
        filt = [a[len("--gtest_filter="):] for a in cmd[1:] if a.startswith("--gtest_filter=")]
        name = t.get("name", "")
        if cmd and filt and cmd[0] not in out and name.endswith(filt[0]):
            out[cmd[0]] = name[:len(name) - len(filt[0])]
    return out


def ctest_to_gtest(ctest_json):
    """{ctest name: (binary basename, gtest name)}."""
    out = {}
    for t in json.loads(ctest_json).get("tests", []):
        cmd = t.get("command") or []
        filt = [a[len("--gtest_filter="):] for a in cmd[1:] if a.startswith("--gtest_filter=")]
        if cmd and filt:
            out[t.get("name", "")] = (os.path.basename(cmd[0]), filt[0])
    return out


def artefact_dir(tier):
    d = os.environ.get("GATE_ARTEFACT_DIR", "")
    if not d:
        import tempfile
        import time as _t
        d = os.path.join(tempfile.gettempdir(), "dauntless-gate",
                         "%s-%s" % (tier, _t.strftime("%Y%m%d-%H%M%S")))
    os.makedirs(d, exist_ok=True)
    return d


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


def parse_gtest(out):
    """Return (failed 'inproc:' ids, completed) for one gtest binary's output.
    `completed` is False when gtest never printed its closing summary -- the
    binary crashed or hung part-way, and its unrun tests cannot count as passes."""
    failed = {"inproc:" + m.group(1) for m in map(_GTEST_FAILED.match, out.splitlines()) if m}
    completed = any(_GTEST_DONE.match(l) for l in out.splitlines())
    return failed, completed


def gtest_binaries(ctest_json):
    """Unique gtest (executable, extra env) pairs from `ctest --show-only=json-v1`, in
    first-seen order. The env is each test's ENVIRONMENT property (e.g. the
    renderer tests' GALLIUM_DRIVER), taken from the binary's first test."""
    seen = {}
    for t in json.loads(ctest_json).get("tests", []):
        cmd = t.get("command")
        # Only gtest_discover_tests cases (they carry --gtest_filter=); a plain
        # add_test() tool prints no gtest summary and would read as a crash.
        if not cmd or cmd[0] in seen or not any(a.startswith("--gtest_filter=") for a in cmd[1:]):
            continue
        env = {}
        for prop in t.get("properties", []):
            if prop.get("name") == "ENVIRONMENT":
                for kv in prop.get("value", []):
                    k, _, v = kv.partition("=")
                    env[k] = v
        seen[cmd[0]] = env
    return list(seen.items())


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


def _echo(line):
    sys.stdout.write(line)
    sys.stdout.flush()


def _stream(cmd, echo=_echo, **kw):
    """Run cmd with stderr merged into stdout, passing each line to `echo` as
    it arrives (the gate shows progress instead of 80 minutes of silence) and
    returning (returncode, all output) for the same parsing as before."""
    print("  $ " + " ".join(cmd), flush=True)
    proc = subprocess.Popen(cmd, cwd=ROOT, text=True, errors="replace",
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            bufsize=1, **kw)
    lines = []
    for line in proc.stdout:
        lines.append(line)
        echo(line)
    proc.stdout.close()
    return proc.wait(), "".join(lines)


def run_pytest(tier="full", artefacts=None):
    """Run the full pytest suite under the RSS watchdog; return set of failed ids.

    Streamed, verbose (-v: each test's name as it finishes, so a hang shows
    the last finished test) and with faulthandler_timeout: any single test
    running past 5 minutes dumps every thread's Python stack into the output.
    PYTHONUNBUFFERED reaches the watchdog and pytest (the watchdog's child
    inherits its stdout and env), so lines arrive as written, not in blocks.
    """
    print("== pytest ==", flush=True)
    cmd = [
        "uv", "run", "python", "tools/pytest_rss_watchdog.py", CEILING_MB, "--",
        "uv", "run", "pytest", "tests", "-v", "-rfE", "--tb=no", "-p", "no:cacheprovider",
        "-o", "faulthandler_timeout=300",
    ]
    if tier == "merge":
        cmd += ["-m", "not deep"]
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    if artefacts:
        cmd += ["-p", "tools.pytest_durations_plugin"]
        env["GATE_DURATIONS_OUT"] = os.path.join(artefacts, "pytest_durations.json")
        env["PYTHONPATH"] = ROOT + os.pathsep + env.get("PYTHONPATH", "")
    returncode, out = _stream(cmd, env=env)
    RUN_INFO["peak_rss_mb"] = parse_peak_rss(out)
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
    if returncode == 99:
        print("  !! pytest watchdog killed the run (RSS ceiling) — incomplete", flush=True)
        return failed, True
    # A non-zero rc with no parsed failures means something broke (collection error).
    if returncode not in (0, 1) and not failed:
        sys.stdout.write(out[-2000:])
        print("  !! pytest exited %d with no parseable failures" % returncode, flush=True)
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


def run_inproc(root, deep=None, artefacts=None):
    """Run each gtest binary once, whole (minus `deep`: {binary: names}),
    from the project root; return (failed 'inproc:' ids, skipped ctest ids,
    harness error). With `deep`, a suite left with no case to run is a
    harness error: that area lost its merge-tier coverage."""
    print("== in-process (each gtest binary once, CWD = project root) ==", flush=True)
    listing = _run(["ctest", "--test-dir", "build", "--show-only=json-v1"])
    if listing.returncode != 0:
        print("  !! could not list ctest tests", flush=True)
        return set(), set(), True
    prefixes = gtest_prefixes(listing.stdout)
    failed, skipped, error = set(), set(), False
    for exe, extra in gtest_binaries(listing.stdout):
        env = dict(os.environ)
        env.update(extra)
        if root:
            env["DAUNTLESS_GAME_DIR"] = root
        name = os.path.basename(exe)
        args = [exe]
        if deep is not None:
            names = gt.parse_gtest_list(subprocess.run(
                [exe, "--gtest_list_tests"], cwd=ROOT, env=env, text=True,
                capture_output=True).stdout)
            mine = deep.get(name, set()) & set(names)
            lost = gt.uncovered_suites(names, mine)
            if lost:
                print("  !! %s: suites with no merge-tier case: %s"
                      % (name, ", ".join(lost)), flush=True)
                error = True
            if mine:
                args.append(gt.gtest_filter(mine))
        try:
            proc = subprocess.run(args, cwd=ROOT, env=env, text=True,
                                  capture_output=True, timeout=INPROC_TIMEOUT_S)
            out = proc.stdout + proc.stderr
        except subprocess.TimeoutExpired:
            out = ""
        if artefacts:
            with open(os.path.join(artefacts, "inproc_%s.log" % name), "w",
                      encoding="utf-8") as fh:
                fh.write(out)
        f, completed = parse_gtest(out)
        if not completed:
            # A crash/hang takes every later test with it; name the binary.
            f.add("inproc:%s(did-not-complete)" % name)
        sk = {"ctest:" + prefixes.get(exe, "") + n for n in parse_gtest_skips(out)}
        print("  %-24s %d failure(s), %d skipped%s" % (
            name, len(f), len(sk), "" if completed else "  !! did not complete"), flush=True)
        failed |= f
        skipped |= sk
    return failed, skipped, error


def build_native():
    print("== build (cmake --build build -j) ==", flush=True)
    proc = _run(["cmake", "--build", "build", "-j"])
    if proc.returncode != 0:
        sys.stdout.write((proc.stdout + proc.stderr)[-3000:])
        print("  !! native build failed", flush=True)
        return False
    print("  build ok", flush=True)
    return True


def _tier(argv):
    for i, a in enumerate(argv):
        if a == "--tier" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--tier="):
            return a.split("=", 1)[1]
    return "full"


def attribute(failures, deep_pytest, deep_gtest, ctest_map):
    """Split new failure ids into (merge gate would have caught it, deep-only).
    pytest: by the deep list. ctest:<name>: its gtest case, by deep_gtest.
    inproc:<name>: by deep_gtest (any binary). A binary that did not complete
    is merge-catchable: the merge gate runs every binary."""
    is_deep = gt.deep_matcher(deep_pytest)
    all_deep = set().union(*deep_gtest.values()) if deep_gtest else set()
    merge, deep = [], []
    for f in failures:
        suite, _, name = f.partition(":")
        if suite == "pytest":
            d = is_deep(name)
        elif suite == "ctest":
            b, g = ctest_map.get(name, (None, name))
            d = g in deep_gtest.get(b, ()) if b else g in all_deep
        elif suite == "inproc":
            d = name in all_deep
        else:
            d = False
        (deep if d else merge).append(f)
    return merge, deep


def main():
    argv = sys.argv[1:]
    args = set(argv)
    tier = _tier(argv)
    if tier not in ("merge", "full"):
        print("unknown --tier %r (merge | full)" % tier)
        return 2
    merge_tier = tier == "merge"
    do_pytest = "--ctest-only" not in args
    do_ctest = "--pytest-only" not in args and not merge_tier
    do_build = "--no-build" not in args and "--pytest-only" not in args
    do_inproc = "--pytest-only" not in args and "--no-inproc" not in args
    art = artefact_dir(tier)
    t_start = time.time()
    phases = []
    print("gate tier: %s   artefacts: %s" % (tier, art), flush=True)

    baseline_raw = _load_baseline()
    known, known_skips = split_baseline(baseline_raw)
    optional_mod_entries = parse_optional_mod_entries(baseline_raw)
    current = set()
    skipped = set()
    harness_error = False
    root = content_root() if do_inproc or do_ctest else None
    mods_root_path = mods_root() if do_inproc or do_ctest else None
    deep_gtest = gt.load_deep_gtest()

    def _phase(name, t0):
        phases.append((name, time.time() - t0))

    if do_build:
        t0 = time.time()
        if not build_native():
            return 2
        _phase("build", t0)
    if do_pytest:
        t0 = time.time()
        f, err = run_pytest(tier, art)
        current |= f
        harness_error = harness_error or err
        _phase("pytest", t0)
    if do_ctest:
        t0 = time.time()
        f, skipped, err = run_ctest(root, mods_root_path)
        current |= f
        harness_error = harness_error or err
        _phase("ctest", t0)
    if do_inproc:
        t0 = time.time()
        f, inproc_skips, err = run_inproc(
            root, deep=deep_gtest if merge_tier else None, artefacts=art)
        current |= f
        if merge_tier:
            skipped = inproc_skips      # the merge tier's only C++ skip source
        harness_error = harness_error or err
        _phase("in-process gtest", t0)

    new_failures = sorted(current - known)
    suites_ran = {s for s, on in (("pytest", do_pytest), ("ctest", do_ctest),
                                   ("inproc", do_inproc)) if on}
    # The merge tier does not run the deep tests, so it cannot say a
    # baselined failure or skip now passes: only the full gate judges that.
    fixed_baseline = [] if harness_error or merge_tier else \
        stale_baseline(known, current, suites_ran)
    # optional-mod ids are judged entirely by diff_optional_mod_skips, never
    # by the generic skip:/delete-me machinery -- pull them out of `skipped`
    # first, or an absent-mod skip (legitimate) reads as an unbaselined new
    # skip, and a present-mod skip that later starts running (also
    # legitimate: "nothing to report") reads as a stale baseline line to
    # delete, which the ledger form explicitly promises never happens.
    optional_mod_ids = set(optional_mod_entries)
    new_skips, running_skips = ([], []) if harness_error else \
        diff_skips(skipped - optional_mod_ids, known_skips, root is not None)
    if merge_tier:
        running_skips = []
    new_optional_mod_skips = [] if harness_error else \
        diff_optional_mod_skips(skipped, optional_mod_entries, mods_root_path)
    new_skips = sorted(new_skips + new_optional_mod_skips)
    fixed_baseline += ["skip:" + t for t in running_skips]

    # Full gate only: the memory budget and the merge tier's projected cost.
    budget_failures = []
    peak = RUN_INFO.get("peak_rss_mb")
    if not merge_tier and do_pytest and not harness_error:
        steps = os.path.join(art, "pytest_durations.json.rss.json")
        if os.path.isfile(steps):
            with open(steps, encoding="utf-8") as fh:
                top = list(json.load(fh).items())[:5]
            print("pytest peak RSS %s MB; largest high-water rises: %s" % (
                "?" if peak is None else "%.0f" % peak,
                "; ".join("%s +%.0f MB" % kv for kv in top)))
        if peak is None:
            budget_failures.append("pytest peak RSS was not reported by the watchdog")
        elif peak > RSS_BUDGET_MB:
            budget_failures.append(
                "pytest peak RSS %.0f MB is over the %.0f MB budget "
                "(docs/reference/architecture/test-suite-memory.md)" % (peak, RSS_BUDGET_MB))
        try:
            durations, case_ms = gt.load_artefacts(art)
            py = gt.project_pytest(durations, gt.load_deep_pytest())
            cc = gt.project_gtest(case_ms, deep_gtest) if do_inproc else 0.0
            print("merge tier projected from this run: pytest %.0f s (budget %.0f), "
                  "gtest %.0f s (budget %.0f)" % (py, gt.PYTEST_FAIL_S, cc, gt.GTEST_FAIL_S))
            if py > gt.PYTEST_FAIL_S or cc > gt.GTEST_FAIL_S:
                budget_failures.append(
                    "the merge tier has outgrown its budget: run "
                    "`uv run python tools/gate_tiers.py generate %s` and commit "
                    "tests/gate_tiers/" % art)
        except (OSError, ValueError) as e:
            budget_failures.append("could not project the merge tier: %r" % (e,))

    print("\n" + "=" * 70)
    total = time.time() - t_start
    print("%s gate: %s  total %.0f s (%.1f min)%s" % (
        tier, "  ".join("%s %.0f s" % p for p in phases), total, total / 60.0,
        "" if peak is None else "  pytest peak RSS %.0f MB" % peak))
    if merge_tier and total > MERGE_BUDGET_S:
        print("⚠ the merge gate took over %.0f s: regenerate the tiers from the "
              "last full gate's artefacts (tools/gate_tiers.py generate)" % MERGE_BUDGET_S)
    print("artefacts: %s" % art)
    print("-" * 70)
    if fixed_baseline:
        print("BASELINE NOW PASSING — delete these lines from tests/known_failures.txt:")
        for t in fixed_baseline:
            print("  - " + t)
        print("-" * 70)
    if (do_ctest or do_inproc) and not harness_error:
        src = "in-process gtest" if merge_tier else "ctest"
        if root is None:
            print("⚠ NO BC CONTENT ROOT — %d %s test(s) SKIPPED, asset-backed "
                  "tests did not run." % (len(skipped), src))
        else:
            print("%s: %d skipped with BC content at %s (%d baselined)."
                  % (src, len(skipped), root, len(skipped & known_skips)))
        print("-" * 70)
    if new_skips:
        print("NEW SKIPS (BC content IS configured, so these should have run) —")
        print("route the test through native/tests/support/content_root.h, or")
        print("baseline it as 'skip:<id>' in tests/known_failures.txt WITH a reason:")
        for t in new_skips:
            print("  ⊘ " + t)
        print("-" * 70)
    for b in budget_failures:
        print("BUDGET: " + b)
    if budget_failures:
        print("-" * 70)
    if new_failures:
        if merge_tier:
            print("NEW FAILURES (not in baseline) — these are REGRESSIONS to fix:")
            for t in new_failures:
                print("  ✗ " + t)
        else:
            ctest_map = {}
            listing = _run(["ctest", "--test-dir", "build", "--show-only=json-v1"])
            if listing.returncode == 0:
                ctest_map = ctest_to_gtest(listing.stdout)
            merge, deep = attribute(new_failures, gt.load_deep_pytest(), deep_gtest, ctest_map)
            print("NEW FAILURES (not in baseline) — these are REGRESSIONS to fix.")
            print("The merge gate would ALSO have caught these (%d):" % len(merge))
            for t in merge:
                print("  ✗ " + t)
            print("Deep-only: only the full gate runs these (%d):" % len(deep))
            for t in deep:
                print("  ✗ " + t)
        print("=" * 70)
        return 1
    if new_skips or budget_failures:
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
