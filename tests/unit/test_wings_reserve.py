from engine.wings import dials, reserve
from engine.wings.assess import ShipView


def setup_function(_):
    dials.reset()


def V(name, hull=1.0, shield=1.0, power=1.0):
    return ShipView(name, (0, 0, 0), hull, shield, power)


def five(**over):
    return [over.get(n, V(n)) for n in "abcde"]


def test_pick_reserve_needs_min_wing():
    assert reserve.pick_reserve(five()[:4], None, set(), 5) is None


def test_pick_reserve_healthiest_noncommander():
    vs = five(a=V("a", 1.0, 1.0), b=V("b", 0.5, 0.5), c=V("c", 0.9, 0.9))
    vs[3] = V("d", 0.2, 0.2)
    vs[4] = V("e", 0.3, 0.3)
    assert reserve.pick_reserve(vs, "a", set(), 5) == "c"


def test_pick_reserve_tie_lowest_power_then_name():
    vs = [V("a", power=2.0), V("b", power=1.0), V("c", power=1.0),
          V("d", 0.1), V("e", 0.1)]
    assert reserve.pick_reserve(vs, None, set(), 5) == "b"


def test_pick_reserve_ignores_players():
    vs = five(a=V("a", 1.0, 1.0), b=V("b", 0.5, 0.5))
    assert reserve.pick_reserve(vs, None, {"a"}, 5) is None
    vs = five(a=V("a", 1.0, 1.0)) + [V("f", 0.1, 0.1)]
    assert reserve.pick_reserve(vs, None, {"a"}, 5) != "a"


def R(**kw):
    base = dict(lost_member=False, decision=None, primary_hull=None,
                ours=1.0, theirs=1.0, enemies_in_reach=1, held_s=0.0)
    base.update(kw)
    return reserve.commit_reason(**base)


def test_loss():
    assert R(lost_member=True) == "loss"


def test_protect():
    assert R(decision="protect") == "protect"


def test_finish():
    assert R(primary_hull=0.29) == "finish"
    assert R(primary_hull=0.3) is None


def test_advantage():
    assert R(ours=2.0, theirs=1.0) == "advantage"


def test_advantage_needs_enemy_in_reach():
    assert R(ours=10, theirs=0, enemies_in_reach=0) is None


def test_timeout():
    assert R(held_s=90.0) == "timeout"


def test_no_trigger_returns_none():
    assert R() is None


# ── where: the hold point ───────────────────────────────────────────────────

def _dist(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def test_hold_point_on_reserve_bearing_past_commander_range():
    """reserve_gu farther from the centroid than the commander, on the
    reserve's own bearing: a commander circling the enemy does not swing
    the point round (Task 6: the anchor's bearing outran the ship)."""
    p = reserve.hold_point((100.0, 0.0, 0.0), (0.0, -50.0, 0.0),
                           (0.0, 0.0, 0.0), 150.0)
    assert p == (0.0, -250.0, 0.0)
    assert _dist(p, (0.0, 0.0, 0.0)) == 100.0 + 150.0


def test_hold_point_behind_commander_when_on_its_line():
    p = reserve.hold_point((-100.0, 0.0, 0.0), (-120.0, 0.0, 0.0),
                           (0.0, 0.0, 0.0), 150.0)
    assert p == (-250.0, 0.0, 0.0)


def test_hold_point_no_enemy_ever_is_the_anchor():
    assert reserve.hold_point((5.0, 6.0, 7.0), (0.0, 0.0, 0.0),
                              (5.0, 6.0, 7.0), 150.0) == (5.0, 6.0, 7.0)


def test_hold_point_reserve_on_the_centroid_uses_commander_bearing():
    p = reserve.hold_point((-100.0, 0.0, 0.0), (0.0, 0.0, 0.0),
                           (0.0, 0.0, 0.0), 150.0)
    assert p == (-250.0, 0.0, 0.0)
