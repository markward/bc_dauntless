import pytest

from engine.quickbattle import scenario as sc, victory as vc
from engine.quickbattle.scenario import VictoryOrder
from engine.quickbattle.victory import Victory


def _enemy(s):
    return s.groups[1]


def _with_escort():
    s = sc.default_scenario()
    g = s.add_group()
    s.update_details(g.id, "friendly", "port", "close", "medium")
    e1 = s.add_ship(g.id, "Akira")
    return s, g, e1


def test_default_is_elimination():
    assert sc.default_scenario().victory == Victory()


def test_can_start_needs_an_enemy():
    s = sc.default_scenario()
    s.add_ship(s.player_group().id, "Akira")
    assert s.can_start() is False
    assert vc.start_problem(s) == "Add an enemy ship to start"
    s.add_ship(_enemy(s).id, "Warbird")
    assert s.can_start() is True
    assert vc.start_problem(s) is None


def test_late_enemy_group_counts():
    s = sc.default_scenario()
    s.add_ship(_enemy(s).id, "Warbird")
    assert s.update_details(_enemy(s).id, "enemy", "fore", "standard", "medium",
                            warp_in_min=2)
    assert s.can_start() is True


def test_km_unavailable_without_candidate():
    s = sc.default_scenario()
    s.add_ship(_enemy(s).id, "Warbird")
    assert vc.unavailable_reason(s, "kobayashi_maru") == \
        "Add a friendly or neutral ship first"
    assert vc.set_type(s, "kobayashi_maru") is False
    assert s.victory.type == "elimination"
    assert vc.set_type(s, "nonsense") is False


def test_km_preselects_first_candidate():
    s, _g, e1 = _with_escort()
    n = s.add_group()
    s.update_details(n.id, "neutral", "aft", "close", "medium")
    n1 = s.add_ship(n.id, "Freighter")
    en = s.add_ship(_enemy(s).id, "Warbird")
    assert [e.id for _g2, e in vc.protect_candidates(s)] == [e1.id, n1.id]
    assert vc.set_type(s, "kobayashi_maru") is True
    assert s.victory.protect == e1.id
    assert vc.set_protect(s, n1.id) is True
    assert s.victory.protect == n1.id
    assert vc.set_protect(s, s.player_entry().id) is False
    assert vc.set_protect(s, en.id) is False
    assert s.victory.protect == n1.id


@pytest.mark.parametrize("edit", ["remove", "to_enemy"])
def test_km_falls_back_when_protected_ship_goes(edit):
    s, _g, e1 = _with_escort()
    vc.set_type(s, "kobayashi_maru")
    assert vc.reconcile(s) is None
    if edit == "remove":
        assert s.remove_entry(e1.id)
    else:
        assert s.move_entry(e1.id, _enemy(s).id)
    assert vc.reconcile(s) == \
        "Kobayashi Maru needs a ship to protect; switched to Elimination"
    assert s.victory.type == "elimination"
    assert vc.reconcile(s) is None


def test_json_round_trip_keeps_protect_id():
    s, _g, e1 = _with_escort()
    vc.set_type(s, "kobayashi_maru")
    vc.set_time_limit(s, 4)
    loaded = sc.from_json(s.to_json())
    assert loaded.victory == Victory("kobayashi_maru", e1.id, 4)
    assert sc.same_setup(s, loaded) is True


def test_same_setup_sees_victory_changes():
    s, g, e1 = _with_escort()
    e2 = s.add_ship(g.id, "Akira")
    vc.set_type(s, "kobayashi_maru")
    base = sc.from_json(s.to_json())
    assert sc.same_setup(s, base)
    other = sc.from_json(s.to_json())
    vc.set_protect(other, e2.id)
    assert not sc.same_setup(s, other)
    other = sc.from_json(s.to_json())
    vc.set_time_limit(other, 3)
    assert not sc.same_setup(s, other)
    other = sc.from_json(s.to_json())
    other.victory.type, other.victory.protect = "elimination", None
    assert not sc.same_setup(s, other)


