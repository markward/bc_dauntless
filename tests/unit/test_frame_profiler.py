"""engine.core.frame_profiler — the Python half of the frame profiler.

The value of a profiler is entirely in whether its numbers mean what the
report says they mean, so these tests pin the attribution rules rather than
just exercising the API.
"""
import time

import pytest

from engine.core import frame_profiler as fp


@pytest.fixture(autouse=True)
def _isolated_profiler():
    """Every test starts from a clean, disabled profiler and leaves one behind.

    The module holds process-global state, and set_enabled(native=False) keeps
    the C++ timer out of it entirely — these tests must not depend on whether
    the extension module was built.
    """
    fp.set_enabled(False, native=False)
    fp.reset()
    yield
    fp.set_enabled(False, native=False)
    fp.reset()


def _busy(seconds: float) -> None:
    """Spin for a real interval. sleep() would work too, but a busy wait keeps
    the measured time CPU time on every platform's clock."""
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        pass


def test_disabled_records_nothing():
    fp.begin_frame()
    fp.mark("a")
    _busy(0.002)
    fp.mark("b")
    fp.end_frame()
    assert fp.phases() == {}
    assert fp.frames() == 0
    assert fp.frame_ms() == 0.0


def test_first_mark_names_the_span_that_began_at_begin_frame():
    """mark() opens a phase; it does not close one that was never opened.

    So work done between begin_frame() and the SECOND mark belongs to the
    first mark's name. Getting this backwards would shift every phase's cost
    onto its neighbour, and the report would still look entirely plausible.
    """
    fp.set_enabled(True, native=False)
    fp.begin_frame()
    fp.mark("first")
    _busy(0.005)
    fp.mark("second")
    fp.end_frame()

    phases = fp.phases()
    assert set(phases) == {"first", "second"}
    assert phases["first"] > phases["second"]
    assert phases["first"] >= 4.0     # ~5 ms of busy work landed here


def test_end_frame_closes_the_last_phase():
    fp.set_enabled(True, native=False)
    fp.begin_frame()
    fp.mark("only")
    _busy(0.003)
    fp.end_frame()
    assert fp.phases()["only"] >= 2.0


def test_frame_total_covers_the_whole_body():
    fp.set_enabled(True, native=False)
    fp.begin_frame()
    fp.mark("a")
    _busy(0.002)
    fp.mark("b")
    _busy(0.002)
    fp.end_frame()

    total = fp.frame_ms()
    phases = fp.phases()
    # The total is the span, so it is at least the sum of the parts (equal up
    # to the cost of the mark() calls themselves).
    assert total >= phases["a"] + phases["b"] - 0.5
    assert fp.frames() == 1


def test_first_sample_seeds_rather_than_blending():
    """A new phase must report its measured time, not alpha x it.

    Seeding from zero would make every phase read ~15% of its true cost on the
    first frame and climb from there — long enough to mislead anyone who
    glances at the first report.
    """
    fp.set_enabled(True, native=False)
    fp.begin_frame()
    fp.mark("solo")
    _busy(0.004)
    fp.end_frame()
    first = fp.phases()["solo"]
    assert first >= 3.0, "first sample was blended toward zero"


def test_repeated_frames_smooth_toward_the_new_value():
    fp.set_enabled(True, native=False)
    # One expensive frame, then many cheap ones: the average must fall.
    fp.begin_frame(); fp.mark("p"); _busy(0.010); fp.end_frame()
    expensive = fp.phases()["p"]
    for _ in range(40):
        fp.begin_frame(); fp.mark("p"); fp.end_frame()
    assert fp.phases()["p"] < expensive / 2.0


def test_toggling_clears_accumulated_state():
    """Re-enabling must not blend against samples from a different scene."""
    fp.set_enabled(True, native=False)
    fp.begin_frame(); fp.mark("p"); _busy(0.003); fp.end_frame()
    assert fp.phases()

    fp.set_enabled(False, native=False)
    assert fp.phases() == {}
    fp.set_enabled(True, native=False)
    assert fp.phases() == {}
    assert fp.frames() == 0


