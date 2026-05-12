"""Parametrized identity check for every E1M1 ship type.

Verifies that loadspacehelper.CreateShip returns a ShipClass whose
ship-level + hull + propulsion + sensor + shield + weapon-system
identity fields match the SDK hardpoint definition. Expected values
are hand-coded for clarity, and cross-checked at module load against
the actual ships/Hardpoints/<name>.py file via _hardpoint_parser.
"""
from pathlib import Path

import pytest

import App
from engine.appc.properties import ShieldProperty
from tests.integration._hardpoint_parser import extract_setters


SDK_HARDPOINTS = Path(__file__).resolve().parents[2] / "sdk" / "Build" / "scripts" / "ships" / "Hardpoints"


# ── Per-ship expectations ────────────────────────────────────────────────────

GALAXY = {
    "script": "Galaxy",
    "hardpoint_file": "galaxy.py",
    "ship_template": "Galaxy",
    "hull_template": "Hull",
    "genus": 1, "species": 101, "affiliation": 0,
    "mass": 120.0, "rotational_inertia": 15000.0,
    "ship_name": "Dauntless", "ai_string": "FedAttack", "stationary": 0,
    "has_impulse": True,
    "impulse_template": "ImpulseEngines",
    "impulse_max_speed": 6.3, "impulse_max_accel": 1.5,
    "impulse_max_angular_velocity": 0.28, "impulse_max_angular_accel": 0.12,
    "has_warp": True,
    "has_sensor": True,
    "sensor_template": "SensorArray",
    "sensor_base_range": 2000.0, "sensor_max_probes": 10,
    "has_shields": True,
    "shield_template": "ShieldGenerator",
    "shield_max_front": 8000.0, "shield_max_rear": 4000.0,
    "shield_charge_front": 11.0,
    "has_phasers": True,
    "phaser_template": "Phasers",
    "has_torpedoes": True, "torpedo_tube_count": 6,
}

DRYDOCK = {
    "script": "DryDock",
    "hardpoint_file": "drydock.py",
    "ship_template": "DryDock",
    "hull_template": "Hull",
    "affiliation": 0,
    "mass": 300.0,
    "ship_name": "Dry Dock", "ai_string": "StarbaseAttack", "stationary": 1,
    "has_impulse": False, "has_warp": False,
    "has_sensor": True, "sensor_template": "SensorArray",
    "has_shields": True, "shield_template": "ShieldGenerator",
    "has_phasers": False,
    "has_torpedoes": False,
    "torpedo_tube_count": 0,
}

FEDSTARBASE = {
    "script": "FedStarbase",
    "hardpoint_file": "fedstarbase.py",
    "ship_template": "FederationStarbase",
    "hull_template": "Hull",
    "affiliation": 0, "stationary": 1,
    "ship_name": "Space Dock",
    "has_impulse": False, "has_warp": False,
    "has_sensor": True, "sensor_template": "SensorArray",
    # FedStarbase declares a ShieldGenerator with all-zero face maxes — no
    # functional shields. The subsystem object exists (ShipClass_Create) but
    # we don't assert per-face values.
    "has_shields": False,
    "has_phasers": True, "phaser_template": "Phasers",
    "has_torpedoes": False,
    "torpedo_tube_count": 0,
}

SHUTTLE = {
    "script": "Shuttle",
    "hardpoint_file": "shuttle.py",
    "ship_template": "Shuttle",
    "hull_template": "Hull",
    "mass": 15.0, "affiliation": 0, "stationary": 0,
    "has_impulse": True, "impulse_template": "ImpulseEngines",
    "has_warp": True,
    "has_sensor": True, "sensor_template": "SensorArray",
    "has_shields": True, "shield_template": "ShieldGenerator",
    "has_phasers": False,
    "has_torpedoes": False,
    "torpedo_tube_count": 0,
}

SPACEFACILITY = {
    "script": "SpaceFacility",
    "hardpoint_file": "spacefacility.py",
    "ship_template": "Spacefacility",
    "hull_template": "Hull",
    "mass": 500.0, "stationary": 0, "ai_string": "StarbaseAttack",
    "has_impulse": False, "has_warp": False,
    "has_sensor": True, "sensor_template": "SensorArray",
    "has_shields": True, "shield_template": "ShieldGenerator",
    "has_phasers": False, "has_torpedoes": False, "torpedo_tube_count": 0,
}

NEBULA = {
    "script": "Nebula",
    "hardpoint_file": "nebula.py",
    "ship_template": "Nebula",
    "hull_template": "Hull",
    "mass": 100.0, "stationary": 0, "ai_string": "FedAttack",
    "has_impulse": True, "impulse_template": "ImpulseEngines",
    "has_warp": True,
    "has_sensor": True, "sensor_template": "SensorArray",
    "has_shields": True, "shield_template": "ShieldGenerator",
    "has_phasers": True, "phaser_template": "Phasers",
    "has_torpedoes": True, "torpedo_tube_count": 6,
}

AKIRA = {
    "script": "Akira",
    "hardpoint_file": "akira.py",
    "ship_template": "Akira",
    "hull_template": "Hull",
    "mass": 70.0, "stationary": 0,
    "has_impulse": True, "impulse_template": "ImpulseEngines",
    "has_warp": True,
    "has_sensor": True, "sensor_template": "SensorArray",
    "has_shields": True, "shield_template": "ShieldGenerator",
    "has_phasers": True, "phaser_template": "Phasers",
    "has_torpedoes": True, "torpedo_tube_count": 6,
}

