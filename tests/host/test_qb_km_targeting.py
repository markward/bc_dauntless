"""Kobayashi Maru enemy targeting (victory spec §5.2, live-check fix 1).

Enemies weight the protected ship the way BC's own E6M1 weights an escort
target (Maelstrom/Episode6/E6M1/E6M1.py:595-598): their attack AI targets an
ObjectGroupWithInfo where the protected ship has {"Priority": 2.0} and every
member of pFriendlies {"Priority": 1.0}. SelectTarget adds Priority x 1.0 to
its rating (AI/Preprocessors.py:1564-1603). Elimination keeps BC's stock
target group, QuickBattle's pFriendlies itself.

Headless against the real SDK QuickBattle, driven from the setup panel like
tests/host/test_qb_battle_end.py."""
import sys

import pytest

pytest.importorskip("_dauntless_host")

from tests.host.test_qb_battle_end import _km  # noqa: E402
from tests.integration.test_quickbattle_setup_e2e import (  # noqa: E402,F401
    _do, _go, _km_group, _ships, world)


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


def test_km_enemy_target_group_weights_protected(world):
    hl, _c, panel, QB = world
    import App
    name = _km(panel, allegiance="neutral", ship="Transport")
    _go(hl, panel)
    group = _target_group(_ships(QB)["Warbird-1"])
    assert App.ObjectGroupWithInfo_Cast(group) is group
    assert group[name] == {"Priority": 2.0}
    assert group[_player().GetName()] == {"Priority": 1.0}
    from engine.quickbattle import km_targeting
    assert km_targeting.PROTECTED_TARGET_PRIORITY == 2.0     # E6M1's values
    assert km_targeting.OTHER_TARGET_PRIORITY == 1.0
    # Exactly pFriendlies plus the protected ship: nothing else is a target.
    assert set(group.GetNameTuple()) == set(QB.pFriendlies.GetNameTuple()) | {name}


@pytest.mark.parametrize("allegiance,ship", [("neutral", "Transport"),
                                             ("friendly", "Akira")])
def test_km_enemy_prefers_protected_when_equal(world, allegiance, ship):
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


def test_km_enemy_initial_target_is_protected(world):
    """BC's attack compounds start on the group's FIRST name
    (NonFedAttack.py:11, CloakAttack.py:17), and that current target scores
    +1.0 (fIsTargetFactor) -- the same as the whole priority gap. The
    protected ship is first, so the head start goes to it, not the player."""
    hl, _c, panel, QB = world
    name = _km(panel, allegiance="neutral", ship="Transport")
    _go(hl, panel)
    warbird = _ships(QB)["Warbird-1"]
    assert _target_group(warbird).GetNameTuple()[0] == name
    assert _select_target(warbird).sCurrentTarget == name


def test_elimination_targeting_is_stock(world):
    hl, _c, panel, QB = world
    _do(panel, "add:Warbird")
    _go(hl, panel)
    assert _target_group(_ships(QB)["Warbird-1"]) is QB.pFriendlies


def test_km_friendly_npc_targeting_is_stock(world):
    hl, _c, panel, QB = world
    name = _km(panel, allegiance="friendly", ship="Akira")
    _go(hl, panel)
    assert _target_group(_ships(QB)[name]) is QB.pEnemies


def test_neutral_protected_keeps_neutral_affiliation(world):
    hl, _c, panel, QB = world
    name = _km(panel, allegiance="neutral", ship="Transport")
    _go(hl, panel)
    assert not QB.pFriendlies.IsNameInGroup(name)
    assert not QB.pEnemies.IsNameInGroup(name)
    assert _neutrals().IsNameInGroup(name)
    # The enemies' group is its own object, never the IFF group.
    assert _target_group(_ships(QB)["Warbird-1"]) is not QB.pFriendlies


def _arrive_late(QB, t0, minutes=1):
    import App
    App.g_kTimerManager.tick(t0 + 60.0 * minutes + 1.0 - App.g_kTimerManager.get_time())


