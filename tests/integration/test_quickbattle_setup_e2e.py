"""Headless: panel -> start -> spawn -> win / loss -> End Combat keeps the setup."""
import pytest

pytest.importorskip("_dauntless_host")

from tests.host.test_quickbattle_boot import _fresh_quickbattle_loader  # noqa: E402


@pytest.fixture
def world(monkeypatch, tmp_path):
    hl, controller = _fresh_quickbattle_loader(monkeypatch)
    controller.loader.load_quickbattle()
    from engine.quickbattle import presets
    from engine.ui.quick_battle_setup_panel import QuickBattleSetupPanel
    panel = QuickBattleSetupPanel(on_start=lambda: controller.loader.start_quickbattle(),
                                  presets=presets.load_presets(tmp_path / "p.json"))
    panel.open()
    panel.render_payload()
    import QuickBattle.QuickBattle as QB
    yield hl, controller, panel, QB
    from engine.quickbattle import spawn
    spawn.set_provider(None)


def _do(panel, *actions):
    for a in actions:
        assert panel.dispatch_event(a) is True, a


def _go(hl, panel):
    import App
    _do(panel, "start")
    App.g_kTimerManager.tick(3.0)
    hl._fire_pending_preload_done()


def _destroy(QB, ship):
    import App
    evt = App.TGEvent_Create()
    evt.SetDestination(ship)
    QB.ShipDestroyed(None, evt)


def _ships(QB):
    import App
    return {s.GetName(): s for s in QB.g_pSet.GetClassObjectList(App.CT_DAMAGEABLE_OBJECT)}


def test_enemy_and_neutral_groups_then_win(world):
    hl, _c, panel, QB = world
    enemy = panel.scenario.groups[1]
    _do(panel, "add:Warbird", "group-new")
    g = panel.scenario.groups[-1]
    _do(panel, "details:" + g.id)
    for f, v in (("allegiance", "neutral"), ("direction", "port"), ("distance", "close")):
        _do(panel, "draft:%s:%s" % (f, v))
    _do(panel, "draft-update", "add:Transport")
    _go(hl, panel)
    ships = _ships(QB)
    assert "Warbird-1" in ships and "Transport-2" in ships
    assert QB.g_iNumEnemies == 1
    # Neutrals run no AI and never count (spec D6): no g_kShips row.
    assert ships["Transport-2"].GetObjID() not in QB.g_kShips
    assert ships["Warbird-1"].GetObjID() in QB.g_kShips
    # Groups by allegiance (spec §4.5 step 2).
    import App
    neutrals = App.Game_GetCurrentGame().GetCurrentEpisode().GetCurrentMission() \
        .GetNeutralGroup()
    assert QB.pEnemies.IsNameInGroup("Warbird-1")
    assert neutrals.IsNameInGroup("Transport-2")
    assert not QB.pEnemies.IsNameInGroup("Transport-2")
    assert not QB.pFriendlies.IsNameInGroup("Transport-2")
    # Positions where the Details say (spec §4.4): one ship per group sits on
    # its anchor, player_pos + axis * distance, the axes read off the player.
    from engine.units import GU_TO_KM
    player = App.Game_GetCurrentGame().GetPlayer()
    p = player.GetWorldLocation()
    rot = player.GetWorldRotation()
    fore, starboard = rot.GetCol(1), rot.GetCol(0)

    def at(ship, axis, sign, km):
        d = sign * km / GU_TO_KM
        w = ship.GetWorldLocation()
        want = (p.x + axis.x * d, p.y + axis.y * d, p.z + axis.z * d)
        assert (w.x, w.y, w.z) == pytest.approx(want, abs=1e-3), ship.GetName()

    at(ships["Warbird-1"], fore, +1.0, 35.0)            # Enemy fore Standard
    at(ships["Transport-2"], starboard, -1.0, 20.0)     # Neutral port Close
    _destroy(QB, ships["Transport-2"])               # a neutral: no effect on the win
    assert QB.bWonOrLost == 0
    _destroy(QB, ships["Warbird-1"])
    assert QB.g_iNumEnemies == 0 and QB.bWonOrLost == 1
    assert enemy is panel.scenario.groups[1]


def test_player_death_is_a_loss(world):
    hl, _c, panel, QB = world
    import App
    _do(panel, "add:Warbird")
    _go(hl, panel)
    assert QB.g_idTimer == App.NULL_ID and QB.bWonOrLost == 0
    _destroy(QB, App.Game_GetCurrentGame().GetPlayer())
    assert QB.g_idTimer                               # loss timer posted (QuickBattle.py:3304)


def test_end_combat_reverts_to_home_ship_but_keeps_the_setup(world):
    """Mark's home-ship ruling, 2026-10-02: End Combat puts the player back
    on the home ship (Galaxy), even though the setup screen keeps naming
    the battle ship it was started with."""
    hl, _c, panel, QB = world
    import App
    _do(panel, "set-player:Sovereign", "add:Warbird")
    before = panel.scenario.to_json()
    _go(hl, panel)
    assert QB.g_sPlayerType == "Sovereign"
    QB.EndSimulation()
    hl._process_object_deletions()
    assert QB.g_sPlayerType == "Galaxy"
    assert panel.scenario.to_json() == before
    player = App.Game_GetCurrentGame().GetPlayer()
    assert player is not None
    assert str(player.GetScript()).rsplit(".", 1)[-1] == "Galaxy"


