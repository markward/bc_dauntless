"""Target-list fidelity for inert objects (E1M2 asteroids).

Pins the three fixes that make an asteroid render like the original game:

  1. Non-targetable subsystems (Shield Generator, Power Plant) and the hull
     never appear as target-menu rows — an asteroid shows ZERO subsystems.
  2. A shield-less hull reports has_shields=False so the view drops the bar.
  3. The hull bar is calibrated to the mission-set max: E1M2's CreateDebris
     pegs the hull at 300/300 = 100% via the shared property template, even
     though the hardpoint declared a larger max.

Also guards that a real warship KEEPS its targetable systems but likewise
drops the hull row and any non-targetable group.
"""
import importlib
import sys

from engine.appc.ships import ShipClass_Create
from engine.appc.target_menu import STTargetMenu


def _build(hardpoint, class_name):
    """Mirror loadspacehelper.CreateShip for a bare hardpoint load."""
    for k in list(sys.modules):
        if k == "ships" or k.startswith("ships."):
            del sys.modules[k]
    mod = importlib.import_module("ships.Hardpoints." + hardpoint)
    ship = ShipClass_Create(class_name)
    mod.LoadPropertySet(ship.GetPropertySet())
    ship.SetupProperties()
    ship.SetName(class_name)
    return ship


def _rows(ship):
    menu = STTargetMenu("t")
    menu.RebuildShipMenu(ship)
    row = menu.GetObjectEntry(ship)
    return [c.GetLabel() for c in row._children]


# ── #1: phantom subsystems ────────────────────────────────────────────────────

def test_asteroid_shows_no_subsystem_rows():
    ship = _build("asteroid", "Asteroid")
    # Sanity: the subsystems DO exist on the ship (SDK-faithful construction) —
    # they are just non-targetable, so the menu must hide them.
    assert ship.GetShields() is not None
    assert ship.GetPowerSubsystem() is not None
    assert ship.GetShields().IsTargetable() == 0
    assert ship.GetPowerSubsystem().IsTargetable() == 0
    assert _rows(ship) == []


def test_setup_copies_targetable_from_property():
    ship = _build("asteroid", "Asteroid")
    # asteroid hardpoint: Shield Generator / Power Plant SetTargetable(0),
    # hull "Asteroid" SetTargetable(1).
    assert ship.GetShields().IsTargetable() == 0
    assert ship.GetPowerSubsystem().IsTargetable() == 0
    assert ship.GetHull().IsTargetable() == 1


def test_warship_keeps_targetable_systems_but_no_hull_row():
    ship = _build("Warbird", "Warbird")
    rows = _rows(ship)
    assert rows, "warship must still list its targetable subsystems"
    # Hull is the ship-level bar, never a subsystem row.
    assert not any("hull" in r.lower() for r in rows)
    # A targetable system is present (Shield Generator / Sensor Array etc.).
    assert any(r in ("Shield Generator", "Sensor Array", "Power Plant") for r in rows)


# ── #2: shield-less targets ───────────────────────────────────────────────────

def test_asteroid_reports_no_shields():
    ship = _build("asteroid", "Asteroid")
    shields = ship.GetShields()
    assert shields.HasShields() == 0
    # GetShieldPercentage still returns 1.0 (deliberate AI signal) — the view
    # relies on HasShields(), not the percentage, to drop the bar.
    assert shields.GetShieldPercentage() == 1.0


def test_warship_reports_shields():
    ship = _build("Warbird", "Warbird")
    assert ship.GetShields().HasShields() == 1


# ── #3: hull calibration via the mission-set (shared) property max ────────────

def test_asteroid_hull_calibrates_to_mission_max():
    ship = _build("asteroid", "Asteroid")
    hull = ship.GetHull()
    # Before the E1M2 override, max is the hardpoint value (asteroid = 2500).
    assert hull.GetMaxCondition() == 2500.0
    # E1M2 CreateDebris: rescale via the property, then peg current to full.
    prop = hull.GetProperty()
    prop.SetMaxCondition(300.0)
    hull.SetCondition(prop.GetMaxCondition())
    # Subsystem now delegates max to the property → 300/300 = 100%.
    assert hull.GetMaxCondition() == 300.0
    assert hull.GetConditionPercentage() == 1.0


def test_condition_percentage_clamps_when_condition_exceeds_max():
    ship = _build("asteroid", "Asteroid")
    hull = ship.GetHull()
    hull.GetProperty().SetMaxCondition(300.0)
    hull.SetCondition(9999.0)  # artificially above max
    assert hull.GetConditionPercentage() == 1.0  # clamped, never overflows
