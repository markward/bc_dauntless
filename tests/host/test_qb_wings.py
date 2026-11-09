"""Quick Battle groups fight as wings (spec
2026-11-09-wing-leaders-phase-a-design.md §4, §11 "Quick Battle consumer").

One wing per non-neutral group, armed from battle_end.begin: members are the
ships spawned with QuickBattleAI / QuickBattleFriendlyAI (never station AI,
never neutrals), the player joins its group's wing first in the chain, and
every member's attack AI targets its wing's target group. km_targeting
composes on top: a listed ship's priority reaches the wing group. Late
arrivals join, outside the chain. End Combat and a mission swap put
everything back.

Headless against the real SDK QuickBattle, driven from the setup panel like
tests/host/test_qb_km_targeting.py."""
import sys

import pytest

pytest.importorskip("_dauntless_host")

from tests.host.test_qb_battle_end import (  # noqa: E402
    _cond, _enemies, _group, _km, _names)
from tests.host.test_qb_km_targeting import (  # noqa: E402
    _arrive_late, _hunt, _player, _put, _select_target, _target_group)
from tests.integration.test_quickbattle_setup_e2e import (  # noqa: E402,F401
    _do, _go, _ships, world)

_AI_MODULES = ("QuickBattle.QuickBattleAI", "QuickBattle.QuickBattleFriendlyAI")


def _wing_for(panel, group_index):
    from engine.wings import roster
    gid = panel.scenario.groups[group_index].id
    return next((w for w in roster.wings() if w.wing_id == "qb:" + gid), None)


def _add_to_player_group(panel, *ships):
    g = panel.scenario.groups[0]
    assert g.player
    before = {e.id for e in g.entries}
    for s in ships:
        _do(panel, "add:%s:%s:1" % (s, g.id))
    return [e.id for e in panel.scenario.group(g.id).entries if e.id not in before]


def _name_list(eids):
    names = _names()
    return [names[e][0] for e in eids]


def _is_wing_tree(ship):
    return ship.GetAI() is not None and ship.GetAI().GetName() == "WingPriorityList"


def _original_create_ai(module):
    """The SDK's own CreateAI under any wrappers (km on top of wings)."""
    from engine.quickbattle import km_targeting, wings_qb
    fn = module.CreateAI
    while True:
        inner = getattr(fn, km_targeting._ORIG_ATTR, None) \
            or getattr(fn, wings_qb._ORIG_ATTR, None)
        if inner is None:
            return fn
        fn = inner


# ── arming ──────────────────────────────────────────────────────────────────

def test_wings_armed_per_group(world):
    hl, _c, panel, QB = world
    from engine.wings import chain, roster, service
    escorts = _name_list(_add_to_player_group(panel, "Akira", "Akira", "Akira", "Akira"))
    first = _name_list(_enemies(panel, "Warbird", "Galor"))
    second = _name_list(_group(panel, "enemy", *(["Galor"] * 10)))
    _go(hl, panel)
    player = _player().GetName()
    wings = roster.wings()
    assert len(wings) == 3
    pw, w1, w2 = _wing_for(panel, 0), _wing_for(panel, 1), _wing_for(panel, 2)
    assert {pw.wing_id, w1.wing_id, w2.wing_id} == {w.wing_id for w in wings}
    # The player's wing: the player first, counted in the 20%.
    assert pw.members[player].is_player
    assert set(pw.members) == {player} | set(escorts)
    assert pw.chain == [player]                       # max(1, 5 // 5)
    assert pw.enemy_group is QB.pEnemies
    # Enemy wings: chains sized max(1, floor(0.2 * n)), all from members.
    assert set(w1.members) == set(first) and len(w1.chain) == chain.chain_size(2) == 1
    assert set(w2.members) == set(second) and len(w2.chain) == chain.chain_size(10) == 2
    assert set(w2.chain) <= set(second)
    assert w1.enemy_group is QB.pFriendlies and w2.enemy_group is QB.pFriendlies
    assert all(w.commander == w.chain[0] for w in wings)
    assert all(w in service._armed for w in wings)


