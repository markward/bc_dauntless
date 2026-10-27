"""Quick Battle AI targeting for the condition stacks (spec
2026-10-27-quickbattle-victory-defeat-conditions-design §5.1-5.2).

Enemies weight every protected ship (every Defeat Ships Destroyed list) the
way BC's own E6M1 weights an escort target (Maelstrom/Episode6/E6M1/
E6M1.py:595-598): their attack AI targets an ObjectGroupWithInfo where each
protected ship has {"Priority": 2.0}, listed first, and every member of
pFriendlies {"Priority": 1.0}. Friendly NPCs get the mirror for every hunt
target (every Victory Ships Destroyed list) over pEnemies. SelectTarget adds
Priority x 1.0 to its rating (AI/Preprocessors.py:1564-1603). A side with no
listed ships keeps BC's stock target group, QuickBattle's pFriendlies /
pEnemies itself.

Headless against the real SDK QuickBattle, driven from the setup panel like
tests/host/test_qb_battle_end.py."""
import sys

import pytest

pytest.importorskip("_dauntless_host")

from tests.host.test_qb_battle_end import (  # noqa: E402
    _cond, _enemies, _group, _km, _names)
from tests.integration.test_quickbattle_setup_e2e import (  # noqa: E402,F401
    _do, _go, _ships, world)


def _builders(ship):
    from engine.appc import ai as aimod
    return [a for a in ship.GetAI().GetAllAIsInTree()
            if isinstance(a, aimod.BuilderAI)]


def _target_group(ship):
    """The group the ship's attack AI hands SelectTarget: BC's attack
    compounds (NonFedAttack, CloakAttack, ...) build it with
    ObjectGroup_ForceToGroup(lpTargets) and pass it to their BuilderAI as
    the "pAllTargetsGroup" dependency object."""
    groups = [v for b in _builders(ship)
              for _blk, k, v in b.GetDependencyObjects() if k == "pAllTargetsGroup"]
    assert groups, "no attack AI target group in %s's AI tree" % ship.GetName()
    first = groups[0]
    assert all(g is first for g in groups)
    return first


def _select_target(ship):
    """The ship's real SDK SelectTarget preprocessor, built the way the AI
    driver builds it on the first tick (BuilderAI activation, then the
    engine's CodeAISet substitute)."""
    from engine.appc import ai as aimod, ai_driver
    for b in _builders(ship):
        ai_driver._activate_builder(b)
    for a in ship.GetAI().GetAllAIsInTree():
        if isinstance(a, aimod.PreprocessingAI) and a.GetName() == "SelectTarget":
            inst = a._preprocessing_instance
            ai_driver._ensure_select_target_initialized(inst)
            return inst
    raise AssertionError("no SelectTarget in %s's AI tree" % ship.GetName())


def _put(ship, x, y, z):
    import App
    ship.SetTranslate(App.TGPoint3(x, y, z))
    ship.SetMatrixRotation(App.TGMatrix3())
    ship.UpdateNodeOnly()


def _player():
    import App
    return App.Game_GetCurrentGame().GetPlayer()


def _neutrals():
    import App
    return App.Game_GetCurrentGame().GetCurrentEpisode().GetCurrentMission() \
        .GetNeutralGroup()


def _is_weighted(group):
    import App
    return App.ObjectGroupWithInfo_Cast(group) is group


def _arrive_late(minutes=1):
    import App
    App.g_kTimerManager.tick(App.g_kUtopiaModule.GetGameTime() + 60.0 * minutes
                             + 1.0 - App.g_kTimerManager.get_time())


def _hunt(panel):
    """Enemies Keldon-1 and Galor-2, a friendly Akira-3, Victory ANY [Galor].
    The target is NOT pEnemies' first name, so a stock tie never favours it."""
    keldon, galor = _enemies(panel, "Keldon", "Galor")
    (akira,) = _group(panel, "friendly", "Akira")
    _cond(panel, "victory", "ships", [galor])
    names = _names()
    return names[keldon][0], names[galor][0], names[akira][0]


# ── enemies weight every protected ship ─────────────────────────────────────

def test_enemy_group_weights_every_protected_ship(world):
    hl, _c, panel, QB = world
    _enemies(panel, "Warbird")
    (freighter,) = _group(panel, "neutral", "Freighter")
    (akira,) = _group(panel, "friendly", "Akira")
    _cond(panel, "defeat", "ships", [freighter, akira])
    names = _names()
    freighter, akira = names[freighter][0], names[akira][0]
    _go(hl, panel)
    ships = _ships(QB)
    group = _target_group(ships["Warbird-1"])
    assert _is_weighted(group)
    # Both protected ships first, in listing order, then the player.
    assert group.GetNameTuple()[:2] == (freighter, akira)
    assert group[freighter] == {"Priority": 2.0}
    assert group[akira] == {"Priority": 2.0}
    assert group[_player().GetName()] == {"Priority": 1.0}
    from engine.quickbattle import km_targeting
    assert km_targeting.PROTECTED_TARGET_PRIORITY == 2.0     # E6M1's values
    assert km_targeting.OTHER_TARGET_PRIORITY == 1.0
    assert km_targeting.enemy_target_group() is group
    # Exactly pFriendlies plus the neutral: nothing else is a target.
    assert set(group.GetNameTuple()) == set(QB.pFriendlies.GetNameTuple()) | {freighter}
    # No Victory target list: the friendlies' targeting stays stock.
    assert km_targeting.friendly_target_group() is None
    assert _target_group(ships[akira]) is QB.pEnemies


