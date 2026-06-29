"""combat.apply_hit must bypass shield absorption when the shield
generator is not powered (IsOn() == 0). At green alert shields are down
and damage flows straight to the picked subsystem / hull bleed; the
shield-bubble flash and absorbed_shields readout stay at zero.

Companion to test_apply_hit_routing.py — those fakes don't implement
IsOn() so they default to on; this file uses a real ShieldSubsystem so
the IsOn gate is exercised end-to-end.
"""
import sys
import types

from engine.appc.math import TGPoint3
from engine.appc.combat import apply_hit
from engine.appc.events import ET_WEAPON_HIT
from engine.appc.ships import ShipClass, ShipClass_Create
from engine.appc.subsystems import HullSubsystem, ShieldSubsystem


def _ship_with_full_shields_and_hull(hull_max=2000.0, face_max=1000.0):
    ship = ShipClass_Create("Target")
    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(hull_max)
    ship._hull = hull
    ss = ShieldSubsystem("Shield Generator")
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        ss.SetMaxShields(f, face_max)
    ship.SetShieldSubsystem(ss)
    ship._radius = 20.0
    return ship


def test_green_alert_shields_do_not_absorb_damage():
    """Default alert is GREEN → shields powered down → 500 damage hits
    the hull directly. SetMaxShields seeds the faces to max on load
    (mirrors loadspacehelper); IsOn=False keeps combat from touching
    them, so they stay at the seeded value."""
    ship = _ship_with_full_shields_and_hull(hull_max=2000.0, face_max=1000.0)
    assert ship.GetAlertLevel() == ShipClass.GREEN_ALERT
    apply_hit(ship, 500.0, TGPoint3(0, 10, 0), source=None)
    # Shields untouched (generator never powered up).
    assert ship.GetShields().GetCurrentShields(0) == 1000.0
    # Hull took the full damage.
    assert ship.GetHull().GetCondition() == 1500.0


def test_explicit_green_after_red_drains_and_skips_absorption():
    """RED→GREEN transition drains faces to 0 and powers the generator
    down. Subsequent damage flows straight to hull."""
    ship = _ship_with_full_shields_and_hull(hull_max=2000.0, face_max=1000.0)
    ship.SetAlertLevel(ShipClass.RED_ALERT)
    ship.SetAlertLevel(ShipClass.GREEN_ALERT)
    assert ship.GetShields().GetCurrentShields(0) == 0.0
    apply_hit(ship, 500.0, TGPoint3(0, 10, 0), source=None)
    assert ship.GetHull().GetCondition() == 1500.0


def test_yellow_alert_shields_absorb_damage():
    """YELLOW → shields powered → 500 damage absorbed by front face,
    hull untouched."""
    ship = _ship_with_full_shields_and_hull(hull_max=2000.0, face_max=1000.0)
    ship.SetAlertLevel(ShipClass.YELLOW_ALERT)
    apply_hit(ship, 500.0, TGPoint3(0, 10, 0), source=None)
    assert ship.GetShields().GetCurrentShields(0) == 500.0
    assert ship.GetHull().GetCondition() == 2000.0


def test_red_alert_shields_absorb_damage():
    """RED → shields powered → same absorption as YELLOW."""
    ship = _ship_with_full_shields_and_hull(hull_max=2000.0, face_max=1000.0)
    ship.SetAlertLevel(ShipClass.RED_ALERT)
    apply_hit(ship, 500.0, TGPoint3(0, 10, 0), source=None)
    assert ship.GetShields().GetCurrentShields(0) == 500.0
    assert ship.GetHull().GetCondition() == 2000.0


def test_dropping_to_green_mid_combat_stops_absorbing():
    """Once shields drop, subsequent hits bypass them — even if the
    faces had charge a moment earlier."""
    ship = _ship_with_full_shields_and_hull(hull_max=2000.0, face_max=1000.0)
    ship.SetAlertLevel(ShipClass.RED_ALERT)
    apply_hit(ship, 200.0, TGPoint3(0, 10, 0), source=None)
    assert ship.GetShields().GetCurrentShields(0) == 800.0

    ship.SetAlertLevel(ShipClass.GREEN_ALERT)
    # Shields drained on the green transition.
    assert ship.GetShields().GetCurrentShields(0) == 0.0
    apply_hit(ship, 500.0, TGPoint3(0, 10, 0), source=None)
    # Hull takes the second hit.
    assert ship.GetHull().GetCondition() == 1500.0


# ── WeaponHitEvent.IsHullHit reflects the shield-vs-hull branch ──────────────
# ConditionAttacked / ConditionAttackedBy read pEvent.IsHullHit() to decide
# whether a hit reached the hull (1) or was absorbed by shields (0).

def _capture_weapon_hit_events():
    """Install a broadcast handler that records every WeaponHitEvent;
    returns (events_list, cleanup_callable)."""
    received = []

    def handler(_obj, evt):
        received.append(evt)

    mod = types.ModuleType("_test_is_hull_hit_capture")
    mod.handler = handler
    sys.modules["_test_is_hull_hit_capture"] = mod
    import App
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        ET_WEAPON_HIT, None, "_test_is_hull_hit_capture.handler")

    def cleanup():
        App.g_kEventManager.RemoveBroadcastHandler(
            ET_WEAPON_HIT, None, "_test_is_hull_hit_capture.handler")
        del sys.modules["_test_is_hull_hit_capture"]

    return received, cleanup


def test_event_is_hull_hit_zero_when_shields_absorb():
    """Full front shield absorbs the hit → emitted event IsHullHit()==0."""
    ship = _ship_with_full_shields_and_hull(hull_max=2000.0, face_max=1000.0)
    ship.SetAlertLevel(ShipClass.RED_ALERT)
    received, cleanup = _capture_weapon_hit_events()
    try:
        apply_hit(ship, 500.0, TGPoint3(0, 10, 0), source=None)
        assert len(received) == 1
        assert received[0].IsHullHit() == 0
    finally:
        cleanup()


def test_event_is_hull_hit_one_when_face_down():
    """Front face at zero → damage reaches the hull → IsHullHit()==1."""
    ship = _ship_with_full_shields_and_hull(hull_max=2000.0, face_max=1000.0)
    # Green alert keeps the generator powered down → shields never absorb.
    assert ship.GetAlertLevel() == ShipClass.GREEN_ALERT
    received, cleanup = _capture_weapon_hit_events()
    try:
        apply_hit(ship, 500.0, TGPoint3(0, 10, 0), source=None)
        assert len(received) == 1
        assert received[0].IsHullHit() == 1
    finally:
        cleanup()
