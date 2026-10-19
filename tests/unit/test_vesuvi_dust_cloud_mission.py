"""The "Vesuvi Dust Cloud" dev mission -- baseline B3 run with nobody at the
keyboard (docs/engine/perf-register.md). The player Galaxy parked at
Vesuvi4's own "Player Start", facing into the cloud, immune to the cloud's
damage, no NPCs; with autoquit the run ends a fixed time after it settles.

Initialize() goes through the real harness, the same path a mission-picker
pick takes."""
import pytest

import App
import tools.mission_harness as mh
from engine import dev_scripted_run as dsr
from engine.dev_missions import vesuvi_dust_cloud as vdc
from engine.systems import system_loader

MODULE = "engine.dev_missions.vesuvi_dust_cloud"


def setup_function(_):
    App.g_kSetManager._sets.clear()
    App.g_kSetManager.ClearRenderedSet()
    system_loader.reset()
    dsr.clear_quit_request()


def teardown_function(_):
    App.g_kSetManager._sets.clear()
    App.g_kSetManager.ClearRenderedSet()
    system_loader.reset()
    dsr.clear_quit_request()


def _run():
    mh.setup_sdk()
    status, exc = mh.run_mission(MODULE)
    assert status == "pass", exc
    pSet = App.g_kSetManager.GetSet("Vesuvi4")
    assert pSet is not None, "the mission's own region must be up"
    player = pSet.GetObject("player")
    assert player is not None, "the mission must create the player in Vesuvi4"
    return pSet, player


def test_registered_in_the_developer_mission_picker():
    from engine.host_loop import _developer_family_entry
    modules = {m.module_name: m
               for ep in _developer_family_entry().episodes for m in ep.missions}
    assert MODULE in modules
    assert modules[MODULE].display_name == "Vesuvi Dust Cloud (B3 baseline)"


def test_the_player_galaxy_is_parked_at_vesuvi4s_player_start():
    _pSet, player = _run()
    assert vdc.PLAYER_SHIP == "Galaxy"
    p = player.GetWorldLocation()
    # Vesuvi4.py's "Player Start" waypoint: outside the cloud, facing in.
    assert (p.x, p.y, p.z) == pytest.approx((-1.702752, -335.755219, 0.174175))
    v = player.GetVelocityTG()
    assert (v.x, v.y, v.z) == pytest.approx((0.0, 0.0, 0.0))


def test_the_player_is_immune_to_the_clouds_damage():
    """The radiation drain and the nebula hits gate on IsImmuneToDamage, not
    on the God Mode cheat, so the mission sets BC's own immunity flag."""
    _pSet, player = _run()
    assert player.IsImmuneToDamage()


def test_no_ships_but_the_player_and_the_sets_own_rocks():
    from engine.rocks.rock import RockClass
    pSet, player = _run()
    others = [o for o in pSet.GetClassObjectList(App.CT_SHIP)
              if o.GetName() != "player"]
    assert others, "premise: Vesuvi4_S places its stock asteroids"
    assert all(isinstance(o, RockClass) for o in others), \
        [o.GetName() for o in others if not isinstance(o, RockClass)]


def test_the_run_settles_then_measures_for_a_fixed_time():
    assert vdc.SETTLE_S == 5.0
    assert vdc.MEASURE_S == 60.0


def test_settling_requests_the_quit_when_autoquit_is_on(monkeypatch):
    monkeypatch.setenv("DAUNTLESS_DEV_AUTOQUIT", "1")
    monkeypatch.delenv("DAUNTLESS_DEV_VIEW", raising=False)
    assert dsr.pending_quit_s() is None
    vdc.SettledAction(None)
    assert dsr.pending_quit_s() == vdc.MEASURE_S


def test_settling_never_quits_without_autoquit(monkeypatch):
    monkeypatch.delenv("DAUNTLESS_DEV_AUTOQUIT", raising=False)
    monkeypatch.delenv("DAUNTLESS_DEV_VIEW", raising=False)
    vdc.SettledAction(None)
    assert dsr.pending_quit_s() is None
