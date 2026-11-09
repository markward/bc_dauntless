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
    assert protect.threatened([a, b], {"a": 0.05, "b": 0.2}, [], anchor).name == "b"
    assert protect.threatened([a, b], {"a": 0.05, "b": 0.1}, [], anchor) is None


def test_threatened_by_attackers():
    a = V("a")
    es = [V("e%d" % i, (5, 0, 0), "a") for i in range(3)]
    assert protect.threatened([a], {"a": 0.0}, es, V("anchor")).name == "a"
    assert protect.threatened([a], {"a": 0.0}, es[:2], V("anchor")) is None


def test_threatened_ties():
    a, b = V("a"), V("b")
    es = [V("e%d" % i, (5, 0, 0), "b") for i in range(3)]
    anchor = V("anchor")
    assert protect.threatened([a, b], {"a": 0.2, "b": 0.2}, es, anchor).name == "b"
    assert protect.threatened([b, a], {"a": 0.2, "b": 0.2}, [], anchor).name == "a"


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
