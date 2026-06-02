"""Fixed-timestep accumulator helper.

Decouples simulation cadence from render frame rate using Glenn
Fiedler's "Fix Your Timestep" pattern. Pure function: no engine
dependencies, no side effects, trivially testable.

Used by `engine.host_loop.run()` once per render frame.
"""


def step_accumulator(accumulator, frame_dt, tick_dt, max_frame_dt):
    """Advance the accumulator by one render frame's wall-clock delta.

    Returns (new_accumulator, n_ticks). The caller is responsible for
    invoking the sim-tick callable exactly n_ticks times.

    - frame_dt is clamped to [0, max_frame_dt]. The lower bound guards
      against a backward-stepping clock (shouldn't happen with
      monotonic() but defensive). The upper bound is the
      spiral-of-death cap: after a stalled render frame, we accept
      that some game time is lost rather than chain unbounded ticks
      into the next frame.
    - Steady-state sim rate is 1 / tick_dt regardless of render rate.
    """
    if frame_dt < 0.0:
        frame_dt = 0.0
    elif frame_dt > max_frame_dt:
        frame_dt = max_frame_dt
    accumulator += frame_dt
    n = 0
    while accumulator >= tick_dt:
        n += 1
        accumulator -= tick_dt
    return accumulator, n
