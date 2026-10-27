"""Quick Battle battle end from the Victory / Defeat condition stacks (spec
2026-10-27-quickbattle-victory-defeat-conditions-design §4, §5), headless
against the real SDK QuickBattle, driven from the setup panel like
tests/integration/test_quickbattle_setup_e2e.py.

A battle ends the moment any victory or defeat condition is met: `battle_end`
posts BC's own ET_END_SIMULATION to the XO, int 2 for a win and 1 for a loss,
one second of game time later, exactly as QuickBattle.ShipDestroyed does for
the player's death. Inside that second a defeat condition overturns a pending
win; a pending loss is never overturned. Conditions are built through the
panel's cond-* verbs.

Time is advanced on the timer manager only (no AI, motion or combat), so a
now-group cannot kill the player while a test waits out a timer."""
import pytest

pytest.importorskip("_dauntless_host")

from tests.integration.test_quickbattle_setup_e2e import (  # noqa: E402,F401
    _destroy, _do, _go, _ships, world)

_PROTECTED_LOST = ("The ship we were assigned to protect has been destroyed. "
                   "Ending simulation.")
_PROTECTED_LOST_ALL = ("The ships we were assigned to protect have been "
                       "destroyed. Ending simulation.")
_TIME_UP = "We have run out of time. Ending simulation."
_SURVIVED = "Time is up. We held them off. Ending simulation."


# ── world helpers ───────────────────────────────────────────────────────────

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


def _enemies(panel, *ships):
    """Add `ships` to the default enemy group; their entry ids."""
    g = panel.scenario.groups[1]
    assert g.allegiance == "enemy"
    before = {e.id for e in g.entries}
    for s in ships:
        _do(panel, "add:%s:%s:1" % (s, g.id))
    return [e.id for e in panel.scenario.group(g.id).entries if e.id not in before]


def _group(panel, allegiance, *ships, warp_in=0):
    """A new group of `allegiance` holding `ships`; their entry ids."""
    _do(panel, "group-new")
    g = panel.scenario.groups[-1]
    _do(panel, "details:" + g.id, "draft:allegiance:" + allegiance,
        "draft:direction:port", "draft:distance:close")
    if warp_in:
        _do(panel, "draft:warp_in:%d" % warp_in)
    _do(panel, "draft-update")
    for s in ships:
        _do(panel, "add:%s:%s:1" % (s, g.id))
    return [e.id for e in panel.scenario.group(g.id).entries]


def _cond(panel, side, kind, entries=(), mode=None, minutes=None):
    """Add one condition through the panel verbs; its id."""
    _do(panel, "cond-add:%s:%s" % (side, kind))
    cid = panel.scenario.victory.conditions[-1].id
    if mode is not None:
        _do(panel, "cond-mode:%s:%s" % (cid, mode))
    for eid in entries:
        _do(panel, "cond-ship-add:%s:%s" % (cid, eid))
    if minutes is not None:
        _do(panel, "cond-minutes:%s:%d" % (cid, minutes))
    return cid


def _names():
    """entry id -> (object name, objective label) for the current plan:
    the object name is naming.object_name(title, n), the label
    `display_name or <object name>` (phase 1's rule)."""
    from engine.quickbattle import naming, spawn
    plan = spawn.current_plan()
    out = {}
    for n, o in enumerate(plan.orders, start=1):
        name = naming.object_name(o.title, n)
        out[o.entry_id] = (name, o.display_name or name)
    return out


def _km(panel, allegiance="friendly", ship="Akira", minutes=0):
    """Enemy Warbird-1 (the default enemy group) plus a second group holding
    `ship` (object name "<ship>-2") under a Defeat Ships Destroyed (ANY), and
    a Defeat Timer of `minutes` when non-zero: phase 1's Kobayashi Maru, built
    from the condition verbs. Used by tests/host/test_qb_km_targeting.py."""
    _enemies(panel, "Warbird")
    (eid,) = _group(panel, allegiance, ship)
    _cond(panel, "defeat", "ships", [eid])
    if minutes:
        _cond(panel, "defeat", "timer", minutes=minutes)
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


def _won(st, reason):
    return st is not None and st.ended and st.won is True and st.reason == reason


