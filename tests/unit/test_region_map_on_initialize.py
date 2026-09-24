"""A mapped region set takes the map the moment BC's region module creates it.

Wrapping Initialize() is the one interception point every creation path goes
through: warp arrival, MissionLib.SetupSpaceSet, a mission calling
Systems.X.Y.Initialize() directly (E7M3), and system loading. It cannot be
done at AddObjectToSet: BC's <Region>_S.py adds a body THEN places it.
"""
import importlib
import sys
import types
from pathlib import Path

import pytest

import App
from engine.appc import sdk_overrides
from engine.appc.sets import SetClass_Create
from engine.systems import region_hooks, resolve

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def setup_function(_):
    App.g_kSetManager._sets.clear()
    region_hooks.reset()


def teardown_function(_):
    App.g_kSetManager._sets.clear()
    region_hooks.reset()


def _fake_region_module(qualname, set_name, planet_name, bc_radius=90.0, raises=False):
    """A region module shaped like Systems/Ona/Ona1.py: Initialize creates and
    registers the set, adds the planet, then places it."""
    mod = types.ModuleType(qualname)

    def Initialize():
        pSet = SetClass_Create()
        App.g_kSetManager.AddSet(pSet, set_name)
        planet = App.Planet_Create(bc_radius, "data/models/environment/RedPlanet.nif")
        pSet.AddObjectToSet(planet, planet_name)
        planet.SetTranslateXYZ(100.0, 500.0, 0.0)   # BC's placement, AFTER the add
        if raises:
            raise ImportError("Ona1_S missing")

    mod.Initialize = Initialize
    mod.GetSetName = lambda: set_name
    return mod


def _map_radius(set_name, body_name):
    m, region = resolve.for_set(set_name)
    return next(b.radius_gu for b in m.bodies
                if b.name == body_name and b.owner_region == region.set_name)


def test_dispatcher_routes_a_region_module(monkeypatch):
    calls = []
    monkeypatch.setattr(region_hooks, "on_region_module_exec",
                        lambda mod, q: calls.append(q))
    sdk_overrides.on_sdk_module_exec(types.ModuleType("x"), "Systems.Ona.Ona1")
    assert calls == ["Systems.Ona.Ona1"]


def test_dispatcher_ignores_static_modules_and_packages(monkeypatch):
    calls = []
    monkeypatch.setattr(region_hooks, "on_region_module_exec",
                        lambda mod, q: calls.append(q))
    for q in ("Systems", "Systems.Ona", "Systems.Ona.Ona1_S", "Systems.Utils"):
        sdk_overrides.on_sdk_module_exec(types.ModuleType("x"), q)
    assert calls == []


def test_initialize_applies_the_map_after_bc_places_the_body():
    mod = _fake_region_module("Systems.Ona.Ona1", "Ona1", "Ona 1")
    region_hooks.on_region_module_exec(mod, "Systems.Ona.Ona1")
    mod.Initialize()
    pSet = App.g_kSetManager.GetSet("Ona1")
    planet = pSet.GetObject("Ona 1")
    assert planet.GetRadius() == pytest.approx(_map_radius("Ona1", "Ona 1"))
    loc = planet.GetWorldLocation()
    assert (loc.x, loc.y) != (100.0, 500.0), "BC's placement was not overridden"
    assert region_hooks.is_mapped(pSet)


def test_an_unmapped_region_is_left_alone():
    mod = _fake_region_module("Systems.Starbase12.Starbase12", "Starbase12", "Planet")
    original = mod.Initialize
    region_hooks.on_region_module_exec(mod, "Systems.Starbase12.Starbase12")
    assert mod.Initialize is original


def test_wrapping_twice_does_not_double_wrap():
    mod = _fake_region_module("Systems.Ona.Ona1", "Ona1", "Ona 1")
    region_hooks.on_region_module_exec(mod, "Systems.Ona.Ona1")
    wrapped = mod.Initialize
    region_hooks.on_region_module_exec(mod, "Systems.Ona.Ona1")
    assert mod.Initialize is wrapped


def test_a_reexecuted_module_is_wrapped_again():
    """importlib.reload re-runs the module body, rebinding a pristine
    Initialize; the loader hook fires again and must re-wrap it."""
    mod = _fake_region_module("Systems.Ona.Ona1", "Ona1", "Ona 1")
    region_hooks.on_region_module_exec(mod, "Systems.Ona.Ona1")
    fresh = _fake_region_module("Systems.Ona.Ona1", "Ona1", "Ona 1")
    mod.Initialize = fresh.Initialize
    region_hooks.on_region_module_exec(mod, "Systems.Ona.Ona1")
    mod.Initialize()
    assert region_hooks.is_mapped(App.g_kSetManager.GetSet("Ona1"))


def test_initialize_twice_is_idempotent():
    """Review Focus 1: a mission re-running setup must leave the body at the
    map radius, not the map radius scaled again."""
    mod = _fake_region_module("Systems.Ona.Ona1", "Ona1", "Ona 1")
    region_hooks.on_region_module_exec(mod, "Systems.Ona.Ona1")
    mod.Initialize()
    mod.Initialize()
    planet = App.g_kSetManager.GetSet("Ona1").GetObject("Ona 1")
    assert planet.GetRadius() == pytest.approx(_map_radius("Ona1", "Ona 1"))


