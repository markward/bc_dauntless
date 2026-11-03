"""The test gate (tools/check_test_baseline.py) must SEE what ctest did.

A gtest SKIP exits 0, so a gate that only parses failures reported green while
74 asset-backed C++ tests never ran (hard-coded <project>/game after BC content
became configurable). These pin the parser and the skip ratchet.
"""
import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "check_test_baseline.py"
_spec = importlib.util.spec_from_file_location("check_test_baseline", _SCRIPT)
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


# Verbatim shape of ctest's closing summary blocks.
_CTEST_OUT = """\
99% tests passed, 1 tests failed out of 1167

Total Test time (real) =  20.63 sec

The following tests did not run:
\t 34 - NiNodeParser.GalaxyRootNiNodeParses (Skipped)
\t 49 - AllSamples/HeaderTest.RecognizedAsBcVersion/Galaxy (Skipped)
\t1035 - PlaneIndex.GalaxyAnchors (Disabled)

The following tests FAILED:
\t1151 - HullConnectivity.GalaxySizedLatticeIsFastEnough (Failed)
\t 50 - AllSamples/HeaderTest.HasNonEmptyTextHeader/48-byte object <E0-47 00-02> (Failed)
\t 77 - Crashy.Test (Subprocess aborted)
Errors while running CTest
"""


def test_parse_ctest_collects_failures_including_names_with_spaces():
    failed, _ = gate.parse_ctest(_CTEST_OUT)
    assert failed == {
        "ctest:HullConnectivity.GalaxySizedLatticeIsFastEnough",
        # A parameterised name with spaces used to be invisible: the old regex
        # was (\S+) \(Failed\), which can never match across the space.
        "ctest:AllSamples/HeaderTest.HasNonEmptyTextHeader/48-byte object <E0-47 00-02>",
        "ctest:Crashy.Test",
    }


def test_parse_ctest_collects_skips_but_not_disabled_tests():
    _, skipped = gate.parse_ctest(_CTEST_OUT)
    assert skipped == {
        "ctest:NiNodeParser.GalaxyRootNiNodeParses",
        "ctest:AllSamples/HeaderTest.RecognizedAsBcVersion/Galaxy",
    }


def test_parse_ctest_all_green_has_nothing():
    assert gate.parse_ctest("100% tests passed, 0 tests failed out of 12\n") == (set(), set())


def test_split_baseline_separates_skip_entries():
    failures, skips = gate.split_baseline({
        "pytest:tests/x.py::t", "ctest:A.b", "skip:ctest:C.d",
    })
    assert failures == {"pytest:tests/x.py::t", "ctest:A.b"}
    assert skips == {"ctest:C.d"}


# --- the skip ratchet ---------------------------------------------------------

def test_unlisted_skip_with_content_root_is_new():
    new, running = gate.diff_skips({"ctest:A.x", "ctest:B.y"}, {"ctest:A.x"},
                                   content_configured=True)
    assert new == ["ctest:B.y"]
    assert running == []


def test_baselined_skip_that_now_runs_is_reported_for_deletion():
    new, running = gate.diff_skips(set(), {"ctest:A.x"}, content_configured=True)
    assert new == []
    assert running == ["ctest:A.x"]


def test_no_content_root_never_flags_skips():
    # A machine with no BC install legitimately skips every asset-backed test;
    # the gate reports the count but must not fail or ask for ledger edits.
    new, running = gate.diff_skips({"ctest:B.y"}, {"ctest:A.x"}, content_configured=False)
    assert new == []
    assert running == []


# --- content root -------------------------------------------------------------

def test_content_root_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DAUNTLESS_GAME_DIR", str(tmp_path))
    assert gate.content_root() == str(tmp_path)


def test_content_root_env_pointing_nowhere_is_not_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("DAUNTLESS_GAME_DIR", str(tmp_path / "absent"))
    assert gate.content_root() is None


def test_content_root_empty_env_falls_back_to_engine_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("DAUNTLESS_GAME_DIR", "")
    monkeypatch.setattr(gate, "_engine_game_root", lambda: tmp_path)
    assert gate.content_root() == str(tmp_path)


