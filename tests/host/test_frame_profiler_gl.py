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


def test_a_dead_gpu_column_is_reported_as_unavailable_not_as_zeros(host):
    """A GPU column of 0.000 must never be readable as "the GPU is free".

    This replaces an assertion that could not fail. The old test checked
    `gpu_ms >= 0.0` and `gpu_ms == gpu_ms`, both of which the C++ side
    guarantees by construction: gpu_ns only accumulates when `t1 >= t0`, and a
    uint64 difference divided by 1e6 cannot be NaN. It therefore passed on the
    one real failure mode it was near — this machine's GL returns ZEROED
    GL_TIMESTAMP counters, so every span is exactly 0.000 and the whole column
    reads as free.

    So assert the thing that can actually be wrong: either the driver measures
    something, or the report says the column is not measured.
    """
    from engine.core import frame_profiler as fp

    host.profiler_set_enabled(True)
    _run_frames(max(40, fp.GPU_ZERO_FRAMES + 10))

    scopes = host.profiler_scopes()
    assert scopes, "nothing resolved"
    # Whatever the driver does, the numbers must at least be readable ones.
    for s in scopes:
        assert 0.0 <= s["gpu_ms"] < 1000.0, s     # a pass is not a second long

    frame = host.profiler_frame()
    fp.set_enabled(True, native=False)
    try:
        fp.begin_frame(); fp.mark("p"); fp.end_frame()
        text = "\n".join(fp.report_lines())
    finally:
        fp.set_enabled(False, native=False)

    if frame["gpu_ms"] == 0.0:
        assert "GPU TIMING UNAVAILABLE" in text, (
            "the whole frame measured 0.000 ms of GPU time over %d frames and "
            "the report printed it as a measurement:\n%s"
            % (frame["frames"], text))
    else:
        assert "GPU TIMING UNAVAILABLE" not in text, text


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

    A profiler that calls glGetQueryObjectui64v on an unready query stalls the
    CPU on the GPU and measures its own stall — the failure this catches would
    otherwise present as "rendering got slower".

    MEASURED AS A MINIMUM OVER REPEATS, not a single timed run. The single-run
    form failed intermittently in the full gate (never in isolation, never in
    its own file, never across all of tests/host — only after several thousand
    preceding tests) because it compares WALL CLOCK, and anything that perturbs
    timing perturbs it: GC pressure, the RSS watchdog sampling twice a second,
    thermal state.

    The minimum is the right statistic for the property being defended. A real
    pipeline stall blocks EVERY enabled frame, so it raises the floor and is
    still caught. A load spike raises some batches and leaves the floor alone.
    Taking a mean or a single sample conflates the two.
    """
    import time

    def _best_of(batches, frames=60):
        best = float("inf")
        for _ in range(batches):
            t0 = time.perf_counter()
            _run_frames(frames)
            best = min(best, time.perf_counter() - t0)
        return best

    _run_frames(20)                      # warm, disabled
    off_s = _best_of(5)

    host.profiler_set_enabled(True)
    _run_frames(20)                      # warm, enabled
    on_s = _best_of(5)

    # MEASURED SENSITIVITY (injected a sleep into FrameTimer::end_frame on the
    # enabled path and rebuilt): 400 us/frame passes, 2 ms/frame fails. That is
    # the right order — a real glGetQueryObjectui64v block on an unready query
    # waits for the GPU to catch up, which is milliseconds. Below ~1 ms/frame
    # this is deliberately blind: that is overhead, not a stall, and chasing it
    # here would make the test fail on load instead of on defects.
    assert on_s < off_s * 3.0 + 0.050, (
        "enabled frames took %.1f ms vs %.1f ms disabled (best of 5 batches of "
        "60) — looks like a stall" % (on_s * 1000, off_s * 1000))


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


# DELETED: test_a_scope_entered_twice_is_one_row_with_two_calls.
#
# It ran plain frames and asserted the reported names were UNIQUE — but nothing
# in a headless empty scene is entered twice (every row comes back calls=1), so
# no arrangement of this test could produce the duplicate it claimed to reject.
# It could not fail.
#
# The path it named — push() folding a re-entry into the existing row instead of
# appending a second one — is real and still untested. Reaching it needs a pass
# that genuinely runs twice in one frame, which here means the bridge
# viewscreen RTT rendering the space scene alongside the exterior view; that is
# a full bridge set, not something h.frame() produces on an empty headless
# scene. Covering it wants a gtest driving FrameTimer directly (push/push/pop/
# pop the same name, then read results()), which is where it should go.


def test_the_whole_frame_gpu_total_agrees_with_the_frame_row(host):
    """The headline GPU total and the `frame` row's own gpu_ms are the same
    span, so they must not disagree.

    They used to: the total was taken from `samples.back().q_end`, which is the
    last scope PUSHED (`present`), not the last one CLOSED (`frame`, which
    end_frame closes after every child). That reported present.end -
    frame.begin as the frame total, printed one line above a `frame` row
    measuring frame.end - frame.begin.
    """
    host.profiler_set_enabled(True)
    _run_frames(20)
    by_name = {s["name"]: s for s in host.profiler_scopes()}
    assert "frame" in by_name, sorted(by_name)
    total = host.profiler_frame()["gpu_ms"]
    # Both are EMA-smoothed with the same alpha from the same frames, so on a
    # driver that measures anything they track each other closely; on one that
    # returns zeros they are both 0.
    assert abs(total - by_name["frame"]["gpu_ms"]) <= 0.5 + 0.05 * total, (
        total, by_name["frame"])