def test_same_setup_ignores_entry_ids():
    s, _g, _e1 = _with_escort()
    vc.set_type(s, "kobayashi_maru")
    d = s.to_json()
    # a clone with fresh ids and protect re-pointed at the same position
    t = sc.from_json(d)
    old = {e.id: sc.new_id() for g in t.groups for e in g.entries}
    for g in t.groups:
        for e in g.entries:
            e.id = old[e.id]
    t.victory.protect = old[t.victory.protect]
    assert sc.same_setup(s, t)


def test_old_preset_without_victory_loads_as_elimination():
    d = sc.default_scenario().to_json()
    d.pop("victory")
    assert sc.from_json(d).victory == Victory()


def test_unknown_type_loads_as_elimination():
    d = sc.default_scenario().to_json()
    d["victory"] = {"type": "capture_the_flag", "protect": "x", "time_limit_min": 3}
    assert sc.from_json(d).victory == Victory()


def test_rule_text():
    s, _g, _e1 = _with_escort()
    vc.set_type(s, "kobayashi_maru")
    rule = ("You win when every enemy is destroyed. You lose if the ship you "
            "protect is destroyed, or you are.")
    assert vc.rule_text(s) == rule
    vc.set_time_limit(s, 5)
    assert vc.rule_text(s) == rule + " You also lose if time runs out."


def test_summary_suffix():
    s, _g, e1 = _with_escort()
    assert vc.summary_suffix(s, lambda e: "x") == ""
    vc.set_type(s, "kobayashi_maru")
    assert vc.summary_suffix(s, lambda e: "SS " + e.ship) == \
        " · Kobayashi Maru · protect SS Akira"


def test_battle_plan_carries_victory():
    from types import SimpleNamespace as NS
    s, _g, e1 = _with_escort()
    vc.set_type(s, "kobayashi_maru")
    vc.set_time_limit(s, 3)
    ce = lambda sid: NS(ship_id=sid, variants=[], title=sid, playable=True)
    index = {k.lower(): ce(k) for k in ("Galaxy", "Akira", "Warbird")}
    plan = sc.battle_plan(s, index)
    assert plan.victory == VictoryOrder("kobayashi_maru", e1.id, 180.0)
    assert plan.startable is False
    s.add_ship(_enemy(s).id, "Warbird")
    assert sc.battle_plan(s, index).startable is True


def _index():
    from types import SimpleNamespace as NS
    ce = lambda sid: NS(ship_id=sid, variants=[], title=sid, playable=True)
    return {k.lower(): ce(k) for k in ("Galaxy", "Akira", "Warbird")}


def test_elimination_clears_km_time_limit_and_protect():
    """Final review: KM 2 min, then Elimination, must not carry a hidden
    time limit (or protect) into the battle."""
    s, _g, _e1 = _with_escort()
    s.add_ship(_enemy(s).id, "Warbird")
    assert vc.set_type(s, "kobayashi_maru")
    assert vc.set_time_limit(s, 2)
    assert vc.set_type(s, "elimination")
    assert s.victory == Victory()
    v = sc.battle_plan(s, _index()).victory
    assert v.time_limit_s == 0 and v.protect_entry_id is None


def test_time_limit_refused_for_elimination():
    s, _g, _e1 = _with_escort()
    assert vc.set_time_limit(s, 3) is False
    assert s.victory == Victory()
    vc.set_type(s, "kobayashi_maru")
    assert vc.set_time_limit(s, 3) is True


def test_reconcile_fallback_clears_time_limit():
    s, _g, e1 = _with_escort()
    vc.set_type(s, "kobayashi_maru")
    vc.set_time_limit(s, 4)
    assert s.remove_entry(e1.id)
    assert vc.reconcile(s) is not None
    assert s.victory == Victory()


def test_battle_plan_drops_km_fields_for_other_types():
    """Defence in depth: whatever the scenario holds, only Kobayashi Maru
    gets a time limit and a ship to protect."""
    s, _g, e1 = _with_escort()
    s.add_ship(_enemy(s).id, "Warbird")
    s.victory = Victory("elimination", e1.id, 3)
    assert sc.battle_plan(s, _index()).victory == \
        VictoryOrder("elimination", None, 0.0)
