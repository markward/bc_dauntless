"""Quick Battle battle end (victory spec §4.1-4.5, §5.1-5.2), headless against
the real SDK QuickBattle, driven from the setup panel like
tests/integration/test_quickbattle_setup_e2e.py.

A win now ENDS the battle (BC leaves you flying): `battle_end` posts BC's own
ET_END_SIMULATION to the XO, int 2 for a win and 1 for a loss, one second of
game time later, exactly as QuickBattle.ShipDestroyed does for the player's
death. Kobayashi Maru adds a protected ship and an optional time limit.

Time is advanced on the timer manager only (no AI, motion or combat), so a
now-group cannot kill the player while a test waits out a time limit."""
import pytest

pytest.importorskip("_dauntless_host")

from tests.integration.test_quickbattle_setup_e2e import (  # noqa: E402,F401
    _destroy, _do, _go, _ships, world)

_PROTECTED_LOST = ("The ship we were assigned to protect has been destroyed. "
                   "Ending simulation.")
_TIME_UP = "We have run out of time. Ending simulation."


def _tick(dt):
    import App
    App.g_kTimerManager.tick(dt)


def _jump_to(t):
    import App
    dt = t - App.g_kTimerManager.get_time()
    if dt > 0:
        App.g_kTimerManager.tick(dt)


def _now():
    import App
    return App.g_kUtopiaModule.GetGameTime()


def _player():
    import App
    return App.Game_GetCurrentGame().GetPlayer()


def _km(panel, allegiance="friendly", ship="Akira", minutes=0):
    """Enemy Warbird-1 (the default enemy group) plus a second group holding
    `ship` (object name "<ship>-2"), protected, under Kobayashi Maru."""
    _do(panel, "add:Warbird", "group-new")
    g = panel.scenario.groups[-1]
    _do(panel, "details:" + g.id)
    for f, v in (("allegiance", allegiance), ("direction", "port"),
                 ("distance", "close")):
        _do(panel, "draft:%s:%s" % (f, v))
    _do(panel, "draft-update", "add:" + ship, "victory-type:kobayashi_maru")
    if minutes:
        _do(panel, "victory-time:%d" % minutes)
    return "%s-2" % ship


def _spoken(monkeypatch):
    """Every CharacterAction speech key created, with its character."""
    import App
    said = []
    real = App.CharacterAction_Create

    def fake(char, kind, key="", *rest):
        said.append((char, key))
        return real(char, kind, key, *rest)
    monkeypatch.setattr(App, "CharacterAction_Create", fake)
    return said


def _said_lines(monkeypatch):
    """(character name, line key) for every CharacterClass.SayLine call."""
    from engine.appc import characters
    said = []
    real = characters.CharacterClass.SayLine

    def spy(self, pDatabase=None, lineID="", *rest):
        said.append((self.GetCharacterName(), lineID))
        return real(self, pDatabase, lineID, *rest)
    monkeypatch.setattr(characters.CharacterClass, "SayLine", spy)
    return said


def _subtitles(monkeypatch):
    """(speaker, text) for every crew subtitle shown."""
    import App
    sub = App.TopWindow_GetTopWindow().FindMainWindow(App.MWT_SUBTITLE)
    got = []
    real = sub.set_crew_line

    def spy(speaker, text, *rest, **kw):
        got.append((speaker, text))
        return real(speaker, text, *rest, **kw)
    monkeypatch.setattr(sub, "set_crew_line", spy)
    return got


def _end_timers(QB):
    """Pending ET_END_SIMULATION timers: [(timer id, int)]."""
    import App
    return [(tid, t.GetEvent().GetInt())
            for tid, t in App.g_kTimerManager._timers.items()
            if t.GetEvent() is not None
            and t.GetEvent().GetEventType() == QB.ET_END_SIMULATION]


def _objective_labels():
    from engine.appc import mission_goals
    menu = mission_goals.objectives_submenu()
    assert menu is not None
    return [menu.GetNthChild(i).GetLabel() for i in range(menu.GetNumChildren())]


def test_elimination_win_ends_the_battle(world, monkeypatch):
    hl, _c, panel, QB = world
    from engine.quickbattle import battle_end
    said = _spoken(monkeypatch)
    _do(panel, "add:Warbird")
    _go(hl, panel)
    st = battle_end.state()
    assert st is not None and st.type == "elimination" and st.protected_name is None
    assert _objective_labels() == ["Destroy all enemy ships"]
    _destroy(QB, _ships(QB)["Warbird-1"])
    st = battle_end.state()
    assert st.ended and st.won is True and st.reason == battle_end.REASON_ELIMINATION
    assert QB.bWonOrLost == 1
    assert QB.g_idTimer and _end_timers(QB) == [(QB.g_idTimer, 2)]
    # BC's own instant win lines are suppressed until the battle ends.
    assert (QB.g_pTact, "QBFelixWin") not in said
    _tick(battle_end.END_DELAY_S + 0.1)
    assert QB.bInSimulation == 0
    assert (QB.g_pTact, "QBFelixWin") in said
    assert QB.g_pXO.IsMenuUp() == 1
    assert battle_end.state() is None


