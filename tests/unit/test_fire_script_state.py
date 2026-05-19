"""FireScript basic state plumbing: weapon list add/remove + accessor.

These pin the lightest part of the SDK class so we know it loads via
_SDKFinder before we get into Update/Fire/Subsystem-targeting paths."""
import pytest

import App
from engine.appc.ai import PreprocessingAI_Create
from engine.appc.subsystems import PhaserSystem, TorpedoSystem


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def _make_fire_script(sTarget="Target"):
    """Build a FireScript with a PreprocessingAI shell bound to pCodeAI.

    SDK pattern: the AI driver framework sets pCodeAI externally before
    any preprocessor method is called. Slice B tests use the same wiring
    (see tests/unit/test_select_target_dispatch.py)."""
    from AI.Preprocessors import FireScript
    fs = FireScript(sTarget)
    # PreprocessingAI shell — ship=None is fine for state-plumbing tests;
    # GetTarget short-circuits when pCodeAI.GetShip() returns None.
    fs.pCodeAI = PreprocessingAI_Create(None, "FirePP")
    return fs


def test_add_weapon_system_appends_to_list():
    fs = _make_fire_script()
    p = PhaserSystem("P")
    fs.AddWeaponSystem(p)
    assert fs.GetWeapons() == [p]


def test_add_weapon_system_multiple_preserves_order():
    fs = _make_fire_script()
    p, t = PhaserSystem("P"), TorpedoSystem("T")
    fs.AddWeaponSystem(p)
    fs.AddWeaponSystem(t)
    assert fs.GetWeapons() == [p, t]


def test_remove_all_weapon_systems_clears_list():
    fs = _make_fire_script()
    p, t = PhaserSystem("P"), TorpedoSystem("T")
    fs.AddWeaponSystem(p)
    fs.AddWeaponSystem(t)
    fs.RemoveAllWeaponSystems()
    assert fs.GetWeapons() == []


def test_add_weapon_system_sets_using_weapon_type_flag():
    """Adding a new type re-flags UsingWeaponType external dispatch."""
    fs = _make_fire_script()
    fs.bCallUsingWeaponTypeFunc = 0
    fs.AddWeaponSystem(PhaserSystem("P"))
    assert fs.bCallUsingWeaponTypeFunc == 1
