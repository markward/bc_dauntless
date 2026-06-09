"""End-to-end: import the real Galaxy hardpoint, run LoadPropertySet on a
ShipClass property set, call SetupProperties, then assert the runtime
emitters inherited the values from sdk/.../ships/Hardpoints/galaxy.py.

This is the canonical proof that PR 1's data + structural plumbing all
the way from hardpoint script to runtime emitter works for a real ship.
"""
import importlib
import sys
import pytest

import App
from engine.appc.ships import ShipClass, ShipClass_Create
from engine.appc.subsystems import (
    PhaserBank, PulseWeapon, TractorBeam, TorpedoTube,
    ShipSubsystem, HullSubsystem,
)
from engine.appc.object_emitter import ObjectEmitter


@pytest.fixture(scope="module")
def galaxy_ship():
    """Load Galaxy hardpoint into a fresh ShipClass and run SetupProperties.

    Mirrors loadspacehelper.CreateShip:87-94 — clears local templates,
    (re)loads the hardpoint module so its top-level RegisterLocalTemplate
    calls run, then invokes the module's LoadPropertySet(propertySet).

    Scoped to the module so setup runs once per file; all tests are
    read-only so sharing the instance is safe.
    """
    ship = ShipClass_Create("Galaxy")

    App.g_kModelPropertyManager.ClearLocalTemplates()
    mod_name = "ships.Hardpoints.galaxy"
    if mod_name in sys.modules:
        importlib.reload(sys.modules[mod_name])
    else:
        importlib.import_module(mod_name)
    mod = sys.modules[mod_name]

    mod.LoadPropertySet(ship.GetPropertySet())
    ship.SetupProperties()

    yield ship

    # Teardown — leave the property manager and module cache as we found them.
    App.g_kModelPropertyManager.ClearLocalTemplates()
    for k in list(sys.modules):
        if k == "ships" or k.startswith("ships."):
            del sys.modules[k]


# ── Group inventory ─────────────────────────────────────────────────────────

def test_galaxy_has_phaser_system(galaxy_ship):
    assert galaxy_ship.GetPhaserSystem() is not None


def test_galaxy_has_torpedo_system(galaxy_ship):
    assert galaxy_ship.GetTorpedoSystem() is not None


def test_galaxy_has_tractor_system(galaxy_ship):
    assert galaxy_ship.GetTractorBeamSystem() is not None


# ── Emitter counts ─────────────────────────────────────────────────────────

def test_galaxy_has_eight_phaser_banks(galaxy_ship):
    assert galaxy_ship.GetPhaserSystem().GetNumWeapons() == 8


def test_galaxy_has_six_torpedo_tubes(galaxy_ship):
    assert galaxy_ship.GetTorpedoSystem().GetNumWeapons() == 6


def test_galaxy_has_four_tractor_emitters(galaxy_ship):
    # Aft Tractor 1+2, Forward Tractor 1+2.
    assert galaxy_ship.GetTractorBeamSystem().GetNumWeapons() == 4


# ── Per-emitter charge values ───────────────────────────────────────────────

def test_galaxy_phaser_charge_fields_match_hardpoint(galaxy_ship):
    """Every phaser bank on the Galaxy uses MaxCharge=5, MinFiringCharge=3,
    NormalDischargeRate=1.0, RechargeRate=0.08 (galaxy.py:209-214 and
    matching blocks for the other seven banks)."""
    phasers = galaxy_ship.GetPhaserSystem()
    for i in range(phasers.GetNumWeapons()):
        bank = phasers.GetWeapon(i)
        assert isinstance(bank, PhaserBank)
        assert bank.GetMaxCharge()           == 5.0
        assert bank.GetMinFiringCharge()     == 3.0
        assert bank.GetNormalDischargeRate() == 1.0
        assert bank.GetRechargeRate()        == 0.08
        assert bank.GetChargeLevel()         == 5.0
        assert bank.GetChargePercentage()    == 1.0


