"""Unit tests: ships with no AI/helm setpoints drift on a scripted
SetVelocity / SetAngularVelocity, mirroring rocks.motion.step.

The SDK calls SetVelocity/SetAngularVelocity with no AI and no setpoints on
these objects (ShipScriptActions.PushObject's launched probe, E1M2's
falling Haven station) -- the shim just stores the value, so without this
integration step they never move. Exception: the current player under
manual control has no setpoints either, but host_loop's _PlayerControl
drives and moves it directly -- this integrator must not also move it.

NOT fixed by this module: E8M2's spinning Matan (and E7M2's JonKa, E8M1's
Galor, E2M1's Karoon) already have an AI installed when their script fires
a bare SetVelocity/SetAngularVelocity, so they take the ramp path instead
of this drift path and their scripted velocity is still silently ignored
-- see engine/appc/ship_motion.py's module docstring "known gap" paragraph.
"""
import math

import pytest

import App
from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc.objects import PhysicsObjectClass
from engine.appc.ship_motion import tick_all_ship_motion
from engine.appc.ships import ShipClass
from engine.core.game import Game, _set_current_game


def setup_function(_):
    _set_current_game(None)


def teardown_function(_):
    _set_current_game(None)


def _place(ship, name="t"):
    """Drop a ship into a fresh SetClass so iter_ships sees it."""
    pSet = App.SetClass_Create()
    pSet.SetName(name)
    pSet.AddObjectToSet(ship, name + "_obj")
    App.g_kSetManager._sets[name] = pSet


def setup_module(_):
    App.g_kSetManager._sets.clear()


def teardown_module(_):
    App.g_kSetManager._sets.clear()


def test_setpointless_ship_drifts_on_scripted_velocity():
    """A non-player ShipClass with no AI and no setpoints, given a bare
    SetVelocity (the probe-launch / E1M2 station pattern -- NOT the Matan
    pattern, which already has an AI with setpoints; see the module
    docstring), moves by v * dt each tick."""
    ship = ShipClass()
    _place(ship)
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    ship.SetVelocity(TGPoint3(0.0, 10.0, 0.0))
    for _ in range(60):
        tick_all_ship_motion(1.0 / 60.0)
    p = ship.GetTranslate()
    assert p.y == pytest.approx(10.0)
    assert p.x == 0.0
    assert p.z == 0.0


def test_setpointless_ship_spins_on_scripted_angular_velocity_model_space():
    """SetAngularVelocity(..., DIRECTION_MODEL_SPACE) on a setpoint-less
    ship rotates it about its own body axis -- the convention E8M2 uses
    for the disabled Matan, though Matan itself has an AI with setpoints
    and so never reaches this drift path (module docstring "known gap")."""
    ship = ShipClass()
    _place(ship)
    # Pitch the ship 90 deg about world X, so body-Z points along world -Y.
    R = TGMatrix3(); R.MakeRotation(math.pi / 2, TGPoint3(1, 0, 0))
    ship.SetMatrixRotation(R)
    ship.SetAngularVelocity(TGPoint3(0.0, 0.0, 1.0),
                            PhysicsObjectClass.DIRECTION_MODEL_SPACE)
    y0 = R.GetCol(1)
    tick_all_ship_motion(0.5)
    # Spinning about BODY Z leaves body Z (the column) unchanged...
    z = ship.GetWorldRotation().GetCol(2)
    assert abs(z.y - R.GetCol(2).y) < 1e-6
    assert abs(z.z - R.GetCol(2).z) < 1e-6
    # ...but it must actually have rotated: body Y has moved.
    y1 = ship.GetWorldRotation().GetCol(1)
    assert abs(y1.x - y0.x) > 1e-3 or abs(y1.y - y0.y) > 1e-3 or abs(y1.z - y0.z) > 1e-3


def test_static_setpointless_ship_never_moves():
    """SetStatic + a scripted velocity must never move the ship (the
    existing immobile gate must still run first)."""
    ship = ShipClass()
    _place(ship)
    ship.SetStatic(1)
    ship.SetVelocity(TGPoint3(5.0, 0.0, 0.0))
    tick_all_ship_motion(1.0)
    assert ship.GetTranslate().x == 0.0


def test_current_player_with_no_setpoints_is_not_moved():
    """The manually-flown player has no setpoints either, but host_loop's
    _PlayerControl drives it directly -- tick_all_ship_motion must not also
    integrate a scripted/stale velocity on it (double-move)."""
    g = Game()
    _set_current_game(g)
    player = ShipClass()
    _place(player, name="player_set")
    App.Game_SetCurrentPlayer(player)
    player.SetTranslateXYZ(0.0, 0.0, 0.0)
    player.SetVelocity(TGPoint3(0.0, 10.0, 0.0))
    tick_all_ship_motion(1.0)
    p = player.GetTranslate()
    assert (p.x, p.y, p.z) == (0.0, 0.0, 0.0)


def test_ship_with_setpoints_is_unaffected_by_drift_path():
    """A ship that DOES have setpoints keeps flying the normal ramp path,
    not the drift path (sanity: the drift branch must not shadow it)."""
    from engine.appc.math import TGPoint3_GetModelForward
    ship = ShipClass()
    _place(ship)
    ship.SetImpulse(50.0, TGPoint3_GetModelForward(),
                    App.PhysicsObjectClass.DIRECTION_MODEL_SPACE)
    ship.SetTargetAngularVelocityDirect(TGPoint3(0.0, 0.0, 0.0))
    dt = 1.0 / 60.0
    tick_all_ship_motion(dt)
    assert ship._current_speed == 50.0
    p = ship.GetTranslate()
    assert abs(p.y - 50.0 * dt) < 1e-9
