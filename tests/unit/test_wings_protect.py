from engine.wings import dials, protect
from engine.wings.assess import ShipView


def setup_function(_):
    dials.reset()


def V(name, pos=(0, 0, 0), target=None, hull=1.0, shield=1.0):
    return ShipView(name, pos, hull, shield, 1.0, target=target)


def test_damage_rate_window():
    hist = [(0.0, 1.0), (6.0, 0.9), (8.0, 0.8), (10.0, 0.6)]
    assert abs(protect.damage_rate(hist, 10.0, 5.0) - (0.9 - 0.6) / 0.9) < 1e-9
    assert protect.damage_rate(hist[:1], 10.0, 5.0) == 0.0
    assert protect.damage_rate([(8.0, 0.0), (9.0, 0.0)], 10.0, 5.0) == 0.0


def test_damage_rate_never_negative():
    assert protect.damage_rate([(1.0, 0.5), (2.0, 0.9)], 2.0, 5.0) == 0.0


def test_attackers_of_reach_and_target():
    es = [V("a", (10, 0, 0), "p"), V("b", (10, 0, 0), "q"),
          V("c", (500, 0, 0), "p")]
    got = protect.attackers_of("p", es, (0, 0, 0), 350.0)
    assert [e.name for e in got] == ["a"]


def test_threatened_by_rate():
    a, b = V("a"), V("b")
    anchor = V("anchor")
    es = [V("ea", (5, 0, 0), "a"), V("eb", (5, 0, 0), "b")]
    assert protect.threatened([a, b], {"a": 0.05, "b": 0.2}, es, anchor).name == "b"
    assert protect.threatened([a, b], {"a": 0.05, "b": 0.1}, es, anchor) is None


def test_threatened_rate_alone_needs_an_attacker_in_reach():
    """Review I1: a damage rate with nobody in reach targeting the
    protectee (rocks, green alert, a fight past engage_gu) is no threat."""
    a = V("a")
    anchor = V("anchor")
    assert protect.threatened([a], {"a": 0.9}, [], anchor) is None
    far = [V("e", (1000, 0, 0), "a")]
    assert protect.threatened([a], {"a": 0.9}, far, anchor) is None
    other = [V("e", (5, 0, 0), "zz")]
    assert protect.threatened([a], {"a": 0.9}, other, anchor) is None
    near = [V("e", (5, 0, 0), "a")]
    assert protect.threatened([a], {"a": 0.9}, near, anchor).name == "a"


def test_threatened_by_attackers():
    a = V("a")
    es = [V("e%d" % i, (5, 0, 0), "a") for i in range(3)]
    assert protect.threatened([a], {"a": 0.0}, es, V("anchor")).name == "a"
    assert protect.threatened([a], {"a": 0.0}, es[:2], V("anchor")) is None


def test_threatened_ties():
    a, b = V("a"), V("b")
    es = [V("e%d" % i, (5, 0, 0), "b") for i in range(3)] + [
        V("ea", (5, 0, 0), "a")]
    anchor = V("anchor")
    assert protect.threatened([a, b], {"a": 0.2, "b": 0.2}, es, anchor).name == "b"
    one_each = [V("ea", (5, 0, 0), "a"), V("eb", (5, 0, 0), "b")]
    assert protect.threatened([b, a], {"a": 0.2, "b": 0.2}, one_each,
                              anchor).name == "a"


def test_pick_guards_healthiest_nearest_excludes():
    p = V("p", (0, 0, 0))
    ms = [V("far", (100, 0, 0)), V("near", (10, 0, 0)), V("hurt", (5, 0, 0)),
          V("cmd", (1, 0, 0)), V("p", (0, 0, 0))]
    frac = {"far": 1.0, "near": 0.9, "hurt": 0.3, "cmd": 1.0, "p": 1.0}
    assert protect.pick_guards(ms, p, {"cmd", "p"}, frac) == ["near"]


def test_guard_count_two_when_six():
    p = V("p")
    ms = [V("m%d" % i, (i + 1, 0, 0)) for i in range(6)]
    frac = {m.name: 1.0 for m in ms}
    assert protect.pick_guards(ms, p, set(), frac) == ["m0", "m1"]


def test_guard_point_capped_and_halfway():
    assert protect.guard_point((0, 0, 0), (100, 0, 0)) == (40.0, 0.0, 0.0)
    assert protect.guard_point((0, 0, 0), (20, 0, 0)) == (10.0, 0.0, 0.0)
    assert protect.guard_point((1, 2, 3), (1, 2, 3)) == (1, 2, 3)


def test_pick_guards_keeps_eligible_incumbent():
    """Review I3: a current guard keeps the role while still eligible; a
    nearer wingmate only fills a vacancy."""
    p = V("p")
    ms = [V("inc", (30, 0, 0)), V("near", (5, 0, 0))]
    frac = {"inc": 1.0, "near": 1.0}
    assert protect.pick_guards(ms, p, set(), frac) == ["near"]
    assert protect.pick_guards(ms, p, set(), frac, prev=["inc"]) == ["inc"]


def test_pick_guards_drops_ineligible_incumbent():
    p = V("p")
    ms = [V("inc", (30, 0, 0)), V("near", (5, 0, 0))]
    frac = {"inc": 1.0, "near": 1.0}
    assert protect.pick_guards(ms, p, {"inc"}, frac, prev=["inc"]) == ["near"]
    assert protect.pick_guards(ms, p, set(), {"inc": 0.3, "near": 1.0},
                               prev=["inc"]) == ["near"]
    gone = [V("near", (5, 0, 0))]
    assert protect.pick_guards(gone, p, set(), frac, prev=["inc"]) == ["near"]


def test_pick_guards_incumbents_fill_first_then_nearest():
    p = V("p")
    ms = [V("m%d" % i, (i + 1, 0, 0)) for i in range(6)]
    frac = {m.name: 1.0 for m in ms}
    assert protect.pick_guards(ms, p, set(), frac, prev=["m5"]) == ["m5", "m0"]


def test_pick_guards_skips_low_shields():
    """Review M1: full hull with shields under rotate_out_shield passes the
    strength-fraction bar but is a fall-back candidate, never a guard."""
    p = V("p")
    ms = [V("low", (5, 0, 0), shield=0.22), V("ok", (50, 0, 0))]
    frac = {"low": 0.61, "ok": 1.0}
    assert protect.pick_guards(ms, p, set(), frac) == ["ok"]
    assert protect.pick_guards(ms, p, set(), frac, prev=["low"]) == ["ok"]


def test_guard_count_zero_disables_guards_at_six():
    """Review M2: guard_count 0 switches guards off at any wing size."""
    dials._dials["guard_count"] = 0
    p = V("p")
    ms = [V("m%d" % i, (i + 1, 0, 0)) for i in range(6)]
    frac = {m.name: 1.0 for m in ms}
    assert protect.pick_guards(ms, p, set(), frac) == []
