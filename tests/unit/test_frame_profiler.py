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


def _nested_frame():
    """One frame shaped like the real loop: two mark() phases, each with a
    scope subtree under it, exactly as host_loop nests them.

        sim                 <- mark
          sim.gameloop      <- scope, once per catch-up tick
            gl.ai           <- scope, inside the tick
          sim.combat        <- scope, once per frame
            cb.projectiles  <- scope, inside it
    """
    fp.begin_frame()
    fp.mark("sim")
    fp.note_sim_ticks(3)
    for _ in range(3):
        with fp.scope("sim.gameloop"):
            with fp.scope("gl.ai"):
                _busy(0.001)
    with fp.scope("sim.combat"):
        with fp.scope("cb.projectiles"):
            _busy(0.001)
    fp.end_frame()


def _phase_rows(lines):
    """The python-phase table's rows, keyed by the name they carry."""
    rows = {}
    for ln in lines:
        stripped = ln.strip()
        if not stripped:
            continue
        head = stripped.split()[0]
        if head in ("sim", "sim.gameloop", "gl.ai", "sim.combat",
                    "cb.projectiles"):
            rows[head] = ln
    return rows


def _indent_of(line):
    return len(line) - len(line.lstrip(" "))


def test_the_report_indents_children_under_their_parent(monkeypatch):
    """The Python half nests now -- sim > sim.gameloop > gl.ai -- and printing
    all of it at one indentation put children ABOVE their parents with nothing
    marking the relation, so the column summed to ~3x the real frame."""
    from engine import host_io
    monkeypatch.setattr(host_io, "profiler_scopes", lambda: [])
    monkeypatch.setattr(
        host_io, "profiler_frame",
        lambda: {"cpu_ms": 0.0, "gpu_ms": 0.0, "frames": 0, "enabled": False},
    )
    fp.set_enabled(True, native=False)
    _nested_frame()

    lines = fp.report_lines()
    rows = _phase_rows(lines)
    assert set(rows) == {"sim", "sim.gameloop", "gl.ai", "sim.combat",
                         "cb.projectiles"}, sorted(rows)

    # Parents print ABOVE their children...
    order = [ln for ln in lines if ln in rows.values()]
    assert order.index(rows["sim"]) < order.index(rows["sim.gameloop"])
    assert order.index(rows["sim.gameloop"]) < order.index(rows["gl.ai"])
    assert order.index(rows["sim.combat"]) < order.index(rows["cb.projectiles"])

    # ...and deeper, so the containment is visible without reading the names.
    assert _indent_of(rows["sim.gameloop"]) > _indent_of(rows["sim"])
    assert _indent_of(rows["gl.ai"]) > _indent_of(rows["sim.gameloop"])
    assert _indent_of(rows["cb.projectiles"]) > _indent_of(rows["sim.combat"])
    assert _indent_of(rows["sim.combat"]) == _indent_of(rows["sim.gameloop"])


def test_the_report_says_the_phase_column_must_not_be_summed(monkeypatch):
    """Indentation alone still invites adding the column up. The nesting is
    stated in words as well, because that sum is ~3x the real frame cost."""
    from engine import host_io
    monkeypatch.setattr(host_io, "profiler_scopes", lambda: [])
    monkeypatch.setattr(
        host_io, "profiler_frame",
        lambda: {"cpu_ms": 0.0, "gpu_ms": 0.0, "frames": 0, "enabled": False},
    )
    fp.set_enabled(True, native=False)
    _nested_frame()
    text = "\n".join(fp.report_lines())
    assert "included in" in text and "do not sum" in text.lower()