def test_late_enemy_group_e2e(world):
    """Panel -> a second enemy group set to warp in at 1 min -> start: it is
    absent, counted, arrives with a flash on its minute, and only killing
    both groups wins (warp-in spec §6.5)."""
    hl, _c, panel, QB = world
    import App
    from engine.appc import warp_in_flash
    _do(panel, "add:Warbird", "group-new")
    g = panel.scenario.groups[-1]
    _do(panel, "details:" + g.id, "draft:allegiance:enemy", "draft:warp_in:1",
        "draft-update", "add:Galor")
    assert panel.scenario.group(g.id).warp_in_min == 1
    _go(hl, panel)
    t0 = App.g_kUtopiaModule.GetGameTime()
    ships = _ships(QB)
    assert "Warbird-1" in ships and "Galor-2" not in ships
    assert QB.g_iNumEnemies == 2 and QB.bWonOrLost == 0
    _destroy(QB, ships["Warbird-1"])
    assert QB.bWonOrLost == 0                         # the late Galor still counts
    flashes = warp_in_flash.spawned_count()
    App.g_kTimerManager.tick(t0 + 61.0 - App.g_kTimerManager.get_time())
    galor = _ships(QB).get("Galor-2")
    assert galor is not None
    assert warp_in_flash.spawned_count() == flashes + 1
    assert QB.pEnemies.IsNameInGroup("Galor-2")
    assert galor.GetAI() is not None
    _destroy(QB, galor)
    assert QB.g_iNumEnemies == 0 and QB.bWonOrLost == 1


def _km_group(panel, ship, allegiance, warp_in=0):
    """A second group holding `ship`; returns its entry id."""
    _do(panel, "group-new")
    g = panel.scenario.groups[-1]
    _do(panel, "details:" + g.id, "draft:allegiance:" + allegiance)
    if warp_in:
        _do(panel, "draft:warp_in:%d" % warp_in)
    _do(panel, "draft-update", "add:" + ship)
    return panel.scenario.group(g.id).entries[-1].id


def test_km_e2e_from_the_victory_view(world):
    hl, _c, panel, QB = world
    from engine.quickbattle import battle_end
    from engine.ui import target_markers
    _do(panel, "add:Warbird")
    entry = _km_group(panel, "Transport", "neutral")
    _do(panel, "victory-view", "victory-type:kobayashi_maru", "victory-protect:" + entry)
    _go(hl, panel)
    name = battle_end.state().protected_name
    assert name == "Transport-2"
    assert target_markers.marker_for(name) == "protect"
    _destroy(QB, _ships(QB)[name])
    st = battle_end.state()
    assert st.ended and st.won is False and st.reason == battle_end.REASON_PROTECTED


def test_xo_restart_rearms_from_current_plan(world):
    hl, _c, panel, QB = world
    import App
    from engine.quickbattle import battle_end
    _do(panel, "add:Warbird")
    entry = _km_group(panel, "Akira", "friendly", warp_in=1)
    _do(panel, "victory-type:kobayashi_maru", "victory-protect:" + entry)
    _go(hl, panel)
    assert "Akira-2" not in _ships(QB)

    class _Stub:
        def CallNextHandler(self, evt):
            pass

    QB.RestartSimulation(_Stub(), None)
    App.g_kTimerManager.tick(3.0)
    hl._fire_pending_preload_done()
    st = battle_end.state()
    assert st is not None and st.type == "kobayashi_maru" and not st.ended
    assert st.protected_name == "Akira-2"
    App.g_kTimerManager.tick(61.0)
    akira = _ships(QB).get("Akira-2")
    assert akira is not None
    _destroy(QB, akira)
    st = battle_end.state()
    assert st.ended and st.won is False and st.reason == battle_end.REASON_PROTECTED


def test_preset_km_round_trip_e2e(world, tmp_path):
    hl, controller, panel, QB = world
    from engine.quickbattle import battle_end, presets
    from engine.ui import target_markers
    from engine.ui.quick_battle_setup_panel import QuickBattleSetupPanel
    _do(panel, "add:Warbird")
    entry = _km_group(panel, "Transport", "neutral")
    _do(panel, "victory-type:kobayashi_maru", "victory-protect:" + entry,
        "preset-save:km")
    fresh = QuickBattleSetupPanel(on_start=lambda: controller.loader.start_quickbattle(),
                                  presets=presets.load_presets(tmp_path / "p.json"))
    fresh.open()
    fresh.render_payload()
    _do(fresh, "preset-load:km")
    assert fresh.scenario.victory.type == "kobayashi_maru"
    assert fresh.scenario.victory.protect == entry
    _go(hl, fresh)
    name = battle_end.state().protected_name
    assert name == "Transport-2"
    assert target_markers.marker_for(name) == "protect"