def test_km_protected_destroyed_is_a_loss(world, monkeypatch):
    hl, _c, panel, QB = world
    from engine.quickbattle import battle_end
    from engine.ui import target_markers
    subs = _subtitles(monkeypatch)
    name = _km(panel)
    _go(hl, panel)
    assert battle_end.state().protected_name == name
    assert target_markers.marker_for(name) == "protect"
    _destroy(QB, _ships(QB)[name])
    st = battle_end.state()
    assert st.ended and st.won is False and st.reason == battle_end.REASON_PROTECTED
    assert QB.bWonOrLost == 1 and _end_timers(QB) == [(QB.g_idTimer, 1)]
    _tick(battle_end.END_DELAY_S + 0.1)
    assert QB.bInSimulation == 0
    assert subs and subs[-1] == (QB.g_pXO.GetCharacterName(), _PROTECTED_LOST)


def test_km_protected_neutral_destroyed_is_a_loss(world):
    hl, _c, panel, QB = world
    from engine.quickbattle import battle_end
    name = _km(panel, allegiance="neutral", ship="Transport")
    _go(hl, panel)
    ship = _ships(QB)[name]
    assert ship.GetObjID() not in QB.g_kShips             # neutrals: no row
    _destroy(QB, ship)
    st = battle_end.state()
    assert st.ended and st.won is False and st.reason == battle_end.REASON_PROTECTED
    assert _end_timers(QB) == [(QB.g_idTimer, 1)]


def test_km_protected_killed_by_player_fire_is_a_loss(world):
    """Review Focus 3: Quick Battle turns friendly-fire game over off, so the
    player's own phasers destroying the protected ship must still lose --
    through the real damage path and death sequence, not a hand-made event."""
    hl, _c, panel, QB = world
    from engine.appc import combat, ship_death
    from engine.appc.math import TGPoint3
    from engine.quickbattle import battle_end
    name = _km(panel)
    _go(hl, panel)
    target, player = _ships(QB)[name], _player()
    for _ in range(200):
        if ship_death._out_of_action(target):
            break
        combat.apply_hit(target, damage=5000.0, hit_point=TGPoint3(0.0, 1.0, 0.0),
                         source=player, weapon_type="phaser")
    assert ship_death._out_of_action(target)
    assert battle_end.state().ended is False               # still in its throes
    ship_death.advance(ship_death.MAX_THROES_DURATION + 0.5)
    st = battle_end.state()
    assert st.ended and st.won is False and st.reason == battle_end.REASON_PROTECTED
    assert _end_timers(QB) == [(QB.g_idTimer, 1)]


def test_km_win_needs_protected_alive(world):
    hl, _c, panel, QB = world
    from engine.quickbattle import battle_end
    name = _km(panel)
    _go(hl, panel)
    ships = _ships(QB)
    # With the protected ship alive, killing every enemy wins.
    _destroy(QB, ships["Warbird-1"])
    st = battle_end.state()
    assert st.won is True and _end_timers(QB) == [(QB.g_idTimer, 2)]
    QB.EndSimulation()
    hl._process_object_deletions()
    # Next battle: the protected ship dies first, so the last enemy's death
    # is no longer a win -- the battle already ended as a loss.
    _go(hl, panel)
    ships = _ships(QB)
    _destroy(QB, ships[name])
    _destroy(QB, ships["Warbird-1"])
    st = battle_end.state()
    assert st.won is False and st.reason == battle_end.REASON_PROTECTED
    assert QB.g_iNumEnemies == 0 and QB.bWonOrLost == 1
    assert _end_timers(QB) == [(QB.g_idTimer, 1)]


def test_player_death_beats_protected_same_tick(world, monkeypatch):
    hl, _c, panel, QB = world
    import App
    from engine.quickbattle import battle_end
    said = _spoken(monkeypatch)
    name = _km(panel)
    _go(hl, panel)
    _destroy(QB, _ships(QB)[name])
    ours = QB.g_idTimer
    assert _end_timers(QB) == [(ours, 1)]
    _destroy(QB, _player())
    st = battle_end.state()
    assert st.ended and st.won is False and st.reason == battle_end.REASON_PLAYER
    timers = _end_timers(QB)
    assert len(timers) == 1 and timers[0][0] == QB.g_idTimer != ours
    assert ours not in App.g_kTimerManager._timers
    _tick(battle_end.END_DELAY_S + 0.1)
    assert QB.bInSimulation == 0
    keys = [k for _c2, k in said]
    assert "QBComputerLose" in keys and "SaffiQBProtectedLost1" not in keys