def test_content_root_engine_failure_is_not_configured(monkeypatch):
    monkeypatch.delenv("DAUNTLESS_GAME_DIR", raising=False)

    def boom():
        raise RuntimeError("no paths")

    monkeypatch.setattr(gate, "_engine_game_root", boom)
    assert gate.content_root() is None


# --- stale baseline -----------------------------------------------------------

def test_stale_baseline_only_judges_suites_that_ran():
    # --ctest-only used to announce every pytest baseline line as "now
    # passing" -- it never ran, so it cannot have passed.
    known = {"pytest:tests/x.py::t", "ctest:A.b"}
    assert gate.stale_baseline(known, set(), suites_ran={"ctest"}) == ["ctest:A.b"]
    assert gate.stale_baseline(known, {"ctest:A.b"}, suites_ran={"ctest", "pytest"}) \
        == ["pytest:tests/x.py::t"]


# --- optional-mod skips --------------------------------------------------------
#
# A test that only exists to exercise an OPTIONAL mod (present only where that
# mod happens to be installed) must not be baselined as an ordinary
# "skip:ctest:<name>" -- that line would be a lie the moment someone runs the
# gate with the mod installed, since the skip:/delete-me machinery expects a
# baselined skip to eventually start running. "optional-mod:ctest:<name>
# <path relative to the mods root>" instead ties the skip's legitimacy to
# whether that one path exists.

def test_split_baseline_ignores_optional_mod_entries():
    failures, skips = gate.split_baseline({
        "pytest:tests/x.py::t", "skip:ctest:C.d",
        "optional-mod:ctest:E.f CGSovereign/data/x.nif",
    })
    assert failures == {"pytest:tests/x.py::t"}
    assert skips == {"ctest:C.d"}


def test_parse_optional_mod_entries_extracts_id_and_path():
    entries = gate.parse_optional_mod_entries({
        "skip:ctest:C.d",
        "optional-mod:ctest:E.f CGSovereign/data/x.nif",
    })
    assert entries == {"ctest:E.f": "CGSovereign/data/x.nif"}


def test_optional_mod_skip_with_absent_path_is_not_reported(tmp_path):
    # mod absent + skip -> not reported
    entries = {"ctest:E.f": "CGSovereign/data/x.nif"}
    new = gate.diff_optional_mod_skips({"ctest:E.f"}, entries, str(tmp_path))
    assert new == []


def test_optional_mod_skip_with_present_path_is_new_skip(tmp_path):
    # mod present + skip -> new skip
    (tmp_path / "CGSovereign" / "data").mkdir(parents=True)
    (tmp_path / "CGSovereign" / "data" / "x.nif").write_text("stub")
    entries = {"ctest:E.f": "CGSovereign/data/x.nif"}
    new = gate.diff_optional_mod_skips({"ctest:E.f"}, entries, str(tmp_path))
    assert new == ["ctest:E.f"]


def test_optional_mod_present_path_that_ran_is_not_reported(tmp_path):
    # mod present + ran -> nothing (no "delete this line" nag either)
    (tmp_path / "CGSovereign" / "data").mkdir(parents=True)
    (tmp_path / "CGSovereign" / "data" / "x.nif").write_text("stub")
    entries = {"ctest:E.f": "CGSovereign/data/x.nif"}
    new = gate.diff_optional_mod_skips(set(), entries, str(tmp_path))
    assert new == []


def test_optional_mod_skip_with_no_mods_root_is_not_reported():
    entries = {"ctest:E.f": "CGSovereign/data/x.nif"}
    new = gate.diff_optional_mod_skips({"ctest:E.f"}, entries, None)
    assert new == []


# --- mods root ------------------------------------------------------------

def test_mods_root_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DAUNTLESS_MODS_DIR", str(tmp_path))
    assert gate.mods_root() == str(tmp_path)


def test_mods_root_empty_env_falls_back_to_engine_mods(tmp_path, monkeypatch):
    monkeypatch.setenv("DAUNTLESS_MODS_DIR", "")
    monkeypatch.setattr(gate, "_engine_mods_root", lambda: tmp_path)
    assert gate.mods_root() == str(tmp_path)