def _lost(st, reason):
    return st is not None and st.ended and st.won is False and st.reason == reason


# ── Victory: the default and Ships Destroyed ────────────────────────────────

def test_elimination_default_still_wins(world, monkeypatch):
    hl, _c, panel, QB = world
    import App
    from engine.quickbattle import battle_end
    said = _spoken(monkeypatch)
    _enemies(panel, "Warbird")
    _go(hl, panel)
    st = battle_end.state()
    assert st is not None and not st.ended and st.conditions == ()
    assert _objective_labels() == ["Destroy all enemy ships"]
    _destroy(QB, _ships(QB)["Warbird-1"])
    assert _won(battle_end.state(), battle_end.REASON_ELIMINATION)
    assert QB.bWonOrLost == 1
    assert QB.g_idTimer and _end_timers(QB) == [(QB.g_idTimer, 2)]
    # BC's own instant win lines are suppressed until the battle ends.
    assert (QB.g_pTact, "QBFelixWin") not in said
    top = App.TopWindow_GetTopWindow()
    top.ForceTacticalVisible()              # flying the battle in tactical
    _tick(battle_end.END_DELAY_S + 0.1)
    assert QB.bInSimulation == 0
    assert (QB.g_pTact, "QBFelixWin") in said
    assert QB.g_pXO.IsMenuUp() == 1
    # A win returns to the bridge, like GenerateLoseSequence.
    assert top.IsBridgeVisible() and not top.IsTacticalVisible()
    assert battle_end.state() is None


def test_victory_ships_any_wins_on_first_kill(world):
    hl, _c, panel, QB = world
    from engine.quickbattle import battle_end
    galor, keldon, _warbird = _enemies(panel, "Galor", "Keldon", "Warbird")
    _cond(panel, "victory", "ships", [galor, keldon], mode="any")
    names = _names()
    _go(hl, panel)
    assert battle_end.target_names() == [names[galor][0], names[keldon][0]]
    _destroy(QB, _ships(QB)[names[galor][0]])
    assert QB.g_iNumEnemies == 2                       # a third enemy is alive
    assert _won(battle_end.state(), battle_end.REASON_TARGETS)
    assert QB.bWonOrLost == 1 and _end_timers(QB) == [(QB.g_idTimer, 2)]


def test_victory_ships_all_needs_every_kill(world):
    hl, _c, panel, QB = world
    from engine.quickbattle import battle_end
    galor, keldon, _warbird = _enemies(panel, "Galor", "Keldon", "Warbird")
    _cond(panel, "victory", "ships", [galor, keldon], mode="all")
    names = _names()
    _go(hl, panel)
    ships = _ships(QB)
    _destroy(QB, ships[names[galor][0]])
    st = battle_end.state()
    assert not st.ended and QB.bWonOrLost == 0 and _end_timers(QB) == []
    assert st.conditions[0].destroyed == {names[galor][0]}
    _destroy(QB, ships[names[keldon][0]])
    assert _won(battle_end.state(), battle_end.REASON_TARGETS)
    assert _end_timers(QB) == [(QB.g_idTimer, 2)]


def test_victory_all_waits_for_late_target(world):
    """Review Focus 4: a Victory ALL list naming a late warp-in ship is not
    met until that ship has arrived and died."""
    hl, _c, panel, QB = world
    from engine.quickbattle import battle_end
    galor, _warbird = _enemies(panel, "Galor", "Warbird")
    (vorcha,) = _group(panel, "enemy", "Vorcha", warp_in=1)
    _cond(panel, "victory", "ships", [galor, vorcha], mode="all")
    names = _names()
    _go(hl, panel)
    t0 = _now()
    assert names[vorcha][0] not in _ships(QB)
    _destroy(QB, _ships(QB)[names[galor][0]])
    assert not battle_end.state().ended
    _jump_to(t0 + 61.0)
    late = _ships(QB).get(names[vorcha][0])
    assert late is not None
    assert not battle_end.state().ended
    _destroy(QB, late)
    assert QB.g_iNumEnemies == 1                       # the Warbird lives on
    assert _won(battle_end.state(), battle_end.REASON_TARGETS)


# ── Defeat: Ships Destroyed ─────────────────────────────────────────────────

