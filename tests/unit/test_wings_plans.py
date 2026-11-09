import random

from engine.wings import dials, plans
from engine.wings.assess import ShipView
from engine.wings.decisions import Choice


def V(name, x=0.0, hull=1.0):
    return ShipView(name, (x, 0.0, 0.0), hull, 1.0, 1.0)


def setup_function(_):
    dials.reset()


def test_reach_set_and_priorities():
    anchor = V("anc", 0)
    en = [V("a", 50), V("b", 100), V("c", 150), V("far", 500)]
    out = plans.target_priorities(en, anchor, Choice("a", ("b",)), {}, None)
    assert out == {"a": 3.0, "b": 1.5, "c": 0.0}


def test_km_priority_kept_and_maxed():
    anchor = V("anc", 0)
    en = [V("a", 50), V("b", 100), V("c", 150)]
    out = plans.target_priorities(en, anchor, Choice("a", ("b",)),
                                  {"a": 5.0, "b": 2.0, "c": 0.7}, None)
    assert out == {"a": 5.0, "b": 2.0, "c": 0.7}


def test_listed_ship_in_reach_outranks_decision_primary():
    """A km-listed ship (protect / hunt target) in reach is the primary: the
    decision's primary steps down to the first secondary. Ties on the km
    priority go to the nearer ship."""
    anchor = V("anc", 0)
    en = [V("a", 50), V("b", 100), V("c", 150), V("d", 160)]
    out = plans.target_priorities(en, anchor, Choice("a", ("b",)),
                                  {"c": 2.0, "d": 2.0}, None)
    assert out == {"c": 3.0, "a": 1.5, "b": 1.5, "d": 2.0}
    # No decision primary: still the listed ship.
    out = plans.target_priorities(en, anchor, Choice(None), {"d": 2.0}, None)
    assert out == {"a": 0.0, "b": 0.0, "c": 0.0, "d": 3.0}
    # The player commanding still decides.
    out = plans.target_priorities(en, anchor, Choice("a"), {"c": 2.0}, "b")
    assert out["b"] == 3.0 and out["c"] == 2.0


def test_nothing_in_reach_targets_nearest():
    anchor = V("anc", 0)
    en = [V("f1", 900), V("f2", 600)]
    out = plans.target_priorities(en, anchor, Choice(None), {}, None)
    assert out == {"f2": 3.0}
    assert plans.target_priorities([], anchor, Choice(None), {}, None) == {}


def test_player_target_overrides_primary():
    anchor = V("anc", 0)
    en = [V("a", 50), V("b", 100), V("c", 150)]
    out = plans.target_priorities(en, anchor, Choice("a", ("b", "c")), {},
                                  "b")
    assert out == {"a": 0.0, "b": 3.0, "c": 1.5}


def test_leaderless_priorities():
    assert plans.leaderless_priorities([V("a"), V("b")], {"a": 2.0}) == \
        {"a": 2.0, "b": 0.0}


def test_rejoin_hysteresis():
    anchor = V("anc", 0)
    ms = [V("m1", 250), V("m2", 250), V("m3", 310), V("m4", 190)]
    prev = {"m1": True, "m2": False, "m3": False, "m4": True}
    out = plans.rejoin_flags(ms, anchor, prev, False, "anc")
    assert out == {"m1": True, "m2": False, "m3": True, "m4": False}


def test_gather_holds_until_inside_gather():
    anchor = V("anc", 0)
    ms = [V("m1", 150), V("m2", 80)]
    out = plans.rejoin_flags(ms, anchor, {"m1": True, "m2": True}, True, "anc")
    assert out == {"m1": True, "m2": False}
    out = plans.rejoin_flags(ms, anchor, {}, True, "anc")
    assert out["m1"] is True


def test_commander_never_rejoins():
    anchor = V("anc", 0)
    ms = [V("anc", 900), V("me", 900), V("m", 900)]
    out = plans.rejoin_flags(ms, anchor, {"anc": True}, True, "anc",
                             player="me")
    assert out == {"anc": False, "me": False, "m": True}


def test_desperation_deterministic_and_once():
    ms = [V("b", hull=0.1), V("a", hull=0.2), V("c", hull=0.9)]
    one = plans.desperation(ms, {}, random.Random(7))
    two = plans.desperation(ms, {}, random.Random(7))
    assert one == two and set(one) == {"a", "b"}
    assert set(one.values()) <= {"ram", "flee"}
    assert plans.desperation(ms, dict(one), random.Random(7)) == {}
    r = random.Random(7)
    exp = {n: ("ram" if r.random() < 0.3 else "flee") for n in ("a", "b")}
    assert one == exp


def test_far_player_target_nothing_in_reach():
    anchor = V("anc", 0)
    en = [V("near", 600), V("far", 900)]
    out = plans.target_priorities(en, anchor, Choice(None), {}, "far")
    assert out == {"far": 3.0}


def test_far_player_target_with_others_in_reach():
    anchor = V("anc", 0)
    en = [V("a", 50), V("b", 100), V("far", 900)]
    out = plans.target_priorities(en, anchor, Choice("a", ("b",)), {}, "far")
    assert out == {"a": 0.0, "b": 1.5, "far": 3.0}


def test_choice_outside_reach_is_dropped():
    anchor = V("anc", 0)
    en = [V("a", 50), V("far", 900), V("far2", 800)]
    out = plans.target_priorities(en, anchor, Choice("far", ("far2",)), {},
                                  None)
    assert out == {"a": 0.0}
