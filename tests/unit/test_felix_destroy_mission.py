"""The "Felix: Destroy" dev mission -- baseline B2 run with nobody at the
keyboard (docs/engine/perf-register.md). Five Birds of Prey (the player and
four AI wingmen) against one Sovereign, Felix ordered to Destroy through the
real tactical button, and the run ends a few seconds after the first ship is
destroyed, or at a three-minute cap."""
import math

import App

from engine import dev_scripted_run as dsr
from engine.dev_missions import felix_destroy as fd
from tests.unit.test_optimized_fire_script_identity import _bridge_world, _mk_ship


def test_registered_in_the_developer_mission_picker():
    from engine.host_loop import _developer_family_entry
    modules = [m.module_name
               for ep in _developer_family_entry().episodes for m in ep.missions]
    assert "engine.dev_missions.felix_destroy" in modules


def test_five_birds_of_prey_the_player_and_four_ai_wingmen():
    assert fd.PLAYER_SHIP == "BirdOfPrey"
    assert fd.WINGMAN_SHIP == "BirdOfPrey"
    assert len(fd.WINGMAN_POSITIONS) == 4


def test_one_enemy_sovereign_ahead_of_the_player():
    assert fd.ENEMY_SHIP == "Sovereign"
    x, y, z = fd.ENEMY_POSITION
    assert y > 0.0, "the enemy starts ahead (+Y is forward)"


def test_nobody_spawns_inside_anybody_else():
    pts = [(0.0, 0.0, 0.0), fd.ENEMY_POSITION] + list(fd.WINGMAN_POSITIONS)
    for i, a in enumerate(pts):
        for b in pts[i + 1:]:
            assert math.dist(a, b) >= 4.0 * fd.NOMINAL_HULL_RADIUS_GU, (a, b)


def test_the_run_is_capped_at_three_minutes():
    assert fd.TIME_CAP_S == 180.0


def test_exterior_view_is_opt_in():
    assert fd.wants_exterior_view({}) is False
    assert fd.wants_exterior_view({"DAUNTLESS_DEV_VIEW": "exterior"}) is True


def test_autoquit_is_opt_in():
    assert fd.autoquit_enabled({}) is False
    assert fd.autoquit_enabled({"DAUNTLESS_DEV_AUTOQUIT": "0"}) is False
    assert fd.autoquit_enabled({"DAUNTLESS_DEV_AUTOQUIT": "1"}) is True


def test_felix_destroy_order_goes_through_the_real_tactical_button():
    """Not a hand-set order state: the Orders pane's own Destroy button is
    activated, so Bridge.TacticalMenuHandlers.Maneuver -> UpdateOrders ->
    StartAI run exactly as for a player click."""
    import Bridge.TacticalMenuHandlers as TMH

    from engine.appc.sets import SetClass_Create

    mission = _bridge_world()
    src = SetClass_Create()
    App.g_kSetManager.AddSet(src, "Src")
    player = _mk_ship("Player"); src.AddObjectToSet(player, "Player")
    App.Game_SetCurrentPlayer(player)
    far = _mk_ship("BoP-far"); far.SetTranslateXYZ(0.0, 300.0, 0.0)
    near = _mk_ship("BoP-near"); near.SetTranslateXYZ(0.0, 120.0, 0.0)
    src.AddObjectToSet(far, "BoP-far"); src.AddObjectToSet(near, "BoP-near")
    mission.GetEnemyGroup().AddName("BoP-far")
    mission.GetEnemyGroup().AddName("BoP-near")
    player.GetTorpedoSystem().TurnOn()
    player.GetPhaserSystem().TurnOn()

    target = fd.issue_destroy_order(player, ["BoP-far", "BoP-near"])

    assert target == "BoP-near", "Felix is pointed at the nearest enemy"
    assert player.GetTarget() is near
    assert TMH.GetHighLevelOrder() == "OrderDestroy"
    assert player.GetAI() is not None, "Felix's attack AI was not installed"


class _Evt:
    def __init__(self, obj):
        self._obj = obj

    def GetDestination(self):
        return self._obj


class _Named:
    def __init__(self, name):
        self._name = name

    def GetName(self):
        return self._name


def test_first_death_requests_the_quit_when_autoquit_is_on(monkeypatch):
    monkeypatch.setenv("DAUNTLESS_DEV_AUTOQUIT", "1")
    dsr.clear_quit_request()
    fd.reset_run_state()
    fd.ShipDestroyed(None, _Evt(_Named("BoP-3")))
    assert dsr.pending_quit_s() == fd.POST_DEATH_S
    # Only the FIRST death ends the run.
    dsr.tick_quit_request(1.0)
    fd.ShipDestroyed(None, _Evt(_Named("BoP-4")))
    assert dsr.pending_quit_s() == fd.POST_DEATH_S - 1.0
    dsr.clear_quit_request()


def test_a_death_never_quits_without_autoquit(monkeypatch):
    monkeypatch.delenv("DAUNTLESS_DEV_AUTOQUIT", raising=False)
    dsr.clear_quit_request()
    fd.reset_run_state()
    fd.ShipDestroyed(None, _Evt(_Named("BoP-3")))
    assert dsr.pending_quit_s() is None