def test_time_limit_loses_and_counts_down(world, monkeypatch):
    hl, _c, panel, QB = world
    import App
    from engine.quickbattle import battle_end
    lines = _said_lines(monkeypatch)
    subs = _subtitles(monkeypatch)
    _km(panel, minutes=2)
    _go(hl, panel)
    t0 = _now()
    sci = App.CharacterClass_GetObject(App.g_kSetManager.GetSet("bridge"),
                                       "Science").GetCharacterName()

    def countdown():
        return [(who, k) for who, k in lines if k.startswith("E8M2Countdown")]

    # E8M2's even lines are about that mission's sun, so 2 min says nothing
    # until the 1-minute mark.
    _jump_to(t0 + 59.0)
    assert countdown() == []
    _jump_to(t0 + 60.5)
    assert countdown() == [(sci, "E8M2Countdown1")]
    assert battle_end.state().ended is False
    _jump_to(t0 + 120.5)
    st = battle_end.state()
    assert st.ended and st.won is False and st.reason == battle_end.REASON_TIME
    assert QB.bWonOrLost == 1 and _end_timers(QB) == [(QB.g_idTimer, 1)]
    _tick(battle_end.END_DELAY_S + 0.1)
    assert QB.bInSimulation == 0
    assert subs and subs[-1] == (QB.g_pXO.GetCharacterName(), _TIME_UP)


def test_end_combat_cancels_everything(world, monkeypatch):
    """Review Focus 4: End Combat with a time limit and its countdown pending
    leaves nothing to fire into the next battle."""
    hl, _c, panel, QB = world
    from engine.appc import mission_goals
    from engine.quickbattle import battle_end
    from engine.ui import target_markers
    lines = _said_lines(monkeypatch)
    name = _km(panel, minutes=2)
    _go(hl, panel)
    t0 = _now()
    assert battle_end.state() is not None
    QB.EndSimulation()
    hl._process_object_deletions()
    assert battle_end.state() is None
    menu = mission_goals.objectives_submenu()
    assert menu.GetNumChildren() == 0 and menu.IsVisible() == 0
    assert target_markers.marker_for(name) is None
    before = list(lines)
    _jump_to(t0 + 30.0)
    assert lines == before                        # no countdown after the end
    # The next battle (no time limit) must not inherit the old clock.
    _do(panel, "victory-time:0")
    _go(hl, panel)
    assert battle_end.state() is not None
    _jump_to(t0 + 130.0)
    assert lines == before
    assert _end_timers(QB) == [] and QB.bWonOrLost == 0
    st = battle_end.state()
    assert st is not None and st.ended is False


def test_end_combat_cancels_a_pending_end_timer(world, monkeypatch):
    """Review Focus 4, the end timer itself: End Combat in the second between
    a win and its ending deletes our timer, so no win sequence plays later."""
    hl, _c, panel, QB = world
    said = _spoken(monkeypatch)
    _do(panel, "add:Warbird")
    _go(hl, panel)
    _destroy(QB, _ships(QB)["Warbird-1"])
    assert _end_timers(QB)
    QB.EndSimulation()
    hl._process_object_deletions()
    assert _end_timers(QB) == []
    _tick(2.0)
    assert (QB.g_pTact, "QBFelixWin") not in said


def test_objectives_listed_for_km(world):
    hl, _c, panel, QB = world
    from engine.quickbattle import spawn
    name = _km(panel, minutes=3)
    plan = spawn.current_plan()
    order = next(o for o in plan.orders if o.entry_id == plan.victory.protect_entry_id)
    shown = order.display_name or name
    _go(hl, panel)
    from engine.appc import mission_goals
    assert mission_goals.objectives_submenu().IsVisible() == 1
    assert _objective_labels() == ["Destroy all enemy ships", "Protect %s" % shown,
                                   "Win within 3 min"]


def test_late_arrivals_win_routes_through_battle_end(world):
    hl, _c, panel, QB = world
    from engine.quickbattle import battle_end, late_arrivals
    _do(panel, "add:Warbird")
    _go(hl, panel)
    assert _end_timers(QB) == []
    QB.g_iNumEnemies = 0                     # e.g. the last reinforcement failed
    late_arrivals.check_win(QB)
    st = battle_end.state()
    assert st.won is True and st.reason == battle_end.REASON_ELIMINATION
    assert QB.bWonOrLost == 1 and _end_timers(QB) == [(QB.g_idTimer, 2)]


def test_install_is_idempotent(world):
    _hl, _c, _panel, QB = world
    from engine.quickbattle import battle_end
    fn = QB.ShipDestroyed
    assert getattr(fn, "_dauntless_battle_end_orig", None) is not None
    assert battle_end.install(QB) is False
    assert QB.ShipDestroyed is fn


def test_countdown_says_only_the_generic_minutes(world, monkeypatch):
    """A 10-minute limit hears 9, 7, 5, 3 and 1 minutes, in that order, and
    never E8M2's even, mission-specific lines."""
    hl, _c, panel, QB = world
    lines = _said_lines(monkeypatch)
    _km(panel, minutes=10)
    _go(hl, panel)
    t0 = _now()
    for m in range(10, 0, -1):
        _jump_to(t0 + (10 - m) * 60.0 + 0.5)
    keys = [k for _who, k in lines if k.startswith("E8M2Countdown")]
    assert keys == ["E8M2Countdown%d" % m for m in (9, 7, 5, 3, 1)]
