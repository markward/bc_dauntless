"""Developer "System Preview" mission (system-frames Plan 3, Task 7).

Runs the mission's Initialize() through the real harness (the same path a
mission-picker pick takes), then drives one system_loader.ensure_loaded(player)
-- exactly what host_loop's own per-tick call does -- and checks that the
whole Ona system comes up mapped, with the player parked at Ona1's Player
Start.

The registry assertion goes through engine.host_loop._developer_family_entry(),
the exact function _get_mission_registry() (the picker's own registry_getter)
calls to build the synthetic Developer family -- not a hand-rolled copy of
its expected shape.
"""
import pytest

import App
import tools.mission_harness as mh
from engine.systems import region_hooks, system_loader


def setup_function(_):
    App.g_kSetManager._sets.clear()
    App.g_kSetManager.ClearRenderedSet()
    system_loader.reset()


def teardown_function(_):
    App.g_kSetManager._sets.clear()
    App.g_kSetManager.ClearRenderedSet()
    system_loader.reset()


def test_the_module_imports():
    import engine.dev_missions.system_preview as system_preview
    assert hasattr(system_preview, "Initialize")


def test_running_it_and_ensure_loaded_maps_the_whole_ona_system():
    mh.setup_sdk()
    status, exc = mh.run_mission("engine.dev_missions.system_preview")
    assert status == "pass", exc

    ona1 = App.g_kSetManager.GetSet("Ona1")
    assert ona1 is not None, "the mission's own region must be up"
    player = ona1.GetObject("player")
    assert player is not None, "the mission must create the player in Ona1"

    created = system_loader.ensure_loaded(player)
    assert sorted(created) == ["Ona2", "Ona3"]

    for name in ("Ona1", "Ona2", "Ona3"):
        pSet = App.g_kSetManager.GetSet(name)
        assert pSet is not None and region_hooks.is_mapped(pSet)


def test_the_player_is_at_ona1s_player_start():
    mh.setup_sdk()
    status, exc = mh.run_mission("engine.dev_missions.system_preview")
    assert status == "pass", exc
    ona1 = App.g_kSetManager.GetSet("Ona1")
    player = ona1.GetObject("player")
    p = player.GetWorldLocation()
    # Ona1.py's "Player Start" waypoint sits at the origin.
    assert (p.x, p.y, p.z) == pytest.approx((0.0, 0.0, 0.0))


def test_system_preview_is_registered_in_the_developer_family():
    from engine import host_loop
    fam = host_loop._developer_family_entry()
    assert fam.dir_name == "Developer"
    modules = {m.module_name: m for ep in fam.episodes for m in ep.missions}
    assert "engine.dev_missions.system_preview" in modules
    entry = modules["engine.dev_missions.system_preview"]
    assert entry.display_name == "System Preview"


def _set_course_menu():
    """The live Helm > Set Course menu -- the harness's LoadBridge builds the
    real bridge menus, and this is the lookup Systems.Utils.
    CreateSystemMenuInternal itself does."""
    tcw = App.TacticalControlWindow_GetTacticalControlWindow()
    db = App.g_kLocalizationManager.Load("data/TGL/Bridge Menus.tgl")
    helm = tcw.FindMenu(db.GetString("Helm"))
    course = helm.GetSubmenuW(db.GetString("Set Course")) if helm else None
    App.g_kLocalizationManager.Unload(db)
    assert course is not None, "premise: the bridge built Helm > Set Course"
    return course


def _children(menu):
    # The base STMenu has no GetFirstChild/GetNextChild (a while-loop over
    # them spins on a truthy _Stub); read the AddChild list the way
    # engine.appc.warp's own Set Course walk does.
    return list(menu.__dict__.get("_children", []))


def test_the_set_course_menu_offers_the_ona_system():
    """REGRESSION (final review M1): the mission never called
    Systems.Ona.Ona.CreateMenus(), which is how every SDK mission (E6M1
    ResetSFAI: 'Add Ona to the helm menu') puts a system under Helm > Set
    Course -- so the classic menu had no way to fly between Ona's regions."""
    mh.setup_sdk()
    status, exc = mh.run_mission("engine.dev_missions.system_preview")
    assert status == "pass", exc
    course = _set_course_menu()

    systems = {m.GetRegionModule(): m for m in _children(course)}
    # CreateSystemMenu("Ona", "Systems.Ona.Ona3", ...) keys the system entry
    # on its second argument.
    ona = systems.get("Systems.Ona.Ona3")
    assert ona is not None, "Set Course has no Ona system entry: %r" % (
        sorted(systems),)
    regions = sorted(m.GetRegionModule() for m in _children(ona))
    assert regions == ["Systems.Ona.Ona1", "Systems.Ona.Ona2",
                       "Systems.Ona.Ona3"]