def test_defeat_ships_any_loses(world, monkeypatch):
    hl, _c, panel, QB = world
    from engine.quickbattle import battle_end
    said = _spoken(monkeypatch)
    subs = _subtitles(monkeypatch)
    _enemies(panel, "Warbird")
    (freighter,) = _group(panel, "neutral", "Freighter")
    (akira,) = _group(panel, "friendly", "Akira")
    _cond(panel, "defeat", "ships", [freighter, akira], mode="any")
    names = _names()
    _go(hl, panel)
    assert battle_end.protected_names() == [names[freighter][0], names[akira][0]]
    _destroy(QB, _ships(QB)[names[akira][0]])
    assert _lost(battle_end.state(), battle_end.REASON_PROTECTED)
    assert QB.bWonOrLost == 1 and _end_timers(QB) == [(QB.g_idTimer, 1)]
    _tick(battle_end.END_DELAY_S + 0.1)
    assert QB.bInSimulation == 0
    assert (QB.g_pXO, "SaffiQBProtectedLost1") in said
    assert subs and subs[-1] == (QB.g_pXO.GetCharacterName(), _PROTECTED_LOST)


def test_defeat_ships_all_loses_on_last(world, monkeypatch):
    hl, _c, panel, QB = world
    from engine.quickbattle import battle_end
    said = _spoken(monkeypatch)
    subs = _subtitles(monkeypatch)
    _enemies(panel, "Warbird")
    (freighter,) = _group(panel, "neutral", "Freighter")
    (akira,) = _group(panel, "friendly", "Akira")
    _cond(panel, "defeat", "ships", [freighter, akira], mode="all")
    names = _names()
    _go(hl, panel)
    ships = _ships(QB)
    _destroy(QB, ships[names[freighter][0]])
    assert not battle_end.state().ended and _end_timers(QB) == []
    _destroy(QB, ships[names[akira][0]])
    assert _lost(battle_end.state(), battle_end.REASON_PROTECTED_ALL)
    assert _end_timers(QB) == [(QB.g_idTimer, 1)]
    _tick(battle_end.END_DELAY_S + 0.1)
    assert (QB.g_pXO, "SaffiQBProtectedLostAll1") in said
    assert subs and subs[-1] == (QB.g_pXO.GetCharacterName(), _PROTECTED_LOST_ALL)


def test_defeat_ships_all_with_one_ship_is_protected(world):
    hl, _c, panel, QB = world
    from engine.quickbattle import battle_end
    _enemies(panel, "Warbird")
    (freighter,) = _group(panel, "neutral", "Freighter")
    _cond(panel, "defeat", "ships", [freighter], mode="all")
    names = _names()
    _go(hl, panel)
    _destroy(QB, _ships(QB)[names[freighter][0]])
    assert _lost(battle_end.state(), battle_end.REASON_PROTECTED)


def test_ship_counts_in_every_condition_listing_it(world):
    """Review Focus 3: one ship in two Defeat conditions counts in both."""
    hl, _c, panel, QB = world
    from engine.quickbattle import battle_end
    _enemies(panel, "Warbird")
    (freighter,) = _group(panel, "neutral", "Freighter")
    (akira,) = _group(panel, "friendly", "Akira")
    _cond(panel, "defeat", "ships", [freighter], mode="all")
    _cond(panel, "defeat", "ships", [freighter, akira], mode="any")
    names = _names()
    fname = names[freighter][0]
    _go(hl, panel)
    _destroy(QB, _ships(QB)[fname])
    st = battle_end.state()
    assert _lost(st, battle_end.REASON_PROTECTED)
    assert [c.destroyed for c in st.conditions] == [{fname}, {fname}]
    assert _end_timers(QB) == [(QB.g_idTimer, 1)]


def test_same_named_stranger_does_not_count(world):
    """Only the protected ship that existed at begin counts: another object
    that happens to carry its name (here, a re-made one) does not."""
    hl, _c, panel, QB = world
    import App
    from engine.quickbattle import battle_end
    _enemies(panel, "Warbird")
    (freighter,) = _group(panel, "neutral", "Freighter")
    _cond(panel, "defeat", "ships", [freighter])
    names = _names()
    fname = names[freighter][0]
    _go(hl, panel)
    real = _ships(QB)[fname]

    class _Stranger:
        def GetName(self):
            return fname

        def GetObjID(self):
            return real.GetObjID() + 100000

    battle_end._guard("stranger", battle_end._before_bc, QB, _Stranger())
    assert not battle_end.state().ended and _end_timers(QB) == []
    assert App.ShipClass_GetObject(QB.g_pSet, fname) is not None