def test_members_share_wing_target_group(world):
    hl, _c, panel, QB = world
    import App
    escorts = _name_list(_add_to_player_group(panel, "Akira"))
    first = _name_list(_enemies(panel, "Warbird", "Galor"))
    _go(hl, panel)
    ships = _ships(QB)
    pw, w1 = _wing_for(panel, 0), _wing_for(panel, 1)
    for name in first:
        assert _is_wing_tree(ships[name])
        assert _target_group(ships[name]) is w1.target_group
    for name in escorts:
        assert _is_wing_tree(ships[name])
        assert _target_group(ships[name]) is pw.target_group
    assert w1.target_group is not QB.pFriendlies
    assert set(w1.target_group.GetNameTuple()) == set(QB.pFriendlies.GetNameTuple())
    # The redirect lasted only for the CreateAI call.
    assert App.ObjectGroup_FromModule("QuickBattle.QuickBattle", "pFriendlies") \
        is QB.pFriendlies
    assert App.ObjectGroup_FromModule("QuickBattle.QuickBattle", "pEnemies") \
        is QB.pEnemies


def test_stations_and_neutrals_not_members(world):
    hl, _c, panel, QB = world
    from engine.wings import roster
    _enemies(panel, "Warbird")
    base, akira = _name_list(_group(panel, "friendly", "FedStarbase", "Akira"))
    (transport,) = _name_list(_group(panel, "neutral", "Transport"))
    _go(hl, panel)
    ships = _ships(QB)
    fw = _wing_for(panel, 2)
    assert set(fw.members) == {akira}
    assert roster.wing_of(base) is None
    assert not _is_wing_tree(ships[base])
    from engine.quickbattle import wings_qb
    assert not hasattr(sys.modules["QuickBattle.StarbaseFriendlyAI"].CreateAI,
                       wings_qb._ORIG_ATTR)                   # stock, unwrapped
    assert roster.wing_of(transport) is None
    assert _wing_for(panel, 3) is None                       # the neutral group
    assert len(roster.wings()) == 3


def test_km_priorities_reach_wing_group(world):
    hl, _c, panel, QB = world
    from engine.quickbattle import km_targeting
    from engine.wings import brain
    protected = _km(panel, allegiance="friendly", ship="Akira")
    _go(hl, panel)
    ships = _ships(QB)
    warbird = ships["Warbird-1"]
    ew = _wing_for(panel, 1)
    # km composed on top: the member still gets the WING's group.
    assert _target_group(warbird) is ew.target_group
    assert km_targeting.priorities_for("enemy") == {protected: 2.0}
    assert km_targeting.priorities_for("friendly") == {}
    _put(warbird, 0.0, 0.0, 0.0)
    _put(ships[protected], 10.0, 20.0, 0.0)
    _put(_player(), -10.0, 20.0, 0.0)
    brain.tick_wing(ew)
    assert ew.target_group[protected]["Priority"] >= 2.0


def test_all_late_wing_first_wave_commands(world):
    """Every order of a group shares its warp-in, so a late group is all
    late: its first arrival wave builds the chain and it never goes
    leaderless for want of one."""
    hl, _c, panel, QB = world
    from engine.wings import brain, roster
    _enemies(panel, "Warbird")
    late = _name_list(_group(panel, "enemy", "Galor", "Galor", warp_in=1))
    _go(hl, panel)
    lw = _wing_for(panel, 2)
    assert lw is not None and lw.members == {} and lw.chain == []
    _arrive_late()
    ships = _ships(QB)
    assert set(late) <= set(ships)
    assert set(lw.members) == set(late)
    assert all(roster.member(n).in_chain_eligible for n in late)
    assert lw.chain and set(lw.chain) <= set(late)
    assert lw.commander == lw.chain[0]
    for name in late:
        assert _is_wing_tree(ships[name])
        assert _target_group(ships[name]) is lw.target_group
    brain.tick_wing(lw)
    assert not lw.leaderless and lw.commander in late


