"""The LC Intrepid's own torpedoes load from their Python 1.5 .pyc.

The pack ships ZZ_VoyPhoton and ZZ_Tricobalt ONLY as .pyc (magic 0x4E99).
They used to fall back to the stock photon; engine/py15 now lifts them.

Reads the pack from the project's gitignored mods/ and skips without it.
Every assertion compares against the MOD MODULE'S OWN getters, never a
literal: no value derived from mod content may be committed to this repo.
Spec: docs/superpowers/specs/2026-10-15-pyc-only-mod-modules-design.md §7 T5.
"""
import importlib
import sys

import pytest

import App  # noqa: F401  (SDK shim import order)
from engine import mods
from engine.appc import projectiles, weapon_subsystems
from engine.appc.math import TGPoint3
from engine.appc.properties import WeaponSystemProperty
from engine.appc.subsystems import TorpedoSystem, TorpedoTube
from tests.helpers.bc_assets import PROJECT_ROOT

PACK = PROJECT_ROOT / "mods" / "LC Intrepid Pack"
SCRIPTS = ["Tactical.Projectiles.ZZ_VoyPhoton",
           "Tactical.Projectiles.ZZ_Tricobalt"]


@pytest.fixture(autouse=True)
def intrepid_index():
    probe = PACK / "scripts" / "Tactical" / "Projectiles" / "ZZ_VoyPhoton.pyc"
    if not probe.is_file():
        pytest.skip("LC Intrepid Pack not installed in mods/")
    mods.configure(mods.build_index(PROJECT_ROOT / "mods"))
    weapon_subsystems._reset_projectile_module_cache()
    projectiles._active.clear()
    yield
    for name in SCRIPTS:
        sys.modules.pop(name, None)
    weapon_subsystems._reset_projectile_module_cache()
    projectiles._active.clear()
    mods.configure(None)


def _armed_tube(script) -> TorpedoTube:
    from engine.appc.ships import ShipClass_Create

    ship = ShipClass_Create("Test")
    ship.SetWorldLocation(TGPoint3(0, 0, 0))
    ship._target = None
    ship._target_subsystem = None

    system = TorpedoSystem("Torpedoes")
    system.TurnOn()
    prop = WeaponSystemProperty("Torpedoes")
    prop.SetTorpedoScript(0, script)
    system.SetProperty(prop)
    system._parent_ship = ship
    ship._torpedo_system = system

    tube = TorpedoTube("Forward Torpedo 1")
    tube._reload_delay = 40.0
    tube._immediate_delay = 0.25
    tube._max_ready = 1
    tube._num_ready = 1
    tube._resize_slots()
    system.AddChildSubsystem(tube)
    return tube


@pytest.mark.parametrize("name", SCRIPTS)
def test_the_mod_projectile_loads_from_its_pyc(name, capsys):
    mod = importlib.import_module(name)
    origin = mod.__spec__.origin
    assert origin.lower().endswith(".pyc")
    assert str(PACK) in origin
    assert "[sdk-loader]" not in capsys.readouterr().out
    # ...and the launch resolver hands back THIS module, not the photon.
    assert weapon_subsystems._resolve_projectile_module(name) is mod


@pytest.mark.parametrize("name", SCRIPTS)
def test_its_ammo_type_comes_from_the_mod_module(name):
    from engine.appc.ships import _resolve_torpedo_ammo

    prop = WeaponSystemProperty("Torpedoes")
    prop.SetTorpedoScript(0, name)
    ammo = _resolve_torpedo_ammo(prop, 0)
    mod = importlib.import_module(name)
    assert ammo.GetTorpedoScript() == name
    assert ammo.GetAmmoName() == mod.GetName()
    assert ammo._launch_speed == float(mod.GetLaunchSpeed())


@pytest.mark.parametrize("name", SCRIPTS)
def test_a_fired_torpedo_carries_the_mod_modules_values(name):
    tube = _armed_tube(name)
    assert tube.Fire(target=None, offset=None) is True
    assert len(projectiles._active) == 1
    torp = projectiles._active[0]
    mod = importlib.import_module(name)
    assert torp._damage == float(mod.GetDamage())
    assert torp._guidance_lifetime == float(mod.GetGuidanceLifetime())
    assert torp._max_angular_accel == float(mod.GetMaxAngularAccel())
    assert torp._ttl == float(mod.GetLifetime())
