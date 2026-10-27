"""Quick Battle victory and defeat condition stacks: the pure model.

Spec: docs/superpowers/specs/2026-10-27-quickbattle-victory-defeat-conditions-design.md
§3 (eligible ships, Start Battle, keeping conditions valid, presets), §4.1-4.2.
"""
from types import SimpleNamespace as NS

from engine.quickbattle import scenario as sc, victory as vc
from engine.quickbattle.scenario import ConditionOrder
from engine.quickbattle.victory import (ALL, ANY, DEFEAT, EMPTY_SHIPS_PROBLEM,
                                        NO_ENEMY_PROBLEM, SHIPS, TIMER, VICTORY,
                                        Condition, Victory)


def _setup():
    """Player group, an enemy Galor, a friendly Akira, then a neutral Freighter."""
    s = sc.default_scenario()
    galor = s.add_ship(s.groups[1].id, "Galor")
    fg = s.add_group()
    assert s.update_details(fg.id, "friendly", "port", "close", "medium")
    akira = s.add_ship(fg.id, "Akira")
    ng = s.add_group()
    assert s.update_details(ng.id, "neutral", "aft", "close", "medium")
    freighter = s.add_ship(ng.id, "Freighter")
    return NS(s=s, galor=galor, akira=akira, freighter=freighter, fg=fg, ng=ng)


def _ids(pairs):
    return [e.id for _g, e in pairs]


def _index(*ships):
    ce = lambda sid: NS(ship_id=sid, variants=[], title=sid, playable=True)
    return {k.lower(): ce(k) for k in ships}


def test_new_scenario_has_no_conditions():
    s = sc.default_scenario()
    assert s.victory.conditions == []
    assert vc.start_problem(s) == NO_ENEMY_PROBLEM
    s.add_ship(s.groups[1].id, "Galor")
    assert vc.start_problem(s) is None


def test_eligible_ships_by_side():
    t = _setup()
    assert _ids(vc.eligible(t.s, VICTORY)) == [t.galor.id]
    assert _ids(vc.eligible(t.s, DEFEAT)) == [t.akira.id, t.freighter.id]
    pid = t.s.player_entry().id
    assert pid not in _ids(vc.eligible(t.s, VICTORY)) + _ids(vc.eligible(t.s, DEFEAT))


def test_add_ships_condition_defaults():
    t = _setup()
    c = vc.add_condition(t.s, DEFEAT, SHIPS)
    assert isinstance(c, Condition)
    assert c.mode == ANY and c.ships == []
    assert vc.start_problem(t.s) == EMPTY_SHIPS_PROBLEM
    assert vc.add_ship(t.s, c.id, t.freighter.id) is True
    assert vc.start_problem(t.s) is None


def test_one_timer_per_side():
    t = _setup()
    first = vc.add_condition(t.s, VICTORY, TIMER)
    assert first is not None and first.minutes == 5
    assert vc.add_condition(t.s, VICTORY, TIMER) is None
    assert vc.add_condition(t.s, DEFEAT, TIMER) is not None
    assert vc.has_timer(t.s, VICTORY) and vc.has_timer(t.s, DEFEAT)


def test_add_ship_refuses_ineligible_and_duplicates():
    t = _setup()
    d = vc.add_condition(t.s, DEFEAT, SHIPS)
    v = vc.add_condition(t.s, VICTORY, SHIPS)
    assert vc.add_ship(t.s, d.id, t.galor.id) is False
    assert vc.add_ship(t.s, v.id, t.freighter.id) is False
    assert d.ships == [] and v.ships == []
    assert vc.add_ship(t.s, d.id, t.akira.id) is True
    assert vc.add_ship(t.s, d.id, t.akira.id) is False
    assert d.ships == [t.akira.id]


def test_set_minutes_bounds():
    t = _setup()
    c = vc.add_condition(t.s, DEFEAT, TIMER)
    for bad in (0, 61, "5", 5.0):
        assert vc.set_minutes(t.s, c.id, bad) is False
        assert c.minutes == 5
    assert vc.set_minutes(t.s, c.id, 1) is True and c.minutes == 1
    assert vc.set_minutes(t.s, c.id, 60) is True and c.minutes == 60


def test_set_mode_only_on_ships():
    t = _setup()
    timer = vc.add_condition(t.s, DEFEAT, TIMER)
    ships = vc.add_condition(t.s, DEFEAT, SHIPS)
    assert vc.set_mode(t.s, timer.id, "all") is False
    assert timer.mode == ANY
    assert vc.set_mode(t.s, ships.id, "all") is True and ships.mode == ALL
    assert vc.set_mode(t.s, ships.id, "both") is False and ships.mode == ALL