def test_all_late_first_wave_is_its_first_mobile_arrivals(world):
    """An all-late wing whose earliest late order is immobile (a station
    given QuickBattleAI) builds its chain from its first MOBILE arrivals:
    the station never joins, so it must not fix the first wave."""
    hl, _c, panel, QB = world
    import dataclasses
    import loadspacehelper
    from engine.quickbattle import spawn, wings_qb
    from engine.wings import roster
    _enemies(panel, "Warbird")
    _group(panel, "enemy", "Galor", "Galor", warp_in=1)
    _go(hl, panel)
    plan = spawn.current_plan()
    gid = panel.scenario.groups[2].id
    first, second = [o for o in plan.orders if o.group_id == gid]
    station = dataclasses.replace(first, warp_in_s=first.warp_in_s / 2)
    plan = dataclasses.replace(plan, orders=tuple(
        station if o is first else o for o in plan.orders))
    wings_qb.arm(QB, plan)                  # the station's wave is earliest
    lw = _wing_for(panel, 2)
    assert lw.members == {}
    wings_qb.ship_arrived(QB, station, "Never-spawned")  # immobile: no ship
    assert roster.member("Never-spawned") is None
    loadspacehelper.CreateShip("Galor", QB.g_pSet, "Galor-w1", None, 0, 0)
    wings_qb.ship_arrived(QB, second, "Galor-w1")
    assert roster.member("Galor-w1").in_chain_eligible
    assert lw.chain == ["Galor-w1"] and lw.commander == "Galor-w1"


def test_later_wave_not_in_chain(world):
    """A wave after the first never enters the chain (spec §5)."""
    hl, _c, panel, QB = world
    import dataclasses
    import loadspacehelper
    from engine.quickbattle import spawn, wings_qb
    from engine.wings import roster
    _enemies(panel, "Warbird")
    (first,) = _name_list(_group(panel, "enemy", "Galor", warp_in=1))
    _go(hl, panel)
    _arrive_late()
    lw = _wing_for(panel, 2)
    assert lw.chain == [first]
    order = next(o for o in spawn.current_plan().orders
                 if o.group_id == panel.scenario.groups[2].id)
    later = dataclasses.replace(order, warp_in_s=order.warp_in_s + 60.0)
    loadspacehelper.CreateShip("Galor", QB.g_pSet, "Galor-late", None, 0, 0)
    wings_qb.ship_arrived(QB, later, "Galor-late")
    m = roster.member("Galor-late")
    assert m is not None and roster.wing_of("Galor-late") is lw
    assert not m.in_chain_eligible and lw.chain == [first]
    assert wings_qb.owns("Galor-late")


# ── listed ships keep their pull with wings on ──────────────────────────────

@pytest.mark.parametrize("allegiance,ship", [("neutral", "Transport"),
                                             ("friendly", "Akira")])
def test_enemy_wing_prefers_protected_when_equal(world, allegiance, ship):
    """The km intent with wings on: equidistant, equally far off the
    Warbird's nose, nobody has hurt it, no current target -- the enemy wing
    goes for the Defeat-protected ship, a neutral one included."""
    hl, _c, panel, QB = world
    from engine.wings import brain
    name = _km(panel, allegiance=allegiance, ship=ship)
    _go(hl, panel)
    ships = _ships(QB)
    warbird, protected, player = ships["Warbird-1"], ships[name], _player()
    ew = _wing_for(panel, 1)
    assert _target_group(warbird) is ew.target_group
    # Seeded before the first tick, at the member's CreateAI.
    assert ew.target_group.IsNameInGroup(name)
    _put(warbird, 0.0, 0.0, 0.0)                 # nose along +Y
    _put(player, -10.0, 20.0, 0.0)
    _put(protected, 10.0, 20.0, 0.0)
    st = _select_target(warbird)
    brain.tick_wing(ew)
    warbird.SetTarget(None)
    assert st.dDamageReceived == {}
    assert ew.target_group[name]["Priority"] >= 2.0
    assert st.FindGoodTarget() == name


def test_friendly_wing_prefers_hunt_target_when_equal(world):
    hl, _c, panel, QB = world
    from engine.wings import brain
    keldon, galor, akira = _hunt(panel)
    _go(hl, panel)
    ships = _ships(QB)
    fw = _wing_for(panel, 2)
    assert _target_group(ships[akira]) is fw.target_group
    _put(ships[akira], 0.0, 0.0, 0.0)             # nose along +Y
    _put(ships[keldon], -10.0, 20.0, 0.0)
    _put(ships[galor], 10.0, 20.0, 0.0)
    _put(_player(), 0.0, -400.0, 0.0)
    st = _select_target(ships[akira])
    brain.tick_wing(fw)
    ships[akira].SetTarget(None)
    assert st.dDamageReceived == {}
    assert st.FindGoodTarget() == galor


