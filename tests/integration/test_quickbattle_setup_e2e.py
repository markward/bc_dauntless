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


def _group_of(panel, ship, allegiance, warp_in=0):
    """A new group holding `ship`; returns its entry id."""
    _do(panel, "group-new")
    g = panel.scenario.groups[-1]
    _do(panel, "details:" + g.id, "draft:allegiance:" + allegiance)
    if warp_in:
        _do(panel, "draft:warp_in:%d" % warp_in)
    _do(panel, "draft-update", "add:" + ship)
    return panel.scenario.group(g.id).entries[-1].id


def _cond(panel, side, kind, entries=(), mode=None, minutes=None):
    """One condition built through the panel verbs; its id."""
    _do(panel, "cond-add:%s:%s" % (side, kind))
    cid = panel.scenario.victory.conditions[-1].id
    if mode is not None:
        _do(panel, "cond-mode:%s:%s" % (cid, mode))
    for eid in entries:
        _do(panel, "cond-ship-add:%s:%s" % (cid, eid))
    if minutes is not None:
        _do(panel, "cond-minutes:%s:%d" % (cid, minutes))
    return cid


def _end_ints(QB):
    """Pending ET_END_SIMULATION timers' ints."""
    import App
    return [t.GetEvent().GetInt()
            for t in App.g_kTimerManager._timers.values()
            if t.GetEvent() is not None
            and t.GetEvent().GetEventType() == QB.ET_END_SIMULATION]


def _said(monkeypatch):
    import App
    said = []
    real = App.CharacterAction_Create

    def fake(char, kind, key="", *rest):
        said.append((char, key))
        return real(char, kind, key, *rest)
    monkeypatch.setattr(App, "CharacterAction_Create", fake)
    return said


def _hunt_setup(panel):
    """Enemy Galor + Keldon (the default enemy group), Victory Ships ANY
    [Galor]; returns (galor entry id, keldon entry id)."""
    g = panel.scenario.groups[1]
    _do(panel, "add:Galor:%s:1" % g.id, "add:Keldon:%s:1" % g.id)
    galor, keldon = [e.id for e in panel.scenario.group(g.id).entries]
    _cond(panel, "victory", "ships", [galor], mode="any")
    return galor, keldon


def test_hunt_scenario_end_to_end(world, monkeypatch):
    hl, _c, panel, QB = world
    from engine.appc import mission_goals
    from engine.quickbattle import battle_end
    from engine.ui import target_markers
    said = _said(monkeypatch)
    _hunt_setup(panel)
    _go(hl, panel)
    ships = _ships(QB)
    galor = next(n for n in ships if n.startswith("Galor"))
    assert target_markers.marker_for(galor) == "target"
    labels = mission_goals.objectives_submenu()
    assert labels.GetNumChildren() == 2          # the default + Destroy <Galor>
    _destroy(QB, ships[galor])
    st = battle_end.state()
    assert st.ended and st.won is True and st.reason == battle_end.REASON_TARGETS
    assert QB.g_iNumEnemies == 1                 # the Keldon is still alive
    assert _end_ints(QB) == [2]                  # ET_END_SIMULATION, a win
    import App
    App.g_kTimerManager.tick(battle_end.END_DELAY_S + 0.1)
    assert (QB.g_pTact, "QBFelixWin") in said
    QB.EndSimulation()
    hl._process_object_deletions()
    assert target_markers.marker_for(galor) is None
    menu = mission_goals.objectives_submenu()
    assert menu.GetNumChildren() == 0 and menu.IsVisible() == 0
    assert battle_end.state() is None


def test_three_protected_end_to_end(world, monkeypatch):
    hl, _c, panel, QB = world
    from engine.quickbattle import battle_end
    said = _said(monkeypatch)
    _do(panel, "add:Warbird")
    ids = [_group_of(panel, "Transport", "neutral") for _ in range(3)]
    _cond(panel, "defeat", "ships", ids, mode="any")
    _cond(panel, "defeat", "timer", minutes=2)
    _go(hl, panel)
    protected = battle_end.protected_names()
    assert len(protected) == 3
    _destroy(QB, _ships(QB)[protected[1]])
    st = battle_end.state()
    assert st.ended and st.won is False and st.reason == battle_end.REASON_PROTECTED
    assert _end_ints(QB) == [1]
    import App
    App.g_kTimerManager.tick(battle_end.END_DELAY_S + 0.1)
    assert (QB.g_pXO, "SaffiQBProtectedLost1") in said


def test_xo_restart_rearms_from_current_plan(world):
    hl, _c, panel, QB = world
    import App
    from engine.quickbattle import battle_end
    _do(panel, "add:Warbird")
    entry = _group_of(panel, "Akira", "friendly", warp_in=1)
    _cond(panel, "defeat", "ships", [entry])
    _go(hl, panel)
    assert "Akira-2" not in _ships(QB)

    class _Stub:
        def CallNextHandler(self, evt):
            pass

    QB.RestartSimulation(_Stub(), None)
    App.g_kTimerManager.tick(3.0)
    hl._fire_pending_preload_done()
    st = battle_end.state()
    assert st is not None and not st.ended
    assert battle_end.protected_names() == ["Akira-2"]
    App.g_kTimerManager.tick(61.0)
    akira = _ships(QB).get("Akira-2")
    assert akira is not None
    _destroy(QB, akira)
    st = battle_end.state()
    assert st.ended and st.won is False and st.reason == battle_end.REASON_PROTECTED


def test_preset_round_trip_end_to_end(world, tmp_path):
    hl, controller, panel, QB = world
    from engine.quickbattle import battle_end, presets, spawn
    from engine.ui.quick_battle_setup_panel import QuickBattleSetupPanel
    _hunt_setup(panel)
    _do(panel, "preset-save:hunt")
    saved = [(c.side, c.kind, c.mode, list(c.ships)) for c in panel.scenario.victory.conditions]
    fresh = QuickBattleSetupPanel(on_start=lambda: controller.loader.start_quickbattle(),
                                  presets=presets.load_presets(tmp_path / "p.json"))
    fresh.open()
    fresh.render_payload()
    _do(fresh, "preset-load:hunt")
    loaded = [(c.side, c.kind, c.mode, list(c.ships)) for c in fresh.scenario.victory.conditions]
    assert loaded and len(loaded) == len(saved)
    assert [x[:3] for x in loaded] == [x[:3] for x in saved]
    _go(hl, fresh)
    plan = spawn.current_plan()
    assert [(c.side, c.kind, c.mode) for c in plan.victory.conditions] == \
        [x[:3] for x in saved]
    assert len(plan.victory.conditions[0].entry_ids) == 1
    assert len(battle_end.target_names()) == 1