def test_reconcile_drops_removed_and_ineligible_ships():
    t = _setup()
    c = vc.add_condition(t.s, DEFEAT, SHIPS)
    assert vc.add_ship(t.s, c.id, t.freighter.id)
    assert vc.add_ship(t.s, c.id, t.akira.id)
    assert t.s.remove_entry(t.akira.id)
    assert t.s.update_details(t.ng.id, "enemy", "aft", "close", "medium")
    vc.reconcile(t.s)
    assert vc.find(t.s, c.id) is c
    assert c.ships == []
    assert vc.start_problem(t.s) == EMPTY_SHIPS_PROBLEM


def test_summary_suffix():
    t = _setup()
    assert vc.summary_suffix(t.s) == ""
    vc.add_condition(t.s, VICTORY, SHIPS)
    vc.add_condition(t.s, DEFEAT, SHIPS)
    vc.add_condition(t.s, DEFEAT, TIMER)
    assert vc.summary_suffix(t.s) == " · 1 victory · 2 defeat conditions"
    u = _setup()
    vc.add_condition(u.s, DEFEAT, TIMER)
    assert vc.summary_suffix(u.s) == " · 1 defeat condition"


def test_json_round_trip():
    t = _setup()
    a = vc.add_condition(t.s, VICTORY, SHIPS)
    vc.add_ship(t.s, a.id, t.galor.id)
    vc.set_mode(t.s, a.id, ALL)
    b = vc.add_condition(t.s, DEFEAT, TIMER)
    vc.set_minutes(t.s, b.id, 7)
    v = t.s.victory
    back = vc.from_json(vc.to_json(v))
    assert back == v
    assert [c.id for c in back.conditions] == [a.id, b.id]


def _fields(c):
    return (c.side, c.kind, c.mode, c.ships, c.minutes)


def test_phase1_kobayashi_maru_converts():
    v = vc.from_json({"type": "kobayashi_maru", "protect": "e1",
                      "time_limit_min": 3})
    assert [_fields(c) for c in v.conditions] == [
        (DEFEAT, SHIPS, ANY, ["e1"], 5),
        (DEFEAT, TIMER, ANY, [], 3),
    ]
    assert vc.from_json({"type": "elimination", "protect": None,
                         "time_limit_min": 0}).conditions == []


def test_malformed_condition_dropped_others_kept():
    good = {"id": "t1", "side": "victory", "kind": "timer", "mode": "any",
            "ships": [], "minutes": 4}
    v = vc.from_json({"conditions": [
        good,
        {"id": "x1", "side": "middle", "kind": "timer", "mode": "any",
         "ships": [], "minutes": 4},
        {"id": "x2", "side": "defeat", "kind": "ships", "mode": "any",
         "ships": "e1", "minutes": 5},
        {"id": "x3", "side": "defeat", "kind": "timer", "mode": "any",
         "ships": [], "minutes": 0},
        {"id": "x4", "side": "victory", "kind": "timer", "mode": "any",
         "ships": [], "minutes": 9},
    ]})
    assert [c.id for c in v.conditions] == ["t1"]
    assert v.conditions[0].minutes == 4


def test_battle_plan_carries_conditions():
    t = _setup()
    a = vc.add_condition(t.s, VICTORY, SHIPS)
    vc.set_mode(t.s, a.id, ALL)
    vc.add_ship(t.s, a.id, t.galor.id)
    b = vc.add_condition(t.s, DEFEAT, TIMER)
    vc.set_minutes(t.s, b.id, 2)
    plan = sc.battle_plan(t.s, _index("Galaxy", "Galor", "Akira", "Freighter"))
    assert plan.victory.conditions == (
        ConditionOrder("victory", "ships", "all", (t.galor.id,), 0.0),
        ConditionOrder("defeat", "timer", "any", (), 120.0),
    )


def test_battle_plan_drops_uncatalogued_ship_condition():
    t = _setup()
    c = vc.add_condition(t.s, DEFEAT, SHIPS)
    vc.add_ship(t.s, c.id, t.freighter.id)
    plan = sc.battle_plan(t.s, _index("Galaxy", "Galor", "Akira"))
    assert not any(o.side == DEFEAT and o.kind == SHIPS
                   for o in plan.victory.conditions)
    assert plan.victory.conditions == ()