# ── a loss overturns a pending win; the player's death ──────────────────────

def test_defeat_after_pending_win_overturns_it(world, monkeypatch):
    """Review Focus 2: the protected Freighter dies 0.3 s after the last
    enemy, in that enemy's blast: the pending win becomes a loss."""
    hl, _c, panel, QB = world
    import App
    from engine.quickbattle import battle_end
    said = _spoken(monkeypatch)
    _enemies(panel, "Warbird")
    (freighter,) = _group(panel, "neutral", "Freighter")
    _cond(panel, "defeat", "ships", [freighter])
    names = _names()
    _go(hl, panel)
    ships = _ships(QB)
    _destroy(QB, ships["Warbird-1"])
    assert _won(battle_end.state(), battle_end.REASON_ELIMINATION)
    win_timer = QB.g_idTimer
    assert _end_timers(QB) == [(win_timer, 2)]
    _tick(0.3)
    _destroy(QB, ships[names[freighter][0]])
    assert _lost(battle_end.state(), battle_end.REASON_PROTECTED)
    assert _end_timers(QB) == [(QB.g_idTimer, 1)]
    assert win_timer not in App.g_kTimerManager._timers
    assert QB.bWonOrLost == 1
    _tick(battle_end.END_DELAY_S + 0.1)
    assert QB.bInSimulation == 0
    keys = [k for _c2, k in said]
    assert "SaffiQBProtectedLost1" in keys and "QBFelixWin" not in keys


def test_pending_loss_is_never_overturned(world):
    hl, _c, panel, QB = world
    from engine.quickbattle import battle_end
    _enemies(panel, "Warbird")
    (freighter,) = _group(panel, "neutral", "Freighter")
    _cond(panel, "defeat", "ships", [freighter])
    names = _names()
    _go(hl, panel)
    ships = _ships(QB)
    _destroy(QB, ships[names[freighter][0]])
    _destroy(QB, ships["Warbird-1"])
    assert _lost(battle_end.state(), battle_end.REASON_PROTECTED)
    assert QB.g_iNumEnemies == 0 and _end_timers(QB) == [(QB.g_idTimer, 1)]


def test_player_death_still_beats_pending_win(world, monkeypatch):
    hl, _c, panel, QB = world
    import App
    from engine.quickbattle import battle_end
    said = _spoken(monkeypatch)
    _enemies(panel, "Warbird")
    _go(hl, panel)
    _destroy(QB, _ships(QB)["Warbird-1"])
    ours = QB.g_idTimer
    assert _end_timers(QB) == [(ours, 2)]
    _destroy(QB, _player())
    assert _lost(battle_end.state(), battle_end.REASON_PLAYER)
    timers = _end_timers(QB)
    assert timers == [(QB.g_idTimer, 1)] and QB.g_idTimer != ours
    assert ours not in App.g_kTimerManager._timers
    _tick(battle_end.END_DELAY_S + 0.1)
    assert QB.bInSimulation == 0
    keys = [k for _c2, k in said]
    assert "QBComputerLose" in keys and "QBFelixWin" not in keys


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
    assert _lost(battle_end.state(), battle_end.REASON_PLAYER)
    timers = _end_timers(QB)
    assert len(timers) == 1 and timers[0][0] == QB.g_idTimer != ours
    assert ours not in App.g_kTimerManager._timers
    _tick(battle_end.END_DELAY_S + 0.1)
    keys = [k for _c2, k in said]
    assert "QBComputerLose" in keys and "SaffiQBProtectedLost1" not in keys


def test_protected_killed_by_player_fire_is_a_loss(world):
    """Quick Battle turns friendly-fire game over off, so the player's own
    phasers destroying a protected ship must still lose -- through the real
    damage path and death sequence, not a hand-made event."""
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
    assert _lost(battle_end.state(), battle_end.REASON_PROTECTED)
    assert _end_timers(QB) == [(QB.g_idTimer, 1)]