def test_scope_accumulates_across_uses_in_one_frame():
    fp.set_enabled(True, native=False)
    fp.begin_frame()
    fp.mark("phase")
    with fp.scope("helper"):
        _busy(0.002)
    with fp.scope("helper"):
        _busy(0.002)
    fp.end_frame()
    # Two 2 ms uses accumulate into one 4 ms entry, not overwrite each other.
    assert fp.phases()["helper"] >= 3.0


def test_scope_is_a_passthrough_when_disabled():
    ran = []
    with fp.scope("x"):
        ran.append(1)
    assert ran == [1]
    assert fp.phases() == {}


def test_should_report_fires_on_the_interval_only():
    fp.set_enabled(True, native=False)
    fired = [fp.should_report() for _ in range(fp.REPORT_EVERY * 2)]
    assert fired.count(True) == 2
    assert fired[fp.REPORT_EVERY - 1] is True


def test_should_report_is_false_while_disabled():
    assert not any(fp.should_report() for _ in range(fp.REPORT_EVERY + 5))


def test_report_says_so_when_the_render_half_is_missing(monkeypatch):
    """A report that silently omitted the render passes would read as
    'the render costs nothing' — the single most misleading thing it could do."""
    from engine import host_io
    monkeypatch.setattr(host_io, "profiler_scopes", lambda: [])
    monkeypatch.setattr(
        host_io, "profiler_frame",
        lambda: {"cpu_ms": 0.0, "gpu_ms": 0.0, "frames": 0, "enabled": False},
    )
    fp.set_enabled(True, native=False)
    fp.begin_frame(); fp.mark("p"); fp.end_frame()

    text = "\n".join(fp.report_lines())
    assert "UNAVAILABLE" in text


def _present_report(monkeypatch, swap_interval):
    from engine import host_io
    monkeypatch.setattr(host_io, "profiler_scopes", lambda: [
        {"name": "space", "cpu_ms": 1.0, "gpu_ms": 2.0, "calls": 1, "depth": 1},
        {"name": "present", "cpu_ms": 9.0, "gpu_ms": 0.0, "calls": 1, "depth": 1},
    ])
    monkeypatch.setattr(
        host_io, "profiler_frame",
        lambda: {"cpu_ms": 12.0, "gpu_ms": 3.0, "frames": 10, "enabled": True,
                 "swap_interval": swap_interval},
    )
    fp.set_enabled(True, native=False)
    fp.begin_frame(); fp.mark("p"); fp.end_frame()
    return fp.report_lines()


def test_report_flags_the_vsync_wait_when_the_interval_is_one(monkeypatch):
    lines = _present_report(monkeypatch, 1)
    assert "VSYNC ON" in lines[0]
    present = [ln for ln in lines if "present" in ln]
    assert present and "vsync wait" in present[0]


def test_report_does_not_claim_a_vsync_wait_when_uncapped(monkeypatch):
    """A hidden window defaults to interval 0. The old report hard-coded the
    vsync note and so told every headless capture the opposite of the truth:
    that a real, uncapped cost was a block it could ignore."""
    lines = _present_report(monkeypatch, 0)
    assert "uncapped" in lines[0]
    present = [ln for ln in lines if "present" in ln]
    assert present and "not a vsync wait" in present[0]


def test_report_says_unknown_rather_than_guessing(monkeypatch):
    lines = _present_report(monkeypatch, -1)
    assert "unknown" in lines[0]


def test_report_states_that_the_totals_nest(monkeypatch):
    """python-loop total INCLUDES the render call. Without saying so, a reader
    adds the two totals and gets roughly double the real frame cost."""
    from engine import host_io
    monkeypatch.setattr(host_io, "profiler_scopes", lambda: [])
    monkeypatch.setattr(
        host_io, "profiler_frame",
        lambda: {"cpu_ms": 5.0, "gpu_ms": 4.0, "frames": 3, "enabled": True},
    )
    fp.set_enabled(True, native=False)
    fp.begin_frame(); fp.mark("p"); fp.end_frame()

    text = "\n".join(fp.report_lines())
    assert "includes r.frame" in text