@pytest.mark.parametrize("allegiance,ship", [("neutral", "Transport"),
                                             ("friendly", "Akira")])
def test_enemy_prefers_protected_when_equal(world, allegiance, ship):
    """Equidistant, equally far off the Warbird's nose, nobody has hurt it
    and it has no current target: the SDK rating picks the protected ship."""
    hl, _c, panel, QB = world
    name = _km(panel, allegiance=allegiance, ship=ship)
    _go(hl, panel)
    ships = _ships(QB)
    warbird, protected, player = ships["Warbird-1"], ships[name], _player()
    _put(warbird, 0.0, 0.0, 0.0)                 # nose along +Y
    _put(player, -10.0, 20.0, 0.0)
    _put(protected, 10.0, 20.0, 0.0)
    st = _select_target(warbird)
    warbird.SetTarget(None)
    assert st.dDamageReceived == {}
    assert st.FindGoodTarget() == name


# ── friendlies weight every hunt target ─────────────────────────────────────

def test_friendly_group_weights_targets(world):
    hl, _c, panel, QB = world
    keldon, galor, akira = _hunt(panel)
    _go(hl, panel)
    ships = _ships(QB)
    group = _target_group(ships[akira])
    assert _is_weighted(group)
    assert group.GetNameTuple()[0] == galor
    assert group[galor] == {"Priority": 2.0}
    assert group[keldon] == {"Priority": 1.0}
    assert set(group.GetNameTuple()) == set(QB.pEnemies.GetNameTuple())
    from engine.quickbattle import km_targeting
    assert km_targeting.friendly_target_group() is group
    # No Defeat list: the enemies' targeting stays stock.
    assert km_targeting.enemy_target_group() is None
    assert _target_group(ships[galor]) is QB.pFriendlies
    # pEnemies, the mission's IFF group, is never the weighted group.
    assert group is not QB.pEnemies


def test_friendly_prefers_target_when_equal(world):
    hl, _c, panel, QB = world
    keldon, galor, akira = _hunt(panel)
    _go(hl, panel)
    ships = _ships(QB)
    _put(ships[akira], 0.0, 0.0, 0.0)             # nose along +Y
    _put(ships[keldon], -10.0, 20.0, 0.0)
    _put(ships[galor], 10.0, 20.0, 0.0)
    _put(_player(), 0.0, -400.0, 0.0)
    st = _select_target(ships[akira])
    ships[akira].SetTarget(None)
    assert st.dDamageReceived == {}
    assert st.FindGoodTarget() == galor


def test_no_conditions_targeting_is_stock(world):
    hl, _c, panel, QB = world
    _enemies(panel, "Warbird")
    (akira,) = _group(panel, "friendly", "Akira")
    akira = _names()[akira][0]
    _go(hl, panel)
    ships = _ships(QB)
    assert _target_group(ships["Warbird-1"]) is QB.pFriendlies
    assert _target_group(ships[akira]) is QB.pEnemies
    from engine.quickbattle import km_targeting
    assert km_targeting.enemy_target_group() is None
    assert km_targeting.friendly_target_group() is None
    assert km_targeting._wrapped == []


def test_neutral_protected_keeps_neutral_affiliation(world):
    hl, _c, panel, QB = world
    name = _km(panel, allegiance="neutral", ship="Transport")
    _go(hl, panel)
    assert not QB.pFriendlies.IsNameInGroup(name)
    assert not QB.pEnemies.IsNameInGroup(name)
    assert _neutrals().IsNameInGroup(name)
    # The enemies' group is its own object, never the IFF group.
    assert _target_group(_ships(QB)["Warbird-1"]) is not QB.pFriendlies


# ── late arrivals ───────────────────────────────────────────────────────────

