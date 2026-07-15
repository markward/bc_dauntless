"""TorpedoTube.Fire fire gates (Task 7, audited): aim-point resolve, the
+/-30 degree square cone, the ship-wide 0.5s fire stagger, and the
ET_WEAPON_FIRED / ET_WEAPON_FIRE_FAILED / ET_TORPEDO_AMMO_CONSUMED event
bookkeeping.

Closes the transitional state left by Task 5/6: one tap used to fire EVERY
ready tube in the working group in the same tick (aft tubes launching
backward at a forward target).  The stagger throttles same-tick multi-fire
to one launch; the cone rejects tubes that can't physically point at the
resolved aim point.
"""
from unittest.mock import patch

import pytest

import App
from engine.appc import events, projectiles
from engine.appc.math import TGPoint3
from tests.helpers.torpedo_fixtures import (
    LiveTarget,
    advance_game_clock_by,
    advance_game_clock_to,
    make_ship_with_two_tubes,
    make_target_at,
    pos_at_bearing_deg,
)


@pytest.fixture(autouse=True)
def _clean_clock_and_registry():
    App.g_kTimerManager._time = 0.0
    projectiles._active.clear()
    yield
    App.g_kTimerManager._time = 0.0
    projectiles._active.clear()


@pytest.fixture
def recorded_events():
    """Collect the EVENT TYPE (int) of every torpedo/weapon-fire event the
    engine posts, in arrival order.  Mirrors tests/unit/test_torpedo_fired_
    event.py's `captured` fixture, but stores the type id directly since
    these tests only care about ordering/membership, not source/dest."""
    seen = []
    names = (
        "ET_TORPEDO_FIRED", "ET_TORPEDO_RELOAD",
        "ET_WEAPON_FIRED", "ET_WEAPON_FIRE_FAILED",
        "ET_TORPEDO_AMMO_CONSUMED",
    )
    globals()["_collect"] = lambda _obj, evt: seen.append(evt.GetEventType())
    for name in names:
        App.g_kEventManager.AddBroadcastPythonFuncHandler(
            getattr(App, name), object(), __name__ + "._collect")
    yield seen
    for name in names:
        App.g_kEventManager._broadcast_handlers.pop(getattr(App, name), None)


def _patched_sound():
    return patch("engine.audio.tg_sound.TGSoundManager.instance")


# ── Ship-wide 0.5s stagger ───────────────────────────────────────────────────

def test_ship_wide_stagger_blocks_second_tube_within_half_second():
    ship, sys_, (t1, t2) = make_ship_with_two_tubes()
    advance_game_clock_to(100.0)
    with _patched_sound():
        t1.Fire(None, None)
    assert t1.GetNumReady() == t1.GetMaxReady() - 1
    with _patched_sound():
        t2.Fire(None, None)                       # 0.0s later — staggered out
    assert t2.GetNumReady() == t2.GetMaxReady()
    advance_game_clock_to(100.6)
    with _patched_sound():
        t2.Fire(None, None)
    assert t2.GetNumReady() == t2.GetMaxReady() - 1


def test_stagger_boundary_at_half_a_second_exclusive():
    """CanFire's gate is `<= 0.5` to FAIL, so exactly +0.5s still blocks and
    the first instant past 0.5s passes."""
    ship, sys_, (t1, t2) = make_ship_with_two_tubes()
    advance_game_clock_to(100.0)
    with _patched_sound():
        t1.Fire(None, None)
    advance_game_clock_to(100.5)
    with _patched_sound():
        t2.Fire(None, None)
    assert t2.GetNumReady() == t2.GetMaxReady(), "exactly 0.5s must still block"
    advance_game_clock_by(0.001)
    with _patched_sound():
        t2.Fire(None, None)
    assert t2.GetNumReady() == t2.GetMaxReady() - 1


def test_skew_fire_exempt_from_stagger():
    ship, sys_, (t1, t2) = make_ship_with_two_tubes()
    t2.SetSkewFire(1)
    advance_game_clock_to(100.0)
    with _patched_sound():
        t1.Fire(None, None)
        t2.Fire(None, None)                       # same instant, skew — allowed
    assert t2.GetNumReady() == t2.GetMaxReady() - 1


def test_fresh_system_first_shot_passes_stagger():
    """TorpedoSystem._last_system_fire_time inits to -1000.0 so a fresh
    system's first shot always satisfies the 0.5s gate."""
    ship, sys_, (t1, _) = make_ship_with_two_tubes()
    assert sys_._last_system_fire_time == -1000.0
    advance_game_clock_to(0.0)
    with _patched_sound():
        assert t1.Fire(None, None) is True


# ── +/-30 degree cone ────────────────────────────────────────────────────────