def test_mods_root_engine_failure_returns_none(monkeypatch):
    monkeypatch.delenv("DAUNTLESS_MODS_DIR", raising=False)

    def boom():
        raise RuntimeError("no mods")

    monkeypatch.setattr(gate, "_engine_mods_root", boom)
    assert gate.mods_root() is None

# --- in-process pass ----------------------------------------------------------
# ctest runs each case in its own process from the build dir. That hid a real
# renderer bug (the scuff map's lazy load clobbering a mesh's base texture only
# loaded from the project-root CWD) and a fixture leaking GL state across
# cases. The gate also runs every gtest binary once, whole, from the root.

_GTEST_OUT = """\
[==========] Running 4 tests from 2 test suites.
[ RUN      ] FrameTest.Scorch
frame_test.cc:12: Failure
[  FAILED  ] FrameTest.Scorch (139 ms)
[ RUN      ] AllSamples/HeaderTest.Recognized/Galaxy
[  FAILED  ] AllSamples/HeaderTest.Recognized/Galaxy, where GetParam() = Galaxy (0 ms)
[ RUN      ] FrameTest.Fine
[       OK ] FrameTest.Fine (3 ms)
[==========] 4 tests from 2 test suites ran. (200 ms total)
[  PASSED  ] 2 tests.
[  FAILED  ] 2 tests, listed below:
[  FAILED  ] FrameTest.Scorch
[  FAILED  ] AllSamples/HeaderTest.Recognized/Galaxy, where GetParam() = Galaxy

 2 FAILED TESTS
"""


def test_parse_gtest_collects_each_failed_case_once():
    failed, completed = gate.parse_gtest(_GTEST_OUT)
    assert failed == {"inproc:FrameTest.Scorch",
                      "inproc:AllSamples/HeaderTest.Recognized/Galaxy"}
    assert completed


def test_parse_gtest_without_closing_summary_did_not_complete():
    # A segfault mid-binary leaves no "[==========] N tests ... ran." line.
    failed, completed = gate.parse_gtest(
        "[==========] Running 3 tests from 1 test suite.\n[ RUN      ] A.b\n")
    assert failed == set()
    assert not completed


_CTEST_JSON = """{
  "tests": [
    {"name": "A.one", "command": ["/b/nif_tests", "--gtest_filter=A.one"]},
    {"name": "A.two", "command": ["/b/nif_tests", "--gtest_filter=A.two"]},
    {"name": "R.one", "command": ["/b/renderer_tests", "--gtest_filter=R.one"],
     "properties": [{"name": "ENVIRONMENT", "value": ["GALLIUM_DRIVER=llvmpipe"]},
                    {"name": "WORKING_DIRECTORY", "value": "/b"}]},
    {"name": "scan", "command": ["/b/scan_nifs", "some/dir"]},
    {"name": "NoCommand"}
  ]
}"""


def test_gtest_binaries_from_ctest_json_dedupes_and_keeps_environment():
    # A plain add_test() tool (scan_nifs) is not gtest: it prints no gtest
    # summary, so running it "whole" would read as a crash. Only commands
    # gtest_discover_tests generated (they carry --gtest_filter=) count.
    assert gate.gtest_binaries(_CTEST_JSON) == [
        ("/b/nif_tests", {}),
        ("/b/renderer_tests", {"GALLIUM_DRIVER": "llvmpipe"}),
    ]


def test_stale_baseline_judges_inproc_lines_only_when_that_pass_ran():
    known = {"inproc:A.b", "ctest:C.d"}
    assert gate.stale_baseline(known, set(), suites_ran={"ctest"}) == ["ctest:C.d"]
    assert gate.stale_baseline(known, set(), suites_ran={"ctest", "inproc"}) \
        == ["ctest:C.d", "inproc:A.b"]


# --- pytest pass: streamed, verbose, hang-dumping ------------------------------
# The gate used to run pytest with capture_output=True and -q: nothing printed
# until the end, so a hanging test was 80 minutes of silence. It now streams
# pytest's output line by line, prints each test's name (-v: a hang shows the
# last finished test) and has pytest dump every thread's stack for any test
# running past 5 minutes (faulthandler_timeout).

