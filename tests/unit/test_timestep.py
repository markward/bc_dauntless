"""Pure-function unit tests for the fixed-timestep accumulator.

The accumulator is independent of GameLoop and the renderer, so these
tests need no fixtures and run in milliseconds.
"""

from engine.core.timestep import step_accumulator

TICK_DT = 1.0 / 60.0
MAX_FRAME_DT = 0.25


def test_steady_state_60hz_emits_one_tick_per_frame():
    """At 60 Hz render, every frame produces exactly 1 sim tick."""
    accumulator = 0.0
    total_ticks = 0
    for _ in range(600):  # 10 seconds at 60 Hz
        accumulator, n = step_accumulator(
            accumulator, 1.0 / 60.0, TICK_DT, MAX_FRAME_DT
        )
        total_ticks += n
    assert total_ticks == 600
    assert accumulator < TICK_DT  # never grows unbounded


def test_120hz_render_emits_60hz_sim():
    """At 120 Hz render, sim still produces 60 ticks per real second."""
    accumulator = 0.0
    total_ticks = 0
    for _ in range(1200):  # 10 seconds at 120 Hz
        accumulator, n = step_accumulator(
            accumulator, 1.0 / 120.0, TICK_DT, MAX_FRAME_DT
        )
        total_ticks += n
    # Floating-point drift can give 599 or 600; both are acceptable.
    assert 599 <= total_ticks <= 600


def test_variable_deltas_emit_correct_tick_count():
    """Tick count matches floor(sum(deltas) / TICK_DT) within +-1."""
    deltas = [1.0 / 60.0, 1.0 / 120.0, 1.0 / 30.0, 1.0 / 240.0] * 100
    accumulator = 0.0
    total_ticks = 0
    for d in deltas:
        accumulator, n = step_accumulator(
            accumulator, d, TICK_DT, MAX_FRAME_DT
        )
        total_ticks += n
    expected = int(sum(deltas) / TICK_DT)
    assert abs(total_ticks - expected) <= 1


def test_stall_clamped_to_cap():
    """A 1-second stall produces at most ~15 ticks, not 60."""
    accumulator, n = step_accumulator(
        0.0, 1.0, TICK_DT, MAX_FRAME_DT
    )
    # MAX_FRAME_DT = 0.25; 0.25 / (1/60) = 15 exact ticks.
    # Floating-point residual drift can land on 14 or 15.
    assert n <= 15
    assert n >= 14
    # Accumulator should hold the leftover (< 1 tick).
    assert accumulator < TICK_DT


def test_pause_zero_dt_no_ticks():
    """When frame_dt is 0 (simulating paused frames), no ticks emit."""
    accumulator = 0.0
    total_ticks = 0
    for _ in range(600):  # 10 seconds of paused frames
        accumulator, n = step_accumulator(
            accumulator, 0.0, TICK_DT, MAX_FRAME_DT
        )
        total_ticks += n
    assert total_ticks == 0
    assert accumulator == 0.0


def test_negative_dt_treated_as_zero():
    """Defensive: a clock that steps backward (shouldn't happen with
    monotonic but be safe) does not produce ticks or shrink the
    accumulator below zero."""
    accumulator, n = step_accumulator(
        0.0, -0.1, TICK_DT, MAX_FRAME_DT
    )
    assert n == 0
    assert accumulator == 0.0