def test_cone_rejects_target_astern_and_posts_fire_failed(recorded_events):
    ship, sys_, (t1, _) = make_ship_with_two_tubes()   # tubes face +Y
    target = make_target_at(TGPoint3(0.0, -500.0, 0.0))
    with _patched_sound():
        t1.Fire(target, None)
    assert t1.GetNumReady() == t1.GetMaxReady()        # no launch
    assert events.ET_WEAPON_FIRE_FAILED in recorded_events


def test_cone_boundary_at_30_degrees():
    ship, sys_, (t1, _) = make_ship_with_two_tubes()
    inside = make_target_at(pos_at_bearing_deg(29.0))
    outside = make_target_at(pos_at_bearing_deg(31.0))
    with _patched_sound():
        t1.Fire(inside, None)
    assert t1.GetNumReady() == t1.GetMaxReady() - 1
    advance_game_clock_by(1.0)
    with _patched_sound():
        t1.Fire(outside, None)
    assert t1.GetNumReady() == t1.GetMaxReady() - 1  # unchanged — cone rejected it


def test_cone_accepts_target_dead_ahead():
    ship, sys_, (t1, _) = make_ship_with_two_tubes()
    target = make_target_at(TGPoint3(0.0, 500.0, 0.0))
    with _patched_sound():
        assert t1.Fire(target, None) is True
    assert t1.GetNumReady() == t1.GetMaxReady() - 1


def test_dumb_path_skips_cone_entirely():
    """Fire(target=None) is the dumbfire path — no aim resolve, no cone.  An
    aft-facing tube (which would fail the cone against ANY forward target)
    must still launch on a dumb call."""
    ship, sys_, (t1, _) = make_ship_with_two_tubes()
    with _patched_sound():
        assert t1.Fire(None, None) is True
    assert t1.GetNumReady() == t1.GetMaxReady() - 1


# ── Event bookkeeping ────────────────────────────────────────────────────────

def test_fire_posts_torpedo_fired_then_weapon_fired(recorded_events):
    ship, sys_, (t1, _) = make_ship_with_two_tubes()
    with _patched_sound():
        t1.Fire(None, None)
    ids = [e for e in recorded_events
           if e in (events.ET_TORPEDO_FIRED, events.ET_WEAPON_FIRED)]
    assert ids == [events.ET_TORPEDO_FIRED, events.ET_WEAPON_FIRED]


def test_ammo_consumed_posted_only_for_the_player_ship(recorded_events):
    from engine.core.game import Game, Game_SetCurrentPlayer, _set_current_game

    ship, sys_, (t1, _) = make_ship_with_two_tubes()
    _set_current_game(Game())
    Game_SetCurrentPlayer(ship)
    with _patched_sound():
        t1.Fire(None, None)
    assert events.ET_TORPEDO_AMMO_CONSUMED in recorded_events
    _set_current_game(None)


def test_ammo_consumed_not_posted_for_a_non_player_ship(recorded_events):
    from engine.core.game import Game, Game_SetCurrentPlayer, _set_current_game

    ship, sys_, (t1, _) = make_ship_with_two_tubes()
    other = LiveTarget(0.0, 0.0, 0.0)
    _set_current_game(Game())
    Game_SetCurrentPlayer(other)
    with _patched_sound():
        t1.Fire(None, None)
    assert events.ET_TORPEDO_AMMO_CONSUMED not in recorded_events
    _set_current_game(None)


def test_gated_out_fire_returns_false_and_posts_nothing(recorded_events):
    """CanFire failing (e.g. an empty tube) must not post ANY of the Task 7
    events — the tube never even attempted a shot."""
    ship, sys_, (t1, _) = make_ship_with_two_tubes()
    t1.SetNumReady(0)
    with _patched_sound():
        assert t1.Fire(None, None) is False
    assert recorded_events == []


# ── Module helpers, exercised directly ──────────────────────────────────────

def test_resolve_aim_point_none_for_dead_target():
    from engine.appc.weapon_subsystems import _resolve_torpedo_aim_point

    ship, sys_, (t1, _) = make_ship_with_two_tubes()

    class _Dead:
        def GetWorldLocation(self): return TGPoint3(0, 100, 0)
        def IsDead(self): return 1

    assert _resolve_torpedo_aim_point(t1, _Dead()) is None


def test_resolve_aim_point_none_for_none_target():
    from engine.appc.weapon_subsystems import _resolve_torpedo_aim_point

    ship, sys_, (t1, _) = make_ship_with_two_tubes()
    assert _resolve_torpedo_aim_point(t1, None) is None


def test_in_torpedo_cone_rejects_zero_length_aim_vector():
    from engine.appc.weapon_subsystems import _in_torpedo_cone

    ship, sys_, (t1, _) = make_ship_with_two_tubes()
    mount = t1._emitter_world_position()
    assert _in_torpedo_cone(t1, ship, mount) is False
