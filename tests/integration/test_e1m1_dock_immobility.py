"""Regression: E1M1 spacedock must hold station at bridge-load.

Reproduces the reported bug geometry: the player spawns at "DryDock Start",
co-located with the first Dry Dock (collisions between them disabled by the
mission), while nearby static docks must not drift/rotate even when a moving
object touches them. See docs/superpowers/specs/2026-07-07-static-object-
immobility-design.md.
"""
import App
import pytest
from engine.appc.math import TGPoint3
from engine.appc.objects import PhysicsObjectClass
from engine.appc.ships import ShipClass
from engine.appc.collisions import resolve_collisions
from engine.appc.ship_motion import _step_ship_motion


def _reset_app_state():
    App.g_kSetManager._sets.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def _pos(o):
    p = o.GetTranslate()
    return (p.x, p.y, p.z)


def _rot_cols(o):
    R = o.GetWorldRotation()
    return [(R.GetCol(i).x, R.GetCol(i).y, R.GetCol(i).z) for i in range(3)]


def test_static_dock_does_not_move_under_setpoint_or_collision():
    # A static drydock carrying a Stay-style zero setpoint, plus a moving
    # intruder overlapping it.
    dock = ShipClass()
    dock.SetStatic(True)
    dock.SetStationary(1)
    dock.SetTranslateXYZ(0.0, 0.0, 0.0)
    dock.SetRadius(3.0)
    dock.SetMass(300.0)
    dock.SetSpeed(0.0, TGPoint3(0.0, 1.0, 0.0),
                  PhysicsObjectClass.DIRECTION_MODEL_SPACE)
    dock.SetTargetAngularVelocityDirect(TGPoint3(0.0, 0.0, 0.0))

    intruder = ShipClass()
    # Collision boundary is 0.8*(rA+rB) = 0.8*(3+2) = 4.0; place it at 3.0 so
    # dist (3.0) < boundary (4.0) and the pair genuinely overlaps.
    intruder.SetTranslateXYZ(3.0, 0.0, 0.0)
    intruder.SetRadius(2.0)
    intruder.SetMass(100.0)
    intruder.SetVelocity(TGPoint3(-20.0, 0.0, 0.0))  # approaching

    dock_pos, dock_rot = _pos(dock), _rot_cols(dock)

    _step_ship_motion(dock, 1.0)         # integrator must not move it
    resolve_collisions([dock, intruder]) # collision must not move it

    assert _pos(dock) == pytest.approx(dock_pos)
    assert _rot_cols(dock) == pytest.approx(dock_rot)
    # The mover, by contrast, is affected (de-penetrated away from the anchor).
    assert intruder.__dict__.get("_collision_velocity") is not None


def test_docked_player_is_not_shoved_out_of_its_drydock():
    # Player co-located with the first Dry Dock (both at "DryDock Start"),
    # with collisions between them disabled — the mission's setup.
    player = ShipClass()
    player.SetTranslateXYZ(0.0, 0.0, 0.0)
    player.SetRadius(2.0)
    player.SetMass(100.0)
    player.SetVelocity(TGPoint3(0.5, 0.0, 0.0))  # tiny drift, as at undock start

    drydock = ShipClass()
    drydock.SetStatic(True)
    drydock.SetTranslateXYZ(0.2, 0.0, 0.0)  # essentially co-located, overlapping
    drydock.SetRadius(3.0)
    drydock.SetMass(300.0)

    drydock.EnableCollisionsWith(player, 0)  # mission: disable while docked

    player_pos = _pos(player)
    hits = resolve_collisions([player, drydock])

    assert hits == []                         # pair skipped
    assert _pos(player) == pytest.approx(player_pos)   # not de-penetrated out
    assert player.__dict__.get("_collision_velocity") is None
    assert _pos(drydock) == pytest.approx((0.2, 0.0, 0.0))


def test_reenabling_collisions_after_undock_restores_the_bump():
    # After the undock cutscene the mission calls EnableCollisionsWith(player, 1);
    # once clear, the pair collides normally again (proves re-enable works).
    player = ShipClass()
    player.SetTranslateXYZ(0.0, 0.0, 0.0)
    player.SetRadius(2.0)
    player.SetMass(100.0)
    player.SetVelocity(TGPoint3(10.0, 0.0, 0.0))  # moving toward the dock

    drydock = ShipClass()   # NOT static here: we assert the pair is live again
    drydock.SetTranslateXYZ(1.5, 0.0, 0.0)
    drydock.SetRadius(2.0)
    drydock.SetMass(300.0)

    drydock.EnableCollisionsWith(player, 0)
    drydock.EnableCollisionsWith(player, 1)   # re-enabled

    hits = resolve_collisions([player, drydock])
    assert hits != []                          # collides again