def test_immobile_quickbattleai_ship_not_a_member(world, monkeypatch):
    """A station given QuickBattleAI -- BC's own table does that for Biranu
    Station (not in the ship catalog), here the Card Station's row, which a
    mod could equally write -- has no impulse engine: not a member, stock
    tree, no redirect."""
    hl, _c, panel, QB = world
    from engine.wings import roster
    table = {k: (r[:3] + ["QuickBattleAI"] + r[4:]
                 if r[0] == "CardStation" else r)
             for k, r in QB.g_dEnemyShipTypeToDetails.items()}
    monkeypatch.setattr(QB, "g_dEnemyShipTypeToDetails", table)
    _enemies(panel, "Warbird")
    station, galor = _name_list(_group(panel, "enemy", "CardStation", "Galor"))
    _go(hl, panel)
    ships = _ships(QB)
    sw = _wing_for(panel, 2)
    assert set(sw.members) == {galor}
    assert roster.wing_of(station) is None
    assert not _is_wing_tree(ships[station])
    assert _target_group(ships[station]) is QB.pFriendlies


def test_reset_on_end_and_swap_clears_wings(world):
    hl, _c, panel, QB = world
    from engine.quickbattle import km_targeting, wings_qb
    from engine.wings import roster, service
    _km(panel, allegiance="friendly", ship="Akira")
    _go(hl, panel)
    mods = [sys.modules[m] for m in _AI_MODULES]
    origs = [_original_create_ai(m) for m in mods]
    assert all(m.CreateAI is not o for m, o in zip(mods, origs))
    assert roster.wings()
    QB.EndSimulation()                                       # End Combat
    assert roster.wings() == [] and service._armed == []
    assert all(m.CreateAI is o for m, o in zip(mods, origs))
    assert km_targeting._wrapped == [] and wings_qb._wrapped == []
    _go(hl, panel)
    assert roster.wings()
    assert all(m.CreateAI is not o for m, o in zip(mods, origs))
    hl.reset_mission_state(None)                             # mission swap
    assert roster.wings() == [] and service._armed == []
    assert all(m.CreateAI is o for m, o in zip(mods, origs))


def test_wings_off_is_stock(world, monkeypatch):
    hl, _c, panel, QB = world
    from engine.quickbattle import km_targeting
    from engine.wings import roster
    monkeypatch.setenv("DAUNTLESS_WINGS", "0")
    escort_eid = _add_to_player_group(panel, "Akira")
    warbird_eid = _enemies(panel, "Warbird")
    protected = _group(panel, "friendly", "Akira")
    _cond(panel, "defeat", "ships", protected)
    (escort,), (warbird,) = _name_list(escort_eid), _name_list(warbird_eid)
    _go(hl, panel)
    ships = _ships(QB)
    assert roster.wings() == []
    warbird = ships[warbird]
    assert warbird.GetAI().GetName() == "Wait"               # QuickBattleAI's root
    assert not _is_wing_tree(ships[escort])
    # km behaviour unchanged.
    assert _target_group(warbird) is km_targeting.enemy_target_group()
    assert _target_group(ships[escort]) is QB.pEnemies


def test_setup_switch_off_is_stock(world):
    """The setup screen's "Wing commanders" Off: plan.wings is False, so no
    wing is armed and every tree is the stock one, with wings enabled."""
    hl, _c, panel, QB = world
    from engine.quickbattle import wings_qb
    from engine.wings import roster, service
    assert service.enabled()
    (escort,) = _name_list(_add_to_player_group(panel, "Akira"))
    (warbird,) = _name_list(_enemies(panel, "Warbird"))
    _do(panel, "wings:off")
    _go(hl, panel)
    ships = _ships(QB)
    assert roster.wings() == [] and service._armed == []
    assert ships[warbird].GetAI().GetName() == "Wait"        # QuickBattleAI's root
    assert not _is_wing_tree(ships[escort])
    assert wings_qb._wrapped == []