# ── Timers ──────────────────────────────────────────────────────────────────

def test_victory_timer_wins(world, monkeypatch):
    hl, _c, panel, QB = world
    import App
    from engine.quickbattle import battle_end
    said = _spoken(monkeypatch)
    subs = _subtitles(monkeypatch)
    _enemies(panel, "Warbird")
    _cond(panel, "victory", "timer", minutes=1)
    _go(hl, panel)
    t0 = _now()
    _jump_to(t0 + 59.0)
    assert not battle_end.state().ended
    _jump_to(t0 + 60.5)
    assert _won(battle_end.state(), battle_end.REASON_SURVIVED)
    assert QB.bWonOrLost == 1 and _end_timers(QB) == [(QB.g_idTimer, 2)]
    top = App.TopWindow_GetTopWindow()
    top.ForceTacticalVisible()
    _tick(battle_end.END_DELAY_S + 0.1)
    assert QB.bInSimulation == 0
    assert (QB.g_pXO, "SaffiQBSurvived1") in said
    assert (QB.g_pTact, "QBFelixWin") not in said
    assert subs and subs[-1] == (QB.g_pXO.GetCharacterName(), _SURVIVED)
    assert QB.g_pXO.IsMenuUp() == 1
    assert top.IsBridgeVisible() and not top.IsTacticalVisible()


def test_defeat_timer_loses(world, monkeypatch):
    hl, _c, panel, QB = world
    from engine.quickbattle import battle_end
    said = _spoken(monkeypatch)
    subs = _subtitles(monkeypatch)
    _enemies(panel, "Warbird")
    _cond(panel, "defeat", "timer", minutes=1)
    _go(hl, panel)
    t0 = _now()
    _jump_to(t0 + 60.5)
    assert _lost(battle_end.state(), battle_end.REASON_TIME)
    assert QB.bWonOrLost == 1 and _end_timers(QB) == [(QB.g_idTimer, 1)]
    _tick(battle_end.END_DELAY_S + 0.1)
    assert QB.bInSimulation == 0
    assert (QB.g_pXO, "SaffiQBTimeUp1") in said
    assert subs and subs[-1] == (QB.g_pXO.GetCharacterName(), _TIME_UP)


def test_equal_timers_lose(world):
    hl, _c, panel, QB = world
    from engine.quickbattle import battle_end
    _enemies(panel, "Warbird")
    _cond(panel, "victory", "timer", minutes=2)
    _cond(panel, "defeat", "timer", minutes=2)
    _go(hl, panel)
    t0 = _now()
    import App
    ours = [t.GetEvent().GetInt() for t in App.g_kTimerManager._timers.values()
            if t.GetEvent() is not None
            and t.GetEvent().GetEventType() == battle_end._ET]
    assert battle_end._DEFEAT_TIME_UP in ours
    assert battle_end._VICTORY_TIME_UP not in ours   # not earlier: not scheduled
    _jump_to(t0 + 120.5)
    assert _lost(battle_end.state(), battle_end.REASON_TIME)
    assert _end_timers(QB) == [(QB.g_idTimer, 1)]


def test_defeat_timer_overturns_pending_win(world):
    """A defeat timer running out inside the second after a win is a defeat
    condition met before the win is posted (spec §4.3)."""
    hl, _c, panel, QB = world
    from engine.quickbattle import battle_end
    _enemies(panel, "Warbird")
    _cond(panel, "defeat", "timer", minutes=1)
    _go(hl, panel)
    t0 = _now()
    _jump_to(t0 + 59.7)
    _destroy(QB, _ships(QB)["Warbird-1"])
    assert _won(battle_end.state(), battle_end.REASON_ELIMINATION)
    _jump_to(t0 + 60.2)
    assert _lost(battle_end.state(), battle_end.REASON_TIME)
    assert _end_timers(QB) == [(QB.g_idTimer, 1)]