def test_a_raising_initialize_propagates_and_maps_nothing():
    """Review Focus 2: fail loud, and never map a stale same-named set."""
    stale = SetClass_Create()
    App.g_kSetManager.AddSet(stale, "Ona1")
    mod = _fake_region_module("Systems.Ona.Ona1", "Ona1", "Ona 1", raises=True)
    region_hooks.on_region_module_exec(mod, "Systems.Ona.Ona1")
    with pytest.raises(ImportError):
        mod.Initialize()
    # BC's Initialize re-registered "Ona1" before raising, so the set now
    # under that name is the half-built one. Neither it nor the stale one
    # may be mapped: a wrap that swallowed the error and applied anyway
    # would map whichever GetSet("Ona1") returned.
    assert not region_hooks.is_mapped(App.g_kSetManager.GetSet("Ona1"))
    assert not region_hooks.is_mapped(stale)


def test_apply_to_set_sets_the_flag_and_only_on_success():
    from engine.systems import apply_map
    mapped = SetClass_Create()
    App.g_kSetManager.AddSet(mapped, "Ona1")
    assert apply_map.apply_to_set(mapped, "Ona1") is True
    assert region_hooks.is_mapped(mapped)
    other = SetClass_Create()
    App.g_kSetManager.AddSet(other, "QuickBattle")
    assert apply_map.apply_to_set(other, "QuickBattle") is False
    assert not region_hooks.is_mapped(other)


def test_the_alarm_fires_for_a_mapped_frame_set_realized_unmapped(capsys):
    raw = SetClass_Create()
    App.g_kSetManager.AddSet(raw, "Ona2")
    assert region_hooks.check_realized(raw) is False
    assert region_hooks.unmapped_realized == ["Ona2"]
    assert "[systems] ALARM" in capsys.readouterr().out


def test_the_alarm_is_silent_for_mapped_and_unmapped_frames(capsys):
    from engine.systems import apply_map
    mapped = SetClass_Create()
    App.g_kSetManager.AddSet(mapped, "Ona1")
    apply_map.apply_to_set(mapped, "Ona1")
    qb = SetClass_Create()
    App.g_kSetManager.AddSet(qb, "QuickBattle")
    assert region_hooks.check_realized(mapped) is True
    assert region_hooks.check_realized(qb) is True
    assert region_hooks.unmapped_realized == []
    assert "ALARM" not in capsys.readouterr().out


def test_both_sdk_loaders_route_region_modules():
    """The runtime loader (tools/mission_harness.py) and its test twin
    (tests/conftest.py) must gate identically -- a hook in one only passes
    or fails asymmetrically."""
    gate = '_qual.startswith(("ships.", "Systems."))'
    for rel in ("tools/mission_harness.py", "tests/conftest.py"):
        assert gate in (PROJECT_ROOT / rel).read_text(), f"{rel} does not route Systems.*"


def test_realizing_an_unmapped_region_set_raises_the_alarm():
    from engine import host_loop as hl
    from tests.unit.test_realize_set import _FakeRenderer
    raw = SetClass_Create()
    App.g_kSetManager.AddSet(raw, "Ona3")
    hl.realize_set_objects(hl.MissionSession(mission_name="t"), raw, _FakeRenderer())
    assert region_hooks.unmapped_realized == ["Ona3"]


def _fresh(qualname):
    import tools.mission_harness as mh
    mh.setup_sdk()
    sys.modules.pop(qualname, None)
    return importlib.import_module(qualname)


def _assert_mapped(set_name, body_name):
    pSet = App.g_kSetManager.GetSet(set_name)
    assert pSet is not None
    assert region_hooks.is_mapped(pSet)
    assert pSet.GetObject(body_name).GetRadius() == pytest.approx(
        _map_radius(set_name, body_name))


def test_real_sdk_direct_initialize_is_mapped():
    """E7M3's path: import Systems.X.Y, then call its Initialize()."""
    _fresh("Systems.Ona.Ona1").Initialize()
    _assert_mapped("Ona1", "Ona 1")


def test_real_sdk_setup_space_set_is_mapped():
    """How campaign missions stand up their starting set -- the path the
    reference branch left unmapped."""
    import MissionLib
    _fresh("Systems.Ona.Ona2")
    MissionLib.SetupSpaceSet("Systems.Ona.Ona2")
    _assert_mapped("Ona2", "Ona 2")


def test_real_sdk_warp_arrival_is_mapped():
    from engine.appc import warp
    warp.configure_warp_hooks(realize=None, teardown=None)
    sys.modules.pop("Systems.Ona.Ona3", None)
    warp.ChangeRenderedSetAction_Create("Systems.Ona.Ona3")._do_play()
    _assert_mapped("Ona3", "Ona 3")
    App.g_kSetManager.ClearRenderedSet()
