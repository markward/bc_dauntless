"""Engine-owned ship-data overrides: dispatcher routing, hardpoint template
overrides, GetShipStats overlays, and the real-galaxy integration path.

The override pass is the second half of "pre-load then override": SDK ship
files run untouched, then engine/appc/sdk_overrides.py routes the just-executed
module to hardpoint_overrides (property templates) or ship_overrides
(GetShipStats overlay). sdk/Build/scripts/ is never modified.
"""
import importlib
import sys
import types

import App
import tools.mission_harness as mh
from engine.appc import hardpoint_overrides, sdk_overrides, ship_overrides


# ---------------------------------------------------------------- dispatcher

def test_dispatcher_routes_hardpoint_leaf(monkeypatch):
    calls = []
    monkeypatch.setattr(hardpoint_overrides, "apply", calls.append)
    mod = types.ModuleType("ships.Hardpoints.galaxy")
    sdk_overrides.on_sdk_module_exec(mod, "ships.Hardpoints.galaxy")
    assert calls == ["galaxy"]


def test_dispatcher_routes_ship_module(monkeypatch):
    calls = []
    monkeypatch.setattr(ship_overrides, "apply", calls.append)
    mod = types.ModuleType("ships.Galaxy")
    sdk_overrides.on_sdk_module_exec(mod, "ships.Galaxy")
    assert calls == [mod]


def test_dispatcher_ignores_packages_and_non_ship_modules(monkeypatch):
    hp_calls, ship_calls = [], []
    monkeypatch.setattr(hardpoint_overrides, "apply", hp_calls.append)
    monkeypatch.setattr(ship_overrides, "apply", ship_calls.append)
    for name in ("ships", "ships.Hardpoints", "Bridge.BridgeMenus",
                 "ships.Hardpoints.sub.extra"):
        sdk_overrides.on_sdk_module_exec(types.ModuleType(name), name)
    assert hp_calls == [] and ship_calls == []


def test_dispatcher_swallows_broken_section(monkeypatch, capsys):
    def boom(_leaf):
        raise RuntimeError("section exploded")

    monkeypatch.setattr(hardpoint_overrides, "apply", boom)
    mod = types.ModuleType("ships.Hardpoints.galaxy")
    sdk_overrides.on_sdk_module_exec(mod, "ships.Hardpoints.galaxy")  # no raise
    out = capsys.readouterr().out
    assert "[sdk-overrides]" in out and "section exploded" in out


# ------------------------------------------------------- hardpoint overrides

def test_hardpoint_apply_unknown_leaf_is_noop():
    hardpoint_overrides.apply("no_such_ship")  # must not raise


def test_hardpoint_apply_missing_templates_is_none_safe():
    App.g_kModelPropertyManager.ClearLocalTemplates()
    hardpoint_overrides.apply("galaxy")  # every find() returns None


def test_hardpoint_apply_writes_glow_data_to_registered_template():
    App.g_kModelPropertyManager.ClearLocalTemplates()
    pw = App.EngineProperty_Create("Port Warp")
    App.g_kModelPropertyManager.RegisterLocalTemplate(pw)
    hardpoint_overrides.apply("galaxy")

    assert pw.GetGlowRegionShape(0) == "Cylinder"
    assert pw.GetGlowRegionRadius(0) == 0.45
    # Multi-arg setters key on all-but-last arg (data-bag convention).
    assert pw._data[("GlowRegionAxis", (0, 0.0, 1.0))] == 0.0
    assert pw._data[("GlowRegionExtent", (0, -2.0))] == 2.0
    App.g_kModelPropertyManager.ClearLocalTemplates()


# ----------------------------------------------------------- stats overlays

def _fake_ship_module(name="ships.FakeShip", stats=None):
    base = {"Name": "Fake", "HardpointFile": "fake"} if stats is None else stats
    mod = types.ModuleType(name)

    def GetShipStats():
        return base

    mod.GetShipStats = GetShipStats
    mod._base_stats = base
    return mod


def test_stats_overlay_merges_global_then_per_ship(monkeypatch):
    monkeypatch.setattr(ship_overrides, "GLOBAL_STATS_OVERLAY",
                        {"SpecularCoef": 1.2, "DamageRadMod": 5.0})
    monkeypatch.setitem(ship_overrides.SHIP_STATS_OVERLAYS, "FakeShip",
                        {"DamageRadMod": 9.0, "DauntlessDamageType": "plasma"})
    mod = _fake_ship_module()
    ship_overrides.apply(mod)
    stats = mod.GetShipStats()
    assert stats["Name"] == "Fake"                    # original preserved
    assert stats["SpecularCoef"] == 1.2               # global applied
    assert stats["DamageRadMod"] == 9.0               # per-ship wins
    assert stats["DauntlessDamageType"] == "plasma"   # new key visible
    assert "SpecularCoef" not in mod._base_stats      # source not mutated


def test_stats_overlay_empty_leaves_module_untouched():
    mod = _fake_ship_module(name="ships.NoOverlayShip")
    orig = mod.GetShipStats
    ship_overrides.apply(mod)
    assert mod.GetShipStats is orig


def test_stats_overlay_does_not_double_wrap(monkeypatch):
    monkeypatch.setitem(ship_overrides.SHIP_STATS_OVERLAYS, "FakeShip",
                        {"SpecularCoef": 2.0})
    mod = _fake_ship_module()
    ship_overrides.apply(mod)
    wrapped = mod.GetShipStats
    ship_overrides.apply(mod)
    assert mod.GetShipStats is wrapped
    assert mod.GetShipStats()["SpecularCoef"] == 2.0


