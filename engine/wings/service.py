"""Wing service: the switch, arming with phase stagger, the 1 Hz hook and
reset (spec 2026-11-09-wing-leaders-phase-a-design.md §6).

Pause: GameLoop.tick runs once per GAME tick and the host runs no game ticks
while paused (engine/host_loop.py `_whole_tick`, per `_frame_game_dt`), so
there is deliberately no pause check here.
"""
import os

from engine.wings import brain, decisions, dials, roster

_armed: list = []
_player_wing_id: str | None = None
_EPS = 1e-9


def enabled() -> bool:
    """The global switch: DAUNTLESS_WINGS=0 turns wings off everywhere (perf
    A/B, tests). Quick Battle also reads its setup screen's per-battle
    "Wing commanders" switch (plan.wings, engine/quickbattle/wings_qb.py)."""
    return os.environ.get("DAUNTLESS_WINGS") != "0"


def is_commander(name) -> bool:
    wing = roster.wing_of(name)
    return (wing is not None and not wing.leaderless
            and wing.commander == name)


def set_player_wing(wing_id) -> None:
    """The wing built from the player's own group (it is AI-led; the player
    is no member). None when the player's group has no wing."""
    global _player_wing_id
    _player_wing_id = wing_id


def player_focus():
    """The player's wing's current main target (its primary), or None when
    there is no such wing, it is leaderless or its command is away."""
    if _player_wing_id is None:
        return None
    wing = next((w for w in roster.wings() if w.wing_id == _player_wing_id),
                None)
    if wing is None or wing.leaderless or wing.away:
        return None
    return wing.primary


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
    """Run every armed wing whose period has passed. Consumers check
    enabled() before arming; DAUNTLESS_WINGS=0 also stops the brain."""
    if not _armed or os.environ.get("DAUNTLESS_WINGS") == "0":
        return
    period = dials.get("brain_period_s")
    for wing in list(_armed):
        wing.accum_s += dt
        if wing.accum_s + _EPS >= period:
            wing.accum_s -= period
            brain.tick_safely(wing)


def reset() -> None:
    set_player_wing(None)
    roster.reset()
    _armed.clear()
    brain.reset_cache()


def reset_all() -> None:
    """Tests only: also drops mod-registered decisions and dial changes."""
    reset()
    decisions.reset_registry()
    dials.reset()
