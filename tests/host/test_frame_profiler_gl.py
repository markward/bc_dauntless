"""The frame profiler against a real GL context.

The unit tests cover attribution and smoothing with no GL involved. This is
the other half: the GL_TIMESTAMP query path, which the unit tests cannot
reach and which is where a profiler most easily lies — by reporting zeros,
by stalling on an unready query, or by never resolving at all.

Headless GLFW is enough: timer queries are context state, not window state.
"""
import os

import pytest

pytest.importorskip("_dauntless_host")
import _dauntless_host as h  # noqa: E402


@pytest.fixture(scope="module")
def host():
    """A GL context for this module only.

    shutdown() in teardown is NOT optional: init() raises if the host is
    already initialised, so leaving the context up makes every later host
    test in the session fail at its own init(). Omitting it here cost 13
    unrelated failures in tests/host.
    """
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    h.init(320, 180, "test_frame_profiler_gl")
    try:
        yield h
    finally:
        h.profiler_set_enabled(False)
        h.shutdown()


@pytest.fixture(autouse=True)
def _clean_profiler(host):
    host.profiler_set_enabled(False)
    yield
    host.profiler_set_enabled(False)


def _run_frames(n):
    for _ in range(n):
        h.frame()


def test_disabled_records_nothing(host):
    _run_frames(5)
    assert host.profiler_scopes() == []
    assert host.profiler_frame()["frames"] == 0


def test_enabling_resolves_scopes_within_the_ring_latency(host):
    """Results are read back kRingDepth (3) frames late, so a handful of
    frames must be enough to see a resolved table. If this ever needs many
    frames, resolve() is silently dropping records as unavailable."""
    host.profiler_set_enabled(True)
    _run_frames(8)
    scopes = host.profiler_scopes()
    assert scopes, "no scopes resolved after 8 frames"
    assert host.profiler_frame()["frames"] >= 1


def test_the_frame_scope_is_present_and_outermost(host):
    host.profiler_set_enabled(True)
    _run_frames(8)
    scopes = host.profiler_scopes()
    by_name = {s["name"]: s for s in scopes}
    assert "frame" in by_name, sorted(by_name)
    assert by_name["frame"]["depth"] == 0
    # Everything else nests inside it.
    assert all(s["depth"] >= 1 for s in scopes if s["name"] != "frame")


def test_cpu_time_is_actually_measured(host):
    """A scope reporting exactly 0.0 CPU ms would mean the clock never ran."""
    host.profiler_set_enabled(True)
    _run_frames(10)
    by_name = {s["name"]: s for s in host.profiler_scopes()}
    assert by_name["frame"]["cpu_ms"] > 0.0
    assert host.profiler_frame()["cpu_ms"] > 0.0


def test_gpu_timestamps_resolve_to_a_nonnegative_span(host):
    """GPU spans come from two GL_TIMESTAMP queries differenced. A negative
    span means the pair was mismatched; a NaN means the readback was garbage.

    Not asserted > 0: an empty headless scene can legitimately finish a pass
    inside the timer's resolution, and a driver that reports 0 there is not
    wrong. The bug this guards against is a nonsense value, not a small one.
    """
    host.profiler_set_enabled(True)
    _run_frames(10)
    for s in host.profiler_scopes():
        assert s["gpu_ms"] >= 0.0, s
        assert s["gpu_ms"] == s["gpu_ms"], s      # NaN check
        assert s["gpu_ms"] < 1000.0, s            # a pass is not a second long


def test_call_counts_are_per_frame_not_cumulative(host):
    """`calls` is the raw count from the last resolved frame. If it grew with
    frame count it would be a running total wearing a per-frame label."""
    host.profiler_set_enabled(True)
    _run_frames(8)
    early = {s["name"]: s["calls"] for s in host.profiler_scopes()}
    _run_frames(40)
    late = {s["name"]: s["calls"] for s in host.profiler_scopes()}
    assert early["frame"] == 1
    assert late["frame"] == 1
    assert early == late


def test_toggling_off_and_on_clears_the_table(host):
    host.profiler_set_enabled(True)
    _run_frames(8)
    assert host.profiler_scopes()

    host.profiler_set_enabled(False)
    assert host.profiler_scopes() == []
    assert host.profiler_frame()["frames"] == 0

    # And it recovers rather than staying dead.
    host.profiler_set_enabled(True)
    _run_frames(8)
    assert host.profiler_scopes()


def test_resolving_does_not_stall_on_the_gpu(host):
    """The whole point of the 3-frame ring: reading results must not block.

    Enabled frames should not cost dramatically more wall-clock than disabled
    ones. A profiler that calls glGetQueryObjectui64v on an unready query
    stalls the CPU on the GPU and measures its own stall — the failure this
    catches would otherwise look like "rendering got slower".
    """
    import time

    _run_frames(20)                      # warm, disabled
    t0 = time.perf_counter()
    _run_frames(60)
    off_s = time.perf_counter() - t0

    host.profiler_set_enabled(True)
    _run_frames(20)                      # warm, enabled
    t0 = time.perf_counter()
    _run_frames(60)
    on_s = time.perf_counter() - t0

    # Generous bound: this is a smoke test for a pipeline stall (which shows
    # up as a multiple), not a measurement of the profiler's overhead.
    assert on_s < off_s * 3.0 + 0.050, (
        "enabled frames took %.1f ms vs %.1f ms disabled — looks like a stall"
        % (on_s * 1000, off_s * 1000))


def test_the_table_describes_the_frame_it_reports(host):
    """Every reported scope ran in the last resolved frame, and its depth is
    the depth it had THERE.

    Not "every scope ever seen, at the depth it first had". Passes change
    parent at runtime — render_space runs under `space` in the exterior view
    and under `viewscreen.rtt` on the bridge — so a first-sight tree prints
    this frame's children beneath a previous mission's parent: every row
    individually correct, the tree collectively a lie.
    """
    host.profiler_set_enabled(True)
    _run_frames(10)
    scopes = host.profiler_scopes()

    # Nothing inert is listed: a scope in the table ran.
    assert all(s["calls"] >= 1 for s in scopes), \
        [s for s in scopes if s["calls"] < 1]

    # Depth is walkable: it starts at 0 and never jumps by more than one,
    # which is only true if the depths come from one consistent frame.
    depths = [s["depth"] for s in scopes]
    assert depths[0] == 0
    for prev, cur in zip(depths, depths[1:]):
        assert cur <= prev + 1, (prev, cur, scopes)


def test_a_scope_entered_twice_is_one_row_with_two_calls(host):
    """Re-entry must accumulate into the existing row, not append a second."""
    host.profiler_set_enabled(True)
    _run_frames(10)
    names = [s["name"] for s in host.profiler_scopes()]
    assert len(names) == len(set(names)), names
