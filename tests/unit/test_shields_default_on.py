"""A freshly-spawned ship's shield generator is powered ON.

Regression test for the "initial volleys skip shields" bug: every ship
spawned with GREEN alert (the default) had its generator reading IsOn()==0,
so ``combat.apply_hit`` routed 100% of the first volley to the hull while
the HUD drew a full shield bar from the seeded face charge.

BC's ``PoweredSubsystem`` constructor sets ``m_isOn = 1``
(stbc_reference ``spec/PoweredSubsystem.md`` §"constructor"), and its damage
path never consults the flag at all — ``ShipClass::TestHit`` gates on the
facing's charge fraction (``> 0.1``). An unpowered shield reaches that state
by having its charge drained on the 0.5 s tick, not by a boolean check.

``PoweredSubsystem`` itself keeps its default-off (cold phasers/torpedoes at
spawn are live-verified faithful); only ``ShieldSubsystem`` overrides it, the
same way SensorSubsystem / ImpulseEngineSubsystem / WarpEngineSubsystem /
RepairSubsystem already do.

Explicitly dropping shields still works and is covered by
tests/unit/test_combat_skips_powered_down_shields.py.
"""
from engine.appc.math import TGPoint3
from engine.appc.combat import apply_hit
from engine.appc.ships import ShipClass, ShipClass_Create
from engine.appc.subsystems import (HullSubsystem, PoweredSubsystem,
                                    ShieldSubsystem)


def _spawned_ship(hull_max=2000.0, face_max=1000.0):
    """A ship as ``loadspacehelper`` leaves it: faces seeded to max by
    SetMaxShields, alert level never touched."""
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


def test_fresh_shield_generator_is_powered_on():
    """The generator reads IsOn() without anything having raised alert."""
    assert ShieldSubsystem("Shield Generator").IsOn() == 1


def test_powered_subsystem_base_still_defaults_off():
    """The override is on ShieldSubsystem alone — flipping the base class
    would power weapons up at spawn, which is NOT faithful."""
    assert PoweredSubsystem("Phaser Bank").IsOn() == 0


def test_freshly_spawned_ship_absorbs_its_first_volley():
    """The reported bug: a ship that has never been sent to alert still
    absorbs the opening shot on its shields, not its hull."""
    ship = _spawned_ship(hull_max=2000.0, face_max=1000.0)
    assert ship.GetAlertLevel() == ShipClass.GREEN_ALERT

    apply_hit(ship, 500.0, TGPoint3(0, 10, 0), source=None)

    assert ship.GetShields().GetCurrentShields(0) == 500.0
    assert ship.GetHull().GetCondition() == 2000.0


def test_hud_shield_bar_agrees_with_absorption_on_a_fresh_ship():
    """The bug's tell was a full bar that absorbed nothing: the HUD reads
    charge only (target_list_view._query_shield_percentage) and never
    consulted IsOn. Bar and combat must now agree."""
    from engine.ui.target_list_view import _query_shield_percentage
    ship = _spawned_ship(hull_max=2000.0, face_max=1000.0)

    assert _query_shield_percentage(ship) == 100

    apply_hit(ship, 6000.0, TGPoint3(0, 10, 0), source=None)

    assert _query_shield_percentage(ship) < 100
    assert ship.GetHull().GetCondition() < 2000.0
