"""An unimportable projectile script falls back to the stock photon.

Community ship mods routinely ship their projectile modules as Python 1.5
`.pyc` with no source — the LC Intrepid pack's `ZZ_VoyPhoton` and
`ZZ_Tricobalt` are both magic 0x4E99, the Python that `stbc.exe` embeds.
CPython cannot load those, so `import_module` raises and the tube used to
`return` out of `_spawn_torpedo` in silence.

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