def test_stats_overlay_rewraps_after_reexec(monkeypatch):
    monkeypatch.setitem(ship_overrides.SHIP_STATS_OVERLAYS, "FakeShip",
                        {"SpecularCoef": 2.0})
    mod = _fake_ship_module()
    ship_overrides.apply(mod)
    # Simulate a module re-exec: the pristine function is rebound.
    base = {"Name": "Fake2"}
    mod.GetShipStats = lambda: base
    ship_overrides.apply(mod)
    stats = mod.GetShipStats()
    assert stats["Name"] == "Fake2" and stats["SpecularCoef"] == 2.0


# -------------------------------------------------------------- integration

def _load_real_galaxy_hardpoint():
    mh.setup_sdk()
    App.g_kModelPropertyManager.ClearLocalTemplates()
    sys.modules.pop("ships.Hardpoints.galaxy", None)
    return importlib.import_module("ships.Hardpoints.galaxy")


def _port_warp():
    return App.g_kModelPropertyManager.FindByName(
        "Port Warp", App.TGModelPropertyManager.LOCAL_TEMPLATES)


def test_real_galaxy_load_applies_glow_overrides():
    _load_real_galaxy_hardpoint()
    pw = _port_warp()
    assert pw is not None
    assert pw.GetGlowRegionShape(0) == "Cylinder"
    sa = App.g_kModelPropertyManager.FindByName(
        "Sensor Array", App.TGModelPropertyManager.LOCAL_TEMPLATES)
    assert sa is not None and sa.GetGlowRegionShape(0) == "Sphere"


def test_real_galaxy_reload_reapplies_overrides():
    """Mirror loadspacehelper.CreateShip: ClearLocalTemplates() -> reload(mod)
    must land the overrides on the freshly registered templates."""
    mod = _load_real_galaxy_hardpoint()
    first = _port_warp()
    App.g_kModelPropertyManager.ClearLocalTemplates()
    importlib.reload(mod)
    fresh = _port_warp()
    assert fresh is not None and fresh is not first
    assert fresh.GetGlowRegionShape(0) == "Cylinder"
    assert fresh.GetGlowRegionRadius(0) == 0.45


# ------------------------------------------------- baked impulse sections

def _load_real_hardpoint(leaf):
    mh.setup_sdk()
    App.g_kModelPropertyManager.ClearLocalTemplates()
    sys.modules.pop(f"ships.Hardpoints.{leaf}", None)
    return importlib.import_module(f"ships.Hardpoints.{leaf}")


def _find(name):
    return App.g_kModelPropertyManager.FindByName(
        name, App.TGModelPropertyManager.LOCAL_TEMPLATES)


def test_baked_impulse_extraction_matches_runtime_pod_rule():
    """extract_impulse_pods mirrors subsystem_glow.impulse_engines(): EP_IMPULSE
    children win; aggregator-only ships fall back to ImpulseEngineProperty."""
    from engine.appc.properties import EngineProperty, ImpulseEngineProperty
    from tools.bake_impulse_glow import extract_impulse_pods

    _load_real_galaxy_hardpoint()
    pods = extract_impulse_pods(App.g_kModelPropertyManager,
                                EngineProperty, ImpulseEngineProperty)
    assert pods == [("Port Impulse", 0.25), ("Star Impulse", 0.25),
                    ("Center Impulse", 0.25)]

    class _FakeMgr:
        pass

    agg = ImpulseEngineProperty("Impulse Engines")
    agg.SetRadius(0.5)
    fake = _FakeMgr()
    fake._local = {"Impulse Engines": agg}
    assert extract_impulse_pods(fake, EngineProperty, ImpulseEngineProperty) \
        == [("Impulse Engines", 0.5)]


def test_baked_galaxy_impulse_is_cylinder():
    _load_real_galaxy_hardpoint()
    for name in ("Port Impulse", "Star Impulse", "Center Impulse"):
        p = _find(name)
        assert p is not None
        assert p.GetGlowRegionShape(0) == "Cylinder", name
        assert p.GetGlowRegionRadius(0) == 0.25, name
        assert p._data[("GlowRegionExtent", (0, 0.0))] == 2.0, name


def test_baked_akira_section_applies_on_real_load():
    _load_real_hardpoint("akira")
    p = _find("Port Impulse")
    assert p is not None
    assert p.GetGlowRegionShape(0) == "Cylinder"
    assert p.GetGlowRegionRadius(0) == 0.23  # akira's authored hardpoint radius


def test_sovereign_sdk_hardpoint_gets_baked_glow_and_skin_shield():
    """Sovereign loads from the SDK tree (the root-shadow fork was deleted);
    the loader hook applies its section: baked impulse glow + skin shielding."""
    _load_real_hardpoint("sovereign")
    p = _find("Port Impulse")
    assert p is not None
    assert p.GetGlowRegionShape(0) == "Cylinder"
    sg = _find("Shield Generator")
    assert sg is not None and sg.GetSkinShielding() == 1


def test_every_override_leaf_has_a_hardpoint_file():
    from tools.bake_impulse_glow import ROOT_HARDPOINTS, SDK_HARDPOINTS
    for leaf in hardpoint_overrides.OVERRIDES:
        assert (SDK_HARDPOINTS / f"{leaf}.py").exists() \
            or (ROOT_HARDPOINTS / f"{leaf}.py").exists(), leaf