def test_a_phase_that_stops_running_decays_toward_zero():
    """Otherwise its last reading freezes in the table and keeps being read as
    a live cost long after the work stopped happening."""
    fp.set_enabled(True, native=False)
    fp.begin_frame(); fp.mark("p"); _busy(0.008); fp.end_frame()
    hot = fp.phases()["p"]

    # "p" never runs again; the frames still turn over.
    for _ in range(40):
        fp.begin_frame()
        fp.mark("other")
        fp.end_frame()
    assert fp.phases()["p"] < hot / 4.0


def test_marks_repeated_in_one_frame_sum_rather_than_replace():
    fp.set_enabled(True, native=False)
    fp.begin_frame()
    fp.mark("a"); _busy(0.002)
    fp.mark("b"); _busy(0.001)
    fp.mark("a"); _busy(0.002)
    fp.end_frame()
    # Both "a" spans belong to the frame's total for "a".
    assert fp.phases()["a"] >= 3.0


def test_report_is_ascii_only(monkeypatch):
    """The report is written from inside the frame loop, and Windows consoles
    default to cp1252. A box-drawing character in a printed line raises
    UnicodeEncodeError there — the profiler taking down the game it measures.
    This caught exactly that on the first live run."""
    from engine import host_io
    monkeypatch.setattr(host_io, "profiler_scopes", lambda: [
        {"name": "frame", "cpu_ms": 8.0, "gpu_ms": 5.0, "calls": 1, "depth": 0},
        {"name": "present", "cpu_ms": 7.0, "gpu_ms": 0.0, "calls": 1, "depth": 1},
    ])
    monkeypatch.setattr(
        host_io, "profiler_frame",
        lambda: {"cpu_ms": 8.0, "gpu_ms": 5.0, "frames": 9, "enabled": True},
    )
    fp.set_enabled(True, native=False)
    fp.begin_frame(); fp.mark("p"); fp.end_frame()

    for line in fp.report_lines():
        line.encode("cp1252")   # raises UnicodeEncodeError on failure


def test_print_report_never_raises(monkeypatch):
    """A dead or encoding-hostile stream must drop the report, not the frame."""
    import sys

    class _Hostile:
        def write(self, _):
            raise UnicodeEncodeError("cp1252", "x", 0, 1, "nope")

    monkeypatch.setattr(sys, "stderr", _Hostile())
    fp.set_enabled(True, native=False)
    fp.begin_frame(); fp.mark("p"); fp.end_frame()
    fp.print_report()     # must return normally


def test_report_names_an_idle_capture_as_idle(monkeypatch):
    """The failure this exists to prevent: every early capture with this
    profiler measured a game with no combat in it (QuickBattle boots with an
    empty enemy list; the Maelstrom missions fire nothing in 900 ticks), and
    nothing in the output said so. Conclusions were drawn from an idle game."""
    monkeypatch.setattr(fp, "scene_summary",
                        lambda: "  scene: 9 ships, 0 projectiles in flight, "
                                "0 hull-damaged   <- IDLE: no combat")
    from engine import host_io
    monkeypatch.setattr(host_io, "profiler_scopes", lambda: [])
    monkeypatch.setattr(
        host_io, "profiler_frame",
        lambda: {"cpu_ms": 1.0, "gpu_ms": 1.0, "frames": 5, "enabled": True,
                 "swap_interval": 0},
    )
    fp.set_enabled(True, native=False)
    fp.begin_frame(); fp.mark("p"); fp.end_frame()
    text = "\n".join(fp.report_lines())
    assert "IDLE" in text


def test_scene_summary_never_raises_without_a_world():
    """Called at report time from inside the frame loop; there may be no
    mission (teardown, a swap in progress, a headless import context)."""
    line = fp.scene_summary()
    assert "scene:" in line


def test_scene_summary_flags_a_live_fight_as_not_idle(monkeypatch):
    class _Hull:
        def GetCondition(self): return 40.0
        def GetMaxCondition(self): return 100.0

    class _Ship:
        def GetHull(self): return _Hull()

    import engine.appc.ship_iter as si
    import engine.appc.projectiles as pr
    monkeypatch.setattr(si, "iter_ships", lambda: [_Ship(), _Ship()])
    monkeypatch.setattr(pr, "_active", [object(), object(), object()])

    line = fp.scene_summary()
    assert "2 ships" in line
    assert "3 projectiles" in line
    assert "2 hull-damaged" in line
    assert "IDLE" not in line