# Verbatim shape of `pytest -v -rfE --tb=no` output.
_PYTEST_VERBOSE_OUT = """\
WATCHDOG ceiling=4000 MB  cmd=uv run pytest tests -v
============================= test session starts ==============================
collecting ... collected 5 items

tests/unit/test_s.py::test_ok PASSED                                     [ 20%]
tests/unit/test_s.py::test_fail FAILED                                   [ 40%]
tests/unit/test_s.py::test_err PASSED                                    [ 60%]
tests/unit/test_s.py::test_err ERROR                                     [ 60%]
tests/unit/test_s.py::test_p[c] PASSED                                   [100%]

=========================== short test summary info ============================
FAILED tests/unit/test_s.py::test_fail - assert 0
ERROR tests/unit/test_s.py::test_err - RuntimeError: teardown
===================== 1 failed, 3 passed, 1 error in 0.01s =====================
WATCHDOG DONE peak_rss=300.0 MB  killed=False  rc=1
"""


def _fake_stream(out, rc, calls):
    def stream(cmd, **kw):
        calls.append((cmd, kw))
        return rc, out
    return stream


def test_run_pytest_is_verbose_with_a_hang_timeout_and_parses_the_summary(
        monkeypatch):
    calls = []
    monkeypatch.setattr(gate, "_stream", _fake_stream(_PYTEST_VERBOSE_OUT, 1, calls))
    failed, harness_error = gate.run_pytest()
    # The per-test "::test_fail FAILED" progress lines are not counted twice;
    # only the -rfE summary lines are.
    assert failed == {"pytest:tests/unit/test_s.py::test_fail",
                      "pytest:tests/unit/test_s.py::test_err"}
    assert not harness_error
    (cmd, kw), = calls
    pytest_args = cmd[cmd.index("pytest"):]
    assert "-v" in pytest_args and "-q" not in pytest_args
    assert "-rfE" in pytest_args
    i = pytest_args.index("-o")
    assert pytest_args[i + 1] == "faulthandler_timeout=300"
    # Still under the RSS watchdog, and every Python in the chain unbuffered
    # so lines arrive as they are written, not in 8 KB blocks at the end.
    assert "tools/pytest_rss_watchdog.py" in cmd
    assert kw["env"]["PYTHONUNBUFFERED"] == "1"


def test_run_pytest_without_a_summary_line_is_a_harness_error(monkeypatch):
    monkeypatch.setattr(gate, "_stream", _fake_stream("WATCHDOG died\n", 1, []))
    failed, harness_error = gate.run_pytest()
    assert failed == set() and harness_error


def test_run_pytest_watchdog_kill_is_a_harness_error(monkeypatch):
    monkeypatch.setattr(gate, "_stream", _fake_stream(_PYTEST_VERBOSE_OUT, 99, []))
    failed, harness_error = gate.run_pytest()
    assert harness_error
    assert "pytest:tests/unit/test_s.py::test_fail" in failed


def test_stream_echoes_each_line_before_the_child_exits(tmp_path):
    # The child prints one line, then waits (up to 20 s) for the echo of that
    # line to be seen before printing the next. A gate that buffered until
    # exit would never echo in time and the child would print "late".
    import sys
    flag = tmp_path / "echoed"
    child = (
        "import os, sys, time\n"
        "print('first', flush=True)\n"
        "print('to stderr', file=sys.stderr, flush=True)\n"
        "t = time.time()\n"
        "while not os.path.exists(%r) and time.time() - t < 20:\n"
        "    time.sleep(0.01)\n"
        "print('second' if os.path.exists(%r) else 'late', flush=True)\n"
        "sys.exit(3)\n" % (str(flag), str(flag)))
    echoed = []

    def echo(line):
        echoed.append(line)
        if line.strip() == "first":
            flag.write_text("")

    rc, out = gate._stream([sys.executable, "-c", child], echo=echo)
    assert rc == 3
    assert echoed == ["first\n", "to stderr\n", "second\n"]
    assert out == "first\nto stderr\nsecond\n"   # stderr merged, all collected