def test_late_friendly_joins_km_targets(world):
    hl, _c, panel, QB = world
    import App
    name = _km(panel, allegiance="neutral", ship="Transport")
    _km_group(panel, "Akira", "friendly", warp_in=1)
    _go(hl, panel)
    t0 = App.g_kUtopiaModule.GetGameTime()
    group = _target_group(_ships(QB)["Warbird-1"])
    assert App.ObjectGroupWithInfo_Cast(group) is group
    assert not group.IsNameInGroup("Akira-3")
    _arrive_late(QB, t0)
    assert "Akira-3" in _ships(QB)
    assert group.IsNameInGroup("Akira-3")
    assert group["Akira-3"] == {"Priority": 1.0}
    assert group[name] == {"Priority": 2.0}


def test_late_enemy_gets_km_targets(world):
    hl, _c, panel, QB = world
    import App
    name = _km(panel, allegiance="neutral", ship="Transport")
    _km_group(panel, "Galor", "enemy", warp_in=1)
    _go(hl, panel)
    t0 = App.g_kUtopiaModule.GetGameTime()
    _arrive_late(QB, t0)
    galor = _ships(QB)["Galor-3"]
    group = _target_group(galor)
    assert App.ObjectGroupWithInfo_Cast(group) is group
    assert group is _target_group(_ships(QB)["Warbird-1"])
    assert group[name] == {"Priority": 2.0}


def test_late_protected_joins_km_targets_on_arrival(world):
    hl, _c, panel, QB = world
    import App
    _do(panel, "add:Warbird")
    entry = _km_group(panel, "Transport", "neutral", warp_in=1)
    _do(panel, "victory-type:kobayashi_maru", "victory-protect:" + entry)
    _go(hl, panel)
    t0 = App.g_kUtopiaModule.GetGameTime()
    group = _target_group(_ships(QB)["Warbird-1"])
    assert App.ObjectGroupWithInfo_Cast(group) is group
    assert not group.IsNameInGroup("Transport-2")
    _arrive_late(QB, t0)
    assert "Transport-2" in _ships(QB)
    assert group["Transport-2"] == {"Priority": 2.0}
    # First, like a start-of-battle protected ship: enemies built from now on
    # start on it (NonFedAttack.py:11), and nobody else lost their info.
    assert group.GetNameTuple()[0] == "Transport-2"
    assert group[_player().GetName()] == {"Priority": 1.0}
    assert not QB.pFriendlies.IsNameInGroup("Transport-2")
    assert _neutrals().IsNameInGroup("Transport-2")


def test_restart_into_elimination_is_stock(world):
    """battle_end.reset (End Combat, Restart, mission swap) leaves nothing
    that skews the next battle: a Kobayashi Maru battle, then Elimination."""
    hl, _c, panel, QB = world
    import App
    _km(panel, allegiance="neutral", ship="Transport")
    _go(hl, panel)
    assert _target_group(_ships(QB)["Warbird-1"]) is not QB.pFriendlies
    QB.EndSimulation()                         # End Combat
    from engine.quickbattle import km_targeting
    assert km_targeting.target_group() is None
    assert km_targeting._wrapped == []
    # The module QuickBattle itself loaded. Never __import__ an AI module by
    # its bare name here: in a battle that did not load it, that leaves a
    # stray top-level module the next test's fresh SDK inherits (it stopped
    # test_quickbattle_station_defends' starbase from firing).
    qbai = sys.modules["QuickBattle.QuickBattleAI"]
    assert not hasattr(qbai.CreateAI, km_targeting._ORIG_ATTR)
    _do(panel, "victory-type:elimination")
    _go(hl, panel)
    assert _target_group(_ships(QB)["Warbird-1"]) is QB.pFriendlies
    assert App.ObjectGroup_FromModule("QuickBattle.QuickBattle", "pFriendlies") \
        is QB.pFriendlies


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