def test_countdown_follows_earlier_timer(world, monkeypatch):
    hl, _c, panel, QB = world
    import App
    from engine.quickbattle import battle_end
    lines = _said_lines(monkeypatch)
    _enemies(panel, "Warbird")
    _cond(panel, "victory", "timer", minutes=3)
    _cond(panel, "defeat", "timer", minutes=7)
    _go(hl, panel)
    t0 = _now()
    sci = App.CharacterClass_GetObject(App.g_kSetManager.GetSet("bridge"),
                                       "Science").GetCharacterName()

    def countdown():
        return [(who, k) for who, k in lines if k.startswith("E8M2Countdown")]

    _jump_to(t0 + 0.5)
    assert countdown() == [(sci, "E8M2Countdown3")]
    _jump_to(t0 + 119.5)
    assert countdown() == [(sci, "E8M2Countdown3")]
    _jump_to(t0 + 120.5)
    assert countdown() == [(sci, "E8M2Countdown3"), (sci, "E8M2Countdown1")]
    _jump_to(t0 + 180.5)
    assert _won(battle_end.state(), battle_end.REASON_SURVIVED)
    assert countdown() == [(sci, "E8M2Countdown3"), (sci, "E8M2Countdown1")]


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


# ── markers, objectives, cleanup ────────────────────────────────────────────

def test_markers_and_objectives(world):
    hl, _c, panel, QB = world
    from engine.appc import mission_goals
    from engine.ui import target_markers
    from engine.quickbattle import battle_end
    (galor,) = _enemies(panel, "Galor")
    (freighter,) = _group(panel, "neutral", "Freighter")
    _cond(panel, "defeat", "ships", [freighter])
    _cond(panel, "victory", "ships", [galor])
    names = _names()
    (gname, glabel), (fname, flabel) = names[galor], names[freighter]
    assert fname == "Freighter-2"
    _go(hl, panel)
    assert target_markers.marker_for(fname) == "protect"
    assert target_markers.marker_for(gname) == "target"
    assert battle_end.protected_names() == [fname]
    assert battle_end.target_names() == [gname]
    assert mission_goals.objectives_submenu().IsVisible() == 1
    # The victory stack first (the default, then its conditions in the order
    # they were added), then the defeat stack.
    assert _objective_labels() == ["Destroy all enemy ships",
                                   "Destroy %s" % glabel, "Protect %s" % flabel]
    QB.EndSimulation()
    hl._process_object_deletions()
    assert target_markers.marker_for(fname) is None
    assert target_markers.marker_for(gname) is None
    menu = mission_goals.objectives_submenu()
    assert menu.GetNumChildren() == 0 and menu.IsVisible() == 0
    assert battle_end.protected_names() == [] and battle_end.target_names() == []
    _cond(panel, "victory", "timer", minutes=5)
    _cond(panel, "defeat", "timer", minutes=9)
    _go(hl, panel)
    assert _objective_labels() == ["Destroy all enemy ships",
                                   "Destroy %s" % glabel, "Survive for 5 min",
                                   "Protect %s" % flabel, "Win within 9 min"]


def test_objective_wording_for_lists(world):
    """ANY joins with "or" on Victory and "and" on Defeat, ALL the reverse;
    a Defeat ALL list of several reads "Keep ... alive"; more than three
    names shorten to "A, B, C and N more" (constraints, Rulings)."""
    hl, _c, panel, QB = world
    ve = _enemies(panel, "Galor", "Keldon", "Warbird", "Vorcha", "Galor")
    fe = _group(panel, "neutral", "Freighter", "Transport")
    _cond(panel, "victory", "ships", ve[:2], mode="any")
    _cond(panel, "victory", "ships", ve, mode="all")
    _cond(panel, "defeat", "ships", fe, mode="any")
    _cond(panel, "defeat", "ships", fe, mode="all")
    names = _names()
    v = [names[e][1] for e in ve]
    f = [names[e][1] for e in fe]
    _go(hl, panel)
    assert _objective_labels() == [
        "Destroy all enemy ships",
        "Destroy %s or %s" % (v[0], v[1]),
        "Destroy %s, %s, %s and 2 more" % (v[0], v[1], v[2]),
        "Protect %s and %s" % (f[0], f[1]),
        "Keep %s or %s alive" % (f[0], f[1]),
    ]


