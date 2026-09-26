"""A mod-supplied ships/Hardpoints/<leaf>.py owns its ship: the engine's stock
hardpoint_overrides pass must NOT run after it (spec 2026-09-26), or every
SPV edit saved into the mod file is clobbered by the stock override on the
next rebuild. The articulated-part snapshot still runs either way.

Tests monkeypatch hardpoint_overrides.OVERRIDES with a synthetic leaf rather
than coupling to authored per-ship data (see test_authored_part_data.py).
"""
import importlib
import sys
import types

import pytest

import App
from engine import mods
from engine.appc import articulated_part, hardpoint_overrides, sdk_overrides
import engine.appc.override_routing as r

LEAF = "_dauntless_test_shadow_refit"
QUAL = "ships.Hardpoints." + LEAF

SRC = ('import App\n'
       'PortWarp = App.EngineProperty_Create("Port Warp")\n'
       'PortWarp.SetRadius(1.200000)\n'
       'App.g_kModelPropertyManager.RegisterLocalTemplate(PortWarp)\n')


@pytest.fixture(autouse=True)
def _clear_index():
    mods.configure(None)
    yield
    mods.configure(None)


def _mod_tree(tmp_path, body=SRC):
    f = tmp_path / "M" / "Scripts" / "ships" / "Hardpoints" / (LEAF + ".py")
    f.parent.mkdir(parents=True)
    f.write_text(body)
    return f


def _recorders(monkeypatch):
    applied, snapped = [], []
    monkeypatch.setattr(hardpoint_overrides, "apply", applied.append)
    monkeypatch.setattr(articulated_part, "snapshot_for_leaf", snapped.append)
    return applied, snapped


def test_mod_supplied_leaf_skips_stock_overrides(tmp_path, monkeypatch):
    _mod_tree(tmp_path)
    mods.configure(mods.build_index(tmp_path))
    applied, snapped = _recorders(monkeypatch)
    sdk_overrides.on_sdk_module_exec(types.ModuleType(QUAL), QUAL)
    assert applied == []
    assert snapped == [LEAF]


def test_stock_leaf_still_gets_overrides(monkeypatch):
    applied, snapped = _recorders(monkeypatch)
    sdk_overrides.on_sdk_module_exec(types.ModuleType(QUAL), QUAL)
    assert applied == [LEAF]
    assert snapped == [LEAF]


@pytest.fixture
def clean_templates():
    mgr = App.g_kModelPropertyManager
    mgr.ClearLocalTemplates()
    yield mgr
    mgr.ClearLocalTemplates()


def test_saved_mod_edit_survives_a_real_sdk_import(tmp_path, monkeypatch,
                                                    clean_templates):
    """End to end through the real _SDKFinder/_SDKLoader: the saved radius is
    what the template holds, not the stock override's."""
    def _stock_override(find):
        p = find("Port Warp")
        if p is not None:
            p.SetRadius(99.0)

    monkeypatch.setitem(hardpoint_overrides.OVERRIDES, LEAF, _stock_override)
    f = _mod_tree(tmp_path)
    r.ModHardpointFileTarget(str(f)).write(LEAF, [("Port Warp", "SetRadius", (0.5,))])
    mods.configure(mods.build_index(tmp_path))

    try:
        importlib.import_module("ships.Hardpoints")
    except ImportError as exc:                       # pragma: no cover
        pytest.skip("SDK ships.Hardpoints package unavailable: %s" % exc)
    try:
        module = importlib.import_module(QUAL)
        from pathlib import Path
        assert Path(module.__spec__.origin).resolve() == f.resolve()
        p = clean_templates.FindByName(
            "Port Warp", App.TGModelPropertyManager.LOCAL_TEMPLATES)
        assert p is not None
        assert p.GetRadius() == 0.5
    finally:
        sys.modules.pop(QUAL, None)