def test_late_arrivals_join_groups(world):
    """A late friendly joins the enemies' group at 1.0; a late hunt target
    joins the friendlies' group at 2.0 as its FIRST name, so friendlies built
    from now on start on it (NonFedAttack.py:11)."""
    hl, _c, panel, QB = world
    protected = _km(panel, allegiance="neutral", ship="Transport")
    (akira,) = _group(panel, "friendly", "Akira")
    (late_friend,) = _group(panel, "friendly", "Akira", warp_in=1)
    (late_target,) = _group(panel, "enemy", "Galor", warp_in=1)
    _cond(panel, "victory", "ships", [late_target])
    names = _names()
    akira, late_friend, late_target = (names[akira][0], names[late_friend][0],
                                       names[late_target][0])
    _go(hl, panel)
    ships = _ships(QB)
    enemy_group = _target_group(ships["Warbird-1"])
    friendly_group = _target_group(ships[akira])
    assert _is_weighted(enemy_group) and _is_weighted(friendly_group)
    assert not enemy_group.IsNameInGroup(late_friend)
    assert not friendly_group.IsNameInGroup(late_target)
    assert friendly_group["Warbird-1"] == {"Priority": 1.0}
    _arrive_late()
    ships = _ships(QB)
    assert late_friend in ships and late_target in ships
    assert enemy_group[late_friend] == {"Priority": 1.0}
    assert enemy_group[protected] == {"Priority": 2.0}
    assert friendly_group[late_target] == {"Priority": 2.0}
    assert friendly_group.GetNameTuple()[0] == late_target
    assert friendly_group["Warbird-1"] == {"Priority": 1.0}
    # The late ships' own AI got their side's weighted group.
    assert _target_group(ships[late_friend]) is friendly_group
    assert _target_group(ships[late_target]) is enemy_group


def test_late_protected_joins_first(world):
    hl, _c, panel, QB = world
    _enemies(panel, "Warbird")
    (transport,) = _group(panel, "neutral", "Transport", warp_in=1)
    _cond(panel, "defeat", "ships", [transport])
    transport = _names()[transport][0]
    _go(hl, panel)
    group = _target_group(_ships(QB)["Warbird-1"])
    assert _is_weighted(group)
    assert not group.IsNameInGroup(transport)
    _arrive_late()
    assert transport in _ships(QB)
    assert group[transport] == {"Priority": 2.0}
    assert group.GetNameTuple()[0] == transport
    assert group[_player().GetName()] == {"Priority": 1.0}
    assert not QB.pFriendlies.IsNameInGroup(transport)
    assert _neutrals().IsNameInGroup(transport)


# ── reset ───────────────────────────────────────────────────────────────────

def test_restart_into_no_conditions_is_stock(world):
    """battle_end.reset (End Combat, Restart, mission swap) leaves nothing
    that skews the next battle: a battle with both lists, then none."""
    hl, _c, panel, QB = world
    import App
    keldon, galor, akira = _hunt(panel)
    (akira_eid,) = [e for e, (n, _l) in _names().items() if n == akira]
    defeat = _cond(panel, "defeat", "ships", [akira_eid])
    victory = panel.scenario.victory.conditions[0].id
    _go(hl, panel)
    ships = _ships(QB)
    assert _target_group(ships[keldon]) is not QB.pFriendlies
    assert _target_group(ships[akira]) is not QB.pEnemies
    QB.EndSimulation()                         # End Combat
    from engine.quickbattle import km_targeting
    assert km_targeting.enemy_target_group() is None
    assert km_targeting.friendly_target_group() is None
    assert km_targeting._wrapped == []
    # The modules QuickBattle itself loaded. Never __import__ an AI module by
    # its bare name here: in a battle that did not load it, that leaves a
    # stray top-level module the next test's fresh SDK inherits (it stopped
    # test_quickbattle_station_defends' starbase from firing).
    for module in ("QuickBattle.QuickBattleAI", "QuickBattle.QuickBattleFriendlyAI"):
        assert not hasattr(sys.modules[module].CreateAI, km_targeting._ORIG_ATTR)
    _do(panel, "cond-remove:" + defeat, "cond-remove:" + victory)
    assert panel.scenario.victory.conditions == []
    _go(hl, panel)
    ships = _ships(QB)
    assert _target_group(ships[keldon]) is QB.pFriendlies
    assert _target_group(ships[akira]) is QB.pEnemies
    assert App.ObjectGroup_FromModule("QuickBattle.QuickBattle", "pFriendlies") \
        is QB.pFriendlies
    assert App.ObjectGroup_FromModule("QuickBattle.QuickBattle", "pEnemies") \
        is QB.pEnemies


def test_sync_failure_does_not_abort_ai_assignment(world, monkeypatch):
    """StartSimulation2's AI loop runs the wrapped CreateAI: a sync failing
    there is logged and the ship still gets its AI and the weighted group."""
    hl, _c, panel, QB = world
    from engine.quickbattle import km_targeting
    real, calls = km_targeting.sync, []

    def flaky(qb):
        calls.append(1)
        if len(calls) > 1:                 # arm's own sync succeeds
            raise RuntimeError("sync failed")
        return real(qb)
    name = _km(panel, allegiance="neutral", ship="Transport")
    monkeypatch.setattr(km_targeting, "sync", flaky)
    _go(hl, panel)
    assert len(calls) > 1                  # the CreateAI wrapper's sync ran
    warbird = _ships(QB)["Warbird-1"]
    assert warbird.GetAI() is not None
    assert _target_group(warbird)[name] == {"Priority": 2.0}