def test_end_combat_cancels_everything(world, monkeypatch):
    """End Combat with a timer and its countdown pending leaves nothing to
    fire into the next battle."""
    hl, _c, panel, QB = world
    from engine.appc import mission_goals
    from engine.quickbattle import battle_end
    from engine.ui import target_markers
    lines = _said_lines(monkeypatch)
    name = _km(panel)
    timer = _cond(panel, "defeat", "timer", minutes=2)
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
    # The next battle (no timer) must not inherit the old clock.
    _do(panel, "cond-remove:" + timer)
    _go(hl, panel)
    assert battle_end.state() is not None
    _jump_to(t0 + 130.0)
    assert lines == before
    assert _end_timers(QB) == [] and QB.bWonOrLost == 0
    st = battle_end.state()
    assert st is not None and st.ended is False


def test_end_combat_cancels_a_pending_end_timer(world, monkeypatch):
    """End Combat in the second between a win and its ending deletes our
    timer, so no win sequence plays later."""
    hl, _c, panel, QB = world
    said = _spoken(monkeypatch)
    _enemies(panel, "Warbird")
    _go(hl, panel)
    _destroy(QB, _ships(QB)["Warbird-1"])
    assert _end_timers(QB)
    QB.EndSimulation()
    hl._process_object_deletions()
    assert _end_timers(QB) == []
    _tick(2.0)
    assert (QB.g_pTact, "QBFelixWin") not in said


def test_late_arrivals_win_routes_through_battle_end(world):
    hl, _c, panel, QB = world
    from engine.quickbattle import battle_end, late_arrivals
    _enemies(panel, "Warbird")
    _go(hl, panel)
    assert _end_timers(QB) == []
    QB.g_iNumEnemies = 0                     # e.g. the last reinforcement failed
    late_arrivals.check_win(QB)
    assert _won(battle_end.state(), battle_end.REASON_ELIMINATION)
    assert QB.bWonOrLost == 1 and _end_timers(QB) == [(QB.g_idTimer, 2)]


def test_unarmed_battle_keeps_bc_win(world, monkeypatch):
    """A battle this module never armed keeps BC's own instant win branch
    (QuickBattle.py:3356-3367): a win leaves you flying, no end timer."""
    hl, _c, panel, QB = world
    from engine.quickbattle import battle_end
    said = _spoken(monkeypatch)
    _enemies(panel, "Warbird")
    _go(hl, panel)
    battle_end.reset()                        # as if begin never ran
    assert battle_end.state() is None
    _destroy(QB, _ships(QB)["Warbird-1"])
    assert battle_end.state() is None
    assert QB.bWonOrLost == 1 and QB.bInSimulation == 1
    assert _end_timers(QB) == []
    assert (QB.g_pTact, "QBFelixWin") in said


def test_install_is_idempotent(world):
    _hl, _c, _panel, QB = world
    from engine.quickbattle import battle_end
    fn = QB.ShipDestroyed
    assert getattr(fn, "_dauntless_battle_end_orig", None) is not None
    assert battle_end.install(QB) is False
    assert QB.ShipDestroyed is fn


class _Handler:
    """The pObject an SDK event handler is called with."""
    def CallNextHandler(self, _evt):
        pass


def test_restart_right_after_player_death_plays_no_lose_sequence(world, monkeypatch):
    """XO Restart inside the second between the player's death and BC's own
    loss timer. RestartSimulation reaches EndSimulation directly (only
    EndSimulationEvent deletes qb.g_idTimer), so the EndSimulation hook must
    delete BC's pending loss timer, or it fires into the restarted battle's
    load and plays the lose cutscene there."""
    hl, _c, panel, QB = world
    import App
    from engine.quickbattle import battle_end
    said = _spoken(monkeypatch)
    _enemies(panel, "Warbird")
    _go(hl, panel)
    _destroy(QB, _player())
    assert battle_end.state().reason == battle_end.REASON_PLAYER
    assert _end_timers(QB) == [(QB.g_idTimer, 1)]
    QB.RestartSimulation(_Handler(), None)
    App.g_kTimerManager.tick(3.0)
    hl._fire_pending_preload_done()
    assert "QBComputerLose" not in [k for _c2, k in said]
    assert _end_timers(QB) == []
    assert QB.g_idTimer == App.NULL_ID
    st = battle_end.state()
    assert QB.bInSimulation == 1 and st is not None and not st.ended
