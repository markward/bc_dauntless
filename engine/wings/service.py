"""Wing service: the switch, arming with phase stagger, the 1 Hz hook and
reset (spec 2026-11-09-wing-leaders-phase-a-design.md §6).

Pause: GameLoop.tick runs once per GAME tick and the host runs no game ticks
while paused (engine/host_loop.py `_whole_tick`, per `_frame_game_dt`), so
there is deliberately no pause check here.
"""
import os

from engine.wings import brain, decisions, dials, roster

_dev_enabled = True
_show_markers = False
_armed: list = []
_EPS = 1e-9


def enabled() -> bool:
    return os.environ.get("DAUNTLESS_WINGS") != "0" and _dev_enabled


def set_dev_enabled(on) -> None:
    global _dev_enabled
    _dev_enabled = bool(on)


def set_show_markers(on) -> None:
    global _show_markers
    _show_markers = bool(on)


def show_markers() -> bool:
    return _show_markers


def is_commander(name) -> bool:
    wing = roster.wing_of(name)
    return (wing is not None and not wing.leaderless
            and wing.commander == name)


def reset_dev() -> None:
    set_dev_enabled(True)


def arm(wing) -> None:
    """Build the wing's chain and stagger every armed wing's brain tick
    across the period so they do not all land on one frame."""
    brain.arm_chain(wing)
    if wing not in _armed:
        _armed.append(wing)
    period = dials.get("brain_period_s")
    n = len(_armed)
    for i, w in enumerate(_armed):
        # The stagger is a head start on the accumulator: wing i first runs
        # at (1 - i/n) periods, then every period.
        w.phase_s = i / n * period
        w.accum_s = w.phase_s
    brain.log("%s arm" % wing.wing_id)


def tick(dt: float) -> None:
    """Run every armed wing whose period has passed. The dev switch is NOT
    read here: it is read at arm time (consumers check enabled() before
    arming), so toggling it mid-battle leaves the battle as armed. Only
    DAUNTLESS_WINGS=0 stops the brain."""
    if not _armed or os.environ.get("DAUNTLESS_WINGS") == "0":
        return
    period = dials.get("brain_period_s")
    for wing in list(_armed):
        wing.accum_s += dt
        if wing.accum_s + _EPS >= period:
            wing.accum_s -= period
            brain.tick_safely(wing)


def reset() -> None:
    roster.reset()
    _armed.clear()
    brain.reset_cache()


def reset_all() -> None:
    """Tests only: also drops mod-registered decisions, dial changes and
    the dev switch."""
    reset()
    reset_dev()
    set_show_markers(False)
    decisions.reset_registry()
    dials.reset()
