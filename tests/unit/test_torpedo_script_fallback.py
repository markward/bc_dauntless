"""An unimportable projectile script falls back to the stock photon.

Community ship mods can ship their projectile modules as Python 1.5 `.pyc`
with no source. engine/py15 now loads the straight-line ones (the LC Intrepid
pack's `ZZ_VoyPhoton` and `ZZ_Tricobalt`; see
tests/unit/test_lc_intrepid_pyc_projectiles.py), but a module it refuses --
or any other unimportable script -- still makes `import_module` raise, and
the tube used to `return` out of `_spawn_torpedo` in silence.

That silence was the bug, not the missing module. `Fire()` calls
`_spawn_torpedo` AFTER it has already decremented `_num_ready`, started the
slot cooldown and dropped the ammo reserve, and it goes on to return True and
broadcast ET_WEAPON_FIRED. So every trigger pull burned a torpedo, reloaded
the tube, and launched nothing — with no ET_TORPEDO_FIRED and no log line.

Stock content never hits this: every SDK projectile is a `.py`.
"""
import pytest

import App  # noqa: F401  (SDK shim import order)
from engine.appc import projectiles
from engine.appc.math import TGPoint3
from engine.appc.properties import WeaponSystemProperty
from engine.appc.subsystems import TorpedoSystem, TorpedoTube


MISSING = "Tactical.Projectiles.ZZ_NotShippedAsSource"


@pytest.fixture(autouse=True)
def clear_registry():
    projectiles._active.clear()
    yield
    projectiles._active.clear()


@pytest.fixture
def captured():
    seen = []
    globals()["_collect"] = lambda _obj, evt: seen.append(evt)
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        App.ET_TORPEDO_FIRED, object(), __name__ + "._collect")
    yield seen
    App.g_kEventManager._broadcast_handlers.pop(App.ET_TORPEDO_FIRED, None)


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


def test_unimportable_script_still_launches_a_projectile():
    tube = _armed_tube(MISSING)

    assert tube.Fire(target=None, offset=None) is True
    assert len(projectiles._active) == 1, (
        "an unimportable projectile module must fall back to the stock "
        "photon, not silently launch nothing")


def test_unimportable_script_still_posts_torpedo_fired(captured):
    tube = _armed_tube(MISSING)
    tube.Fire(target=None, offset=None)

    assert len(captured) == 1
    # Source is the PROJECTILE (probe q12) — so a fallback that posted the
    # event without spawning would be caught here too.
    assert captured[0].GetSource() is not None


def test_fallback_projectile_matches_a_real_photon():
    """The substitute is the stock PhotonTorpedo, not an empty Torpedo shell:
    the same module a hardpoint naming PhotonTorpedo directly would load."""
    real = _armed_tube("Tactical.Projectiles.PhotonTorpedo")
    real.Fire(target=None, offset=None)
    expected = projectiles._active[0].GetName()
    projectiles._active.clear()

    fallback = _armed_tube(MISSING)
    fallback.Fire(target=None, offset=None)

    assert projectiles._active[0].GetName() == expected


def test_importable_script_is_untouched():
    """The fallback must not disturb the path stock ships take."""
    tube = _armed_tube("Tactical.Projectiles.PhotonTorpedo")

    assert tube.Fire(target=None, offset=None) is True
    assert len(projectiles._active) == 1


# ── The ammo type, not just the launch ───────────────────────────────────
# _spawn_torpedo already substitutes the photon. The AMMO TYPE built from the
# hardpoint (ships._resolve_torpedo_ammo) did not: on an import failure it
# kept no script at all, so the SDK's FireScript.ChooseTorpType
# (AI/Preprocessors.py:566) did `__import__(pAmmo.GetTorpedoScript())`, got
# None back through the SDK loader's __import__ rewrite, and raised
# AttributeError twice (its own `except` re-reads pScript). That escaped
# FireScript.Update before its weapon cycle advanced, so every update landed
# on the torpedo system again: an LC Intrepid's fire script never reached its
# phasers. Live 2026-10-15 ("[ai] Intrepid-1 node 'FireAll' raised ...").

def _two_slot_system(script0, script1) -> TorpedoSystem:
    from engine.appc.ships import _resolve_torpedo_ammo

    prop = WeaponSystemProperty("Torpedoes")
    prop.SetTorpedoScript(0, script0)
    prop.SetMaxTorpedoes(0, 150)
    prop.SetTorpedoScript(1, script1)
    prop.SetMaxTorpedoes(1, 20)
    system = TorpedoSystem("Torpedoes")
    system.SetProperty(prop)
    for slot in (0, 1):
        system.AddAmmoType(_resolve_torpedo_ammo(prop, slot))
    return system


def test_unimportable_ammo_type_carries_the_fallback_photon_script():
    from engine.appc.ships import _resolve_torpedo_ammo
    from engine.appc.weapon_subsystems import _FALLBACK_PROJECTILE

    prop = WeaponSystemProperty("Torpedoes")
    prop.SetTorpedoScript(0, MISSING)
    prop.SetMaxTorpedoes(0, 150)
    ammo = _resolve_torpedo_ammo(prop, 0)

    assert ammo.GetTorpedoScript() == _FALLBACK_PROJECTILE
    assert ammo.GetAmmoName() == "Photon"
    assert ammo.GetMaxTorpedoes() == 150, "the hardpoint's capacity survives"


def test_sdk_choose_torp_type_survives_two_unimportable_ammo_types():
    import AI.Preprocessors as P

    system = _two_slot_system(MISSING, MISSING + "_Two")
    assert system.GetNumAvailableTorpsToType(0) > 0
    assert system.GetNumAvailableTorpsToType(1) > 0

    # ChooseTorpType reads no FireScript state; call the SDK body as is.
    P.FireScript.ChooseTorpType(None, system, TGPoint3(40.0, 0.0, 0.0), 2.0)

    assert system.GetAmmoTypeNumber() in (0, 1)