FEDOUTPOST = {
    "script": "FedOutpost",
    "hardpoint_file": "fedoutpost.py",
    "ship_template": "FedOutpost",
    "hull_template": "Hull",
    "mass": 400.0, "stationary": 0, "ai_string": "StarbaseAttack",
    "has_impulse": False, "has_warp": False,
    "has_sensor": True, "sensor_template": "SensorArray",
    "has_shields": True, "shield_template": "ShieldGenerator",
    "has_phasers": True, "phaser_template": "Phasers",
    "has_torpedoes": False, "torpedo_tube_count": 0,
}

E1M1_EXPECTATIONS = [GALAXY, DRYDOCK, FEDSTARBASE, SHUTTLE,
                     SPACEFACILITY, NEBULA, AKIRA, FEDOUTPOST]


# ── Cross-check expectations against SDK files at module load ─────────────────

def _verify_expectations_against_sdk():
    """Read each hardpoint file and verify the hand-coded ship-level values."""
    for exp in E1M1_EXPECTATIONS:
        path = SDK_HARDPOINTS / exp["hardpoint_file"]
        ship_setters = extract_setters(path, exp["ship_template"])
        for key in ("mass", "affiliation", "stationary", "ship_name", "ai_string"):
            expected = exp.get(key)
            if expected is None:
                continue
            sdk_key = {
                "mass": "Mass",
                "affiliation": "Affiliation",
                "stationary": "Stationary",
                "ship_name": "ShipName",
                "ai_string": "AIString",
            }[key]
            actual = ship_setters.get(sdk_key)
            assert expected == actual, (
                f"{exp['script']}: expected {key}={expected!r} but SDK has "
                f"{sdk_key}={actual!r} in {exp['hardpoint_file']}"
            )


_verify_expectations_against_sdk()


# ── Fixture ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module", autouse=True)
def sdk_setup():
    from tools.mission_harness import setup_sdk
    setup_sdk()


@pytest.fixture(autouse=True)
def clean_state():
    App.g_kModelPropertyManager.ClearLocalTemplates()
    App.g_kSetManager._sets.clear()
    yield
    App.g_kModelPropertyManager.ClearLocalTemplates()
    App.g_kSetManager._sets.clear()


# ── The actual test ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("expected", E1M1_EXPECTATIONS, ids=lambda e: e["script"])
def test_e1m1_ship_identity(sdk_setup, clean_state, expected):
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "test_set")

    import loadspacehelper
    ship = loadspacehelper.CreateShip(
        expected["script"], pSet, expected["script"] + "_test", None
    )
    assert ship is not None, f"CreateShip({expected['script']!r}) returned None"

    # ── Ship-level identity ──
    if expected.get("mass") is not None:
        assert ship.GetMass() == expected["mass"]
    if expected.get("affiliation") is not None:
        assert ship.GetAffiliation() == expected["affiliation"]
    if expected.get("ship_name") is not None:
        assert ship.GetShipName() == expected["ship_name"]
    if expected.get("ai_string") is not None:
        assert ship.GetAIString() == expected["ai_string"]
    if expected.get("stationary") is not None:
        assert ship.IsStationary() == expected["stationary"]

    # ── Hull (every E1M1 ship has one) ──
    hull = ship.GetHull()
    assert hull is not None, f"{expected['script']} has no hull"
    assert hull.GetMaxCondition() > 0
    assert hull.GetCondition() == hull.GetMaxCondition(), "hull current must seed full"

    # ── Impulse (conditional) ──
    if expected.get("has_impulse"):
        ies = ship.GetImpulseEngineSubsystem()
        assert ies.GetMaxSpeed() > 0, f"{expected['script']} impulse MaxSpeed must be > 0"
        if "impulse_max_speed" in expected:
            assert ies.GetMaxSpeed() == expected["impulse_max_speed"]
        if "impulse_max_accel" in expected:
            assert ies.GetMaxAccel() == expected["impulse_max_accel"]

    # ── Sensor (conditional) ──
    if expected.get("has_sensor"):
        sens = ship.GetSensorSubsystem()
        assert sens.GetBaseSensorRange() > 0, f"{expected['script']} sensor must have a range"

    # ── Shields (conditional) ──
    if expected.get("has_shields"):
        ss = ship.GetShieldSubsystem()
        for face in range(ShieldProperty.NUM_SHIELDS):
            mx = ss.GetMaxShields(face)
            cur = ss.GetCurrentShields(face)
            assert mx > 0, f"{expected['script']} shield face {face} must have max > 0"
            assert cur == mx, f"{expected['script']} shield face {face} not seeded full"
        if "shield_max_front" in expected:
            assert ss.GetMaxShields(ShieldProperty.FRONT_SHIELDS) == expected["shield_max_front"]
        if "shield_max_rear" in expected:
            assert ss.GetMaxShields(ShieldProperty.REAR_SHIELDS) == expected["shield_max_rear"]

    # ── Phasers (conditional) ──
    if expected.get("has_phasers"):
        ps = ship.GetPhaserSystem()
        assert ps.GetMaxCondition() > 0

    # ── Torpedoes (conditional) ──
    if expected.get("has_torpedoes"):
        ts = ship.GetTorpedoSystem()
        assert ts.GetNumAmmoTypes() == expected["torpedo_tube_count"]
        for i in range(expected["torpedo_tube_count"]):
            assert ts.GetAmmoType(i) == App.AT_ONE
    else:
        # Even ships without torpedoes have a TorpedoSystem (default-installed
        # by ShipClass_Create); it should have no ammo loaded.
        assert ship.GetTorpedoSystem().GetNumAmmoTypes() == 0