def test_galaxy_torpedo_tube_reload_fields_match_hardpoint(galaxy_ship):
    """Every torpedo tube: ImmediateDelay=0.25, ReloadDelay=40, MaxReady=1
    (galaxy.py:28-30, repeated for the other five tubes)."""
    torps = galaxy_ship.GetTorpedoSystem()
    for i in range(torps.GetNumWeapons()):
        tube = torps.GetWeapon(i)
        assert isinstance(tube, TorpedoTube)
        assert tube.GetImmediateDelay() == 0.25
        assert tube.GetReloadDelay()    == 40.0
        assert tube.GetMaxReady()       == 1
        assert tube.GetNumReady()       == 1


def test_galaxy_tractor_charge_fields_match_hardpoint(galaxy_ship):
    """Aft tractors recharge=0.5; forward tractors recharge=0.3
    (galaxy.py:854 + 1054 vs 1257 + 1319)."""
    tractors = galaxy_ship.GetTractorBeamSystem()
    aft_recharge = []
    fwd_recharge = []
    for i in range(tractors.GetNumWeapons()):
        beam = tractors.GetWeapon(i)
        assert isinstance(beam, TractorBeam)
        if beam.GetName().startswith("Aft Tractor"):
            aft_recharge.append(beam.GetRechargeRate())
        elif beam.GetName().startswith("Forward Tractor"):
            fwd_recharge.append(beam.GetRechargeRate())
    assert len(aft_recharge) + len(fwd_recharge) == tractors.GetNumWeapons(), (
        "unclassified tractors: "
        f"{[tractors.GetWeapon(i).GetName() for i in range(tractors.GetNumWeapons())]}"
    )
    assert aft_recharge == [0.5, 0.5]
    assert fwd_recharge == [0.3, 0.3]


# ── WG enum routing ─────────────────────────────────────────────────────────

def test_galaxy_get_weapon_system_group_primary_is_phasers(galaxy_ship):
    assert galaxy_ship.GetWeaponSystemGroup(ShipClass.WG_PRIMARY) is galaxy_ship.GetPhaserSystem()


def test_galaxy_get_weapon_system_group_secondary_is_torpedoes(galaxy_ship):
    assert galaxy_ship.GetWeaponSystemGroup(ShipClass.WG_SECONDARY) is galaxy_ship.GetTorpedoSystem()


def test_galaxy_get_weapon_system_group_tractor_is_tractors(galaxy_ship):
    assert galaxy_ship.GetWeaponSystemGroup(ShipClass.WG_TRACTOR) is galaxy_ship.GetTractorBeamSystem()


# ── Faithful loading: engine pods, bridge, object emitters ───────────────────

def test_galaxy_impulse_aggregator_has_three_pods(galaxy_ship):
    imp = galaxy_ship.GetImpulseEngineSubsystem()
    names = sorted(imp.GetChildSubsystem(i).GetName()
                   for i in range(imp.GetNumChildSubsystems()))
    assert names == ["Center Impulse", "Port Impulse", "Star Impulse"]


def test_galaxy_warp_aggregator_has_two_nacelles(galaxy_ship):
    warp = galaxy_ship.GetWarpEngineSubsystem()
    names = sorted(warp.GetChildSubsystem(i).GetName()
                   for i in range(warp.GetNumChildSubsystems()))
    assert names == ["Port Warp", "Star Warp"]


def test_galaxy_port_warp_condition_matches_hardpoint(galaxy_ship):
    warp = galaxy_ship.GetWarpEngineSubsystem()
    port = warp.GetChildSubsystem("Port Warp")
    assert isinstance(port, ShipSubsystem)
    assert port.GetMaxCondition() == 5000.0  # galaxy.py:909


def test_galaxy_bridge_is_child_of_hull(galaxy_ship):
    hull = galaxy_ship.GetHull()
    assert hull.GetName() == "Hull"
    bridge = hull.GetChildSubsystem("Bridge")
    assert isinstance(bridge, HullSubsystem)
    assert bridge.GetMaxCondition() == 12000.0  # galaxy.py:1108


def test_galaxy_has_two_object_emitters(galaxy_ship):
    names = sorted(e.GetName() for e in galaxy_ship.GetObjectEmitters())
    assert names == ["Probe Launcher", "Shuttle Bay"]
    assert all(isinstance(e, ObjectEmitter) for e in galaxy_ship.GetObjectEmitters())