def test_per_tick_rows_are_marked_apart_from_per_frame_ones(monkeypatch):
    """`sim.gameloop` and everything under it is a SUM over the frame's N
    catch-up ticks; `sim.combat` and everything under IT runs once per frame.
    Printed adjacent with nothing distinguishing them, the tick count beside
    the table invites dividing all of them by N -- wrong for half the rows."""
    from engine import host_io
    monkeypatch.setattr(host_io, "profiler_scopes", lambda: [])
    monkeypatch.setattr(
        host_io, "profiler_frame",
        lambda: {"cpu_ms": 0.0, "gpu_ms": 0.0, "frames": 0, "enabled": False},
    )
    fp.set_enabled(True, native=False)
    _nested_frame()
    rows = _phase_rows(fp.report_lines())

    marker = fp.PER_TICK_MARK
    assert rows["sim.gameloop"].rstrip().endswith(marker), rows["sim.gameloop"]
    assert rows["gl.ai"].rstrip().endswith(marker), rows["gl.ai"]
    assert not rows["sim.combat"].rstrip().endswith(marker), rows["sim.combat"]
    assert not rows["cb.projectiles"].rstrip().endswith(marker)
    assert not rows["sim"].rstrip().endswith(marker)
    # And the legend says what the mark means, so it is not a mystery glyph.
    assert "per tick" in "\n".join(fp.report_lines())


def test_the_phase_table_carries_per_frame_call_counts(monkeypatch):
    """The generic backstop for the per-tick problem: a row entered 3 times in
    one frame says so, so nobody has to guess which rows are sums."""
    from engine import host_io
    monkeypatch.setattr(host_io, "profiler_scopes", lambda: [])
    monkeypatch.setattr(
        host_io, "profiler_frame",
        lambda: {"cpu_ms": 0.0, "gpu_ms": 0.0, "frames": 0, "enabled": False},
    )
    fp.set_enabled(True, native=False)
    _nested_frame()
    assert fp.calls() == {"sim": 1, "sim.gameloop": 3, "gl.ai": 3,
                          "sim.combat": 1, "cb.projectiles": 1}
    rows = _phase_rows(fp.report_lines())
    # "<name> <cpu ms> <calls> [mark]"
    assert rows["gl.ai"].split()[2] == "3", rows["gl.ai"]
    assert rows["sim.combat"].split()[2] == "1", rows["sim.combat"]


def test_sim_ticks_is_smoothed_like_every_other_number_beside_it(monkeypatch):
    """The raw last-frame count was printed beside EMA-smoothed costs, so
    dividing one by the other mixed an instantaneous value into an average."""
    fp.set_enabled(True, native=False)
    for n in (10, 10, 10, 10, 0):
        fp.begin_frame()
        fp.note_sim_ticks(n)
        fp.end_frame()
    assert fp.sim_ticks() == 0                 # instantaneous, unchanged
    assert fp.sim_ticks_avg() > 1.0            # smoothed, still remembers the 10s

    from engine import host_io
    monkeypatch.setattr(host_io, "profiler_scopes", lambda: [])
    monkeypatch.setattr(
        host_io, "profiler_frame",
        lambda: {"cpu_ms": 0.0, "gpu_ms": 0.0, "frames": 0, "enabled": False},
    )
    tick_line = [ln for ln in fp.report_lines() if "sim ticks" in ln]
    assert tick_line, fp.report_lines()
    assert "avg" in tick_line[0] and "last frame" in tick_line[0]


def test_report_flags_a_dead_gpu_column_rather_than_printing_zeros(monkeypatch):
    """A driver that returns zeroed GL_TIMESTAMP counters (Apple's GL does)
    yields a full column of 0.000, which reads as 'the GPU is free' -- the
    exact misreading the UNAVAILABLE line exists to prevent elsewhere."""
    from engine import host_io
    monkeypatch.setattr(host_io, "profiler_scopes", lambda: [
        {"name": "frame", "cpu_ms": 8.0, "gpu_ms": 0.0, "calls": 1, "depth": 0},
        {"name": "present", "cpu_ms": 7.0, "gpu_ms": 0.0, "calls": 1, "depth": 1},
    ])
    monkeypatch.setattr(
        host_io, "profiler_frame",
        lambda: {"cpu_ms": 8.0, "gpu_ms": 0.0, "frames": 400, "enabled": True,
                 "swap_interval": 0},
    )
    fp.set_enabled(True, native=False)
    fp.begin_frame(); fp.mark("p"); fp.end_frame()
    text = "\n".join(fp.report_lines())
    assert "GPU TIMING UNAVAILABLE" in text
    # And the column itself must not read as a measured zero.
    frame_row = [ln for ln in fp.report_lines()
                 if ln.strip().startswith("frame ")][0]
    assert "0.000" not in frame_row, frame_row


