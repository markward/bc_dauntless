"""Regression guard for the camera-spring dt wiring.

The exterior-view camera must be fed the wall-clock frame delta
(`_player_dt`), not the fixed sim tick (`TICK_DT`). Feeding a fixed dt
to the exponential springs makes them lurch at non-60 Hz refresh rates
and the player ship visibly judders (the bug this branch fixed).

The host loop is a single monolithic while-loop that is impractical to
unit-test in isolation, so this is a source-level guard: the
`_compute_camera(...)` call that drives the exterior view must pass
`dt=_player_dt`. If someone reverts it to `dt=TICK_DT`, this fails.
"""

import inspect
import re

from engine import host_loop


def _run_source() -> str:
    return inspect.getsource(host_loop.run)


def test_compute_camera_fed_wall_clock_dt():
    src = _run_source()
    # The exterior-view branch calls _compute_camera(...) spanning
    # multiple lines; collapse whitespace to match the dt argument.
    collapsed = re.sub(r"\s+", " ", src)
    assert "_compute_camera( view_mode, director, player=player, dt=_player_dt)" in collapsed, (
        "exterior-view _compute_camera must be fed dt=_player_dt "
        "(wall-clock frame delta), not a fixed TICK_DT"
    )


def test_compute_camera_not_fed_fixed_tick_dt():
    src = _run_source()
    collapsed = re.sub(r"\s+", " ", src)
    assert "_compute_camera( view_mode, director, player=player, dt=TICK_DT)" not in collapsed, (
        "regression: _compute_camera fed fixed TICK_DT — springs will "
        "lurch at non-60Hz refresh rates"
    )
