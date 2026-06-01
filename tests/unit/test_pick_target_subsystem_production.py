"""Production-path tests for pick_target_subsystem.

These build real ShipClass/WeaponSystem/PhaserBank/Subsystem instances
(no _FakeShip stubs) so they exercise the body-frame transform, the
GetSubsystems + _children walk, and the per-subsystem 2x-radius gate.
The legacy _FakeShip-based tests live in test_pick_target_subsystem.py
and verify the fallback branch.
"""
import math

from engine.appc.combat import pick_target_subsystem
from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc.ships import ShipClass
from engine.appc.subsystems import (
    HullSubsystem, PhaserBank, PhaserSystem, SensorSubsystem,
)


def _make_subsystem(cls, name, position, radius):
    """Construct a subsystem with body-frame position + radius set
    directly. Bypasses property-driven setup so each test is self-contained."""
    sub = cls(name)
    sub._position = TGPoint3(position[0], position[1], position[2])
    sub._radius = float(radius)
    return sub


def _make_ship(world_pos=(0.0, 0.0, 0.0), rotation=None):
    """Build a bare ShipClass with explicit world position + rotation.

    No SetupProperties pass; the test assembles its own subsystem tree
    via direct slot assignment so each scenario is independent."""
    ship = ShipClass()
    ship.SetWorldLocation(TGPoint3(*world_pos))
    if rotation is not None:
        ship.SetMatrixRotation(rotation)
    return ship


def _attach_hull(ship, radius=5.0):
    hull = _make_subsystem(HullSubsystem, "Hull", (0.0, 0.0, 0.0), radius)
    hull._parent_ship = ship
    ship.SetHull(hull)
    return hull


def _attach_phaser_system_with_bank(ship, bank_position, bank_radius):
    """Mount a PhaserSystem parent with a single PhaserBank child at
    `bank_position` body-frame, radius `bank_radius`. Returns the bank."""
    parent = PhaserSystem("Phasers")
    parent._parent_ship = ship
    parent._position = TGPoint3(0.0, 0.0, 0.0)
    parent._radius = 0.0
    ship._phaser_system = parent
    bank = _make_subsystem(PhaserBank, "BankFL", bank_position, bank_radius)
    parent.AddChildSubsystem(bank)
    return bank


def test_picks_hardpoint_under_weapon_system():
    """Hit near a PhaserBank's body-frame position picks the bank, not
    the parent PhaserSystem, not the hull."""
    ship = _make_ship()
    hull = _attach_hull(ship, radius=5.0)
    bank = _attach_phaser_system_with_bank(ship,
                                           bank_position=(2.0, 0.0, 1.0),
                                           bank_radius=0.5)
    picked = pick_target_subsystem(ship, TGPoint3(2.1, 0.0, 1.0))
    assert picked is bank
    assert picked is not hull


def test_picks_leaf_top_level_subsystem():
    """Hit near the SensorSubsystem's body-frame position picks it."""
    ship = _make_ship()
    _attach_hull(ship, radius=5.0)
    sensor = _make_subsystem(SensorSubsystem, "Sensors", (0.0, 1.5, 0.0), 0.4)
    sensor._parent_ship = ship
    ship._sensor_subsystem = sensor
    picked = pick_target_subsystem(ship, TGPoint3(0.0, 1.55, 0.0))
    assert picked is sensor


def test_falls_back_to_hull_when_no_subsystem_in_range():
    """Hit far from every mounted subsystem returns the hull."""
    ship = _make_ship()
    hull = _attach_hull(ship, radius=5.0)
    _attach_phaser_system_with_bank(ship, bank_position=(2.0, 0.0, 0.0),
                                    bank_radius=0.5)
    picked = pick_target_subsystem(ship, TGPoint3(0.0, 50.0, 0.0))
    assert picked is hull


def test_rotation_invariance():
    """The picker uses the body-frame transform. Rotating the ship 90
    degrees about world-Z moves its body-X axis along world-Y, so a hit
    at world (0, 2.1, 0) should still pick the bank at body (2, 0, 0)."""
    R = TGMatrix3().MakeZRotation(math.pi / 2.0)
    ship = _make_ship(rotation=R)
    _attach_hull(ship, radius=5.0)
    bank = _attach_phaser_system_with_bank(ship,
                                           bank_position=(2.0, 0.0, 0.0),
                                           bank_radius=0.5)
    picked = pick_target_subsystem(ship, TGPoint3(0.0, 2.1, 0.0))
    assert picked is bank


def test_closest_of_two_in_range_wins():
    """Two overlapping in-range hardpoints; the closer one wins."""
    ship = _make_ship()
    _attach_hull(ship, radius=5.0)
    parent = PhaserSystem("Phasers")
    parent._parent_ship = ship
    ship._phaser_system = parent
    near = _make_subsystem(PhaserBank, "Near", (2.0, 0.0, 0.0), 2.0)
    far = _make_subsystem(PhaserBank, "Far", (3.0, 0.0, 0.0), 2.0)
    parent.AddChildSubsystem(near)
    parent.AddChildSubsystem(far)
    picked = pick_target_subsystem(ship, TGPoint3(2.1, 0.0, 0.0))
    assert picked is near


def test_hull_never_iterated_as_candidate():
    """Hull radius is enormous; without hull-exclusion it would swallow
    every hit. The picker must skip hull during the walk and only return
    it as a fallback."""
    ship = _make_ship()
    hull = _attach_hull(ship, radius=100.0)
    bank = _attach_phaser_system_with_bank(ship,
                                           bank_position=(2.0, 0.0, 0.0),
                                           bank_radius=0.5)
    picked = pick_target_subsystem(ship, TGPoint3(2.0, 0.0, 0.0))
    assert picked is bank
    assert picked is not hull