def test_a_working_gpu_column_is_not_flagged(monkeypatch):
    """The flag must key on 'zero across many resolved frames', not on any
    zero: a cheap pass legitimately measures 0.000."""
    from engine import host_io
    monkeypatch.setattr(host_io, "profiler_scopes", lambda: [
        {"name": "frame", "cpu_ms": 8.0, "gpu_ms": 5.0, "calls": 1, "depth": 0},
        {"name": "anim", "cpu_ms": 1.0, "gpu_ms": 0.0, "calls": 1, "depth": 1},
    ])
    monkeypatch.setattr(
        host_io, "profiler_frame",
        lambda: {"cpu_ms": 8.0, "gpu_ms": 5.0, "frames": 400, "enabled": True,
                 "swap_interval": 0},
    )
    fp.set_enabled(True, native=False)
    fp.begin_frame(); fp.mark("p"); fp.end_frame()
    text = "\n".join(fp.report_lines())
    assert "GPU TIMING UNAVAILABLE" not in text


def test_an_over_long_label_is_visibly_marked_not_silently_clipped(monkeypatch):
    """A clipped name reads as a different, shorter phase -- and panel scopes
    (`ui.<panel name>`, indented under ui.render_all) do overflow the column."""
    from engine import host_io
    long_name = "ui.a_panel_with_a_really_long_name_indeed"
    monkeypatch.setattr(host_io, "profiler_scopes", lambda: [
        {"name": long_name, "cpu_ms": 1.0, "gpu_ms": 1.0, "calls": 1, "depth": 2},
    ])
    monkeypatch.setattr(
        host_io, "profiler_frame",
        lambda: {"cpu_ms": 1.0, "gpu_ms": 1.0, "frames": 10, "enabled": True,
                 "swap_interval": 0},
    )
    fp.set_enabled(True, native=False)
    fp.begin_frame()
    fp.mark("ui_panels")
    with fp.scope(long_name):
        pass
    fp.end_frame()

    lines = fp.report_lines()
    clipped = [ln for ln in lines if long_name[:20] in ln]
    assert clipped, lines
    for ln in clipped:
        assert long_name in ln or fp.CLIP_MARK in ln, ln


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


def test_enabling_mid_frame_does_not_report_a_garbage_total():
    """Toggling the profiler on is the DOCUMENTED primary workflow: the user
    hits the key mid-frame, so that frame's begin_frame() already ran while
    disabled and no-opped.

    end_frame() then measured (now - _frame_t0) with _frame_t0 still 0.0 --
    i.e. perf_counter() from its arbitrary epoch, hundreds of thousands of
    seconds. Because reset() also cleared _frame_seeded, that value was
    ASSIGNED rather than blended, so the headline "python loop" total started
    at ~8.5e8 ms and decayed over the following reports, reading as though the
    frame were getting faster.

    A frame the profiler did not open must not be reported at all.
    """
    fp.set_enabled(True, native=False)
    fp.reset()

    # The frame that was already in flight when the profiler came on: no
    # begin_frame(), because it ran before enabling.
    fp.end_frame()
    assert fp.frame_ms() == 0.0, (
        f"a frame that was never opened was reported as {fp.frame_ms()} ms")

    # A properly opened frame still reports.
    fp.begin_frame()
    fp.end_frame()
    assert fp.frame_ms() > 0.0
    assert fp.frame_ms() < 1000.0, (
        f"frame total {fp.frame_ms()} ms is wall-clock-epoch garbage, "
        "not a frame duration")


def test_reset_clears_the_report_interval_and_tick_count():
    """reset() left _since_report and _sim_ticks standing. A toggle-off /
    toggle-on near the end of an interval therefore made the very next frame
    report -- which is what turned the seeding bug above into an immediately
    visible ~8.5e8 ms line rather than a quietly wrong average."""
    fp.set_enabled(True, native=False)
    fp.note_sim_ticks(17)
    for _ in range(5):
        fp.begin_frame()
        fp.end_frame()

    fp.reset()
    assert fp.sim_ticks() == 0, "stale tick count survived a reset"
    # A full interval must elapse from the reset, not from wherever the
    # previous run happened to leave the counter.
    for i in range(fp.REPORT_EVERY - 1):
        assert not fp.should_report(), (
            f"reported after {i + 1} frames; the interval survived the reset")
    assert fp.should_report()
