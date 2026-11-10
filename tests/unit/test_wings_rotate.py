from engine.wings import dials, rotate
from engine.wings.assess import ShipView


def setup_function(_):
    dials.reset()


def V(name, shield, hull=1.0):
    return ShipView(name, (0, 0, 0), hull, shield, 1.0)


def four(**sh):
    return [V(n, sh.get(n, 1.0), sh.get("h" + n, 1.0)) for n in "abcd"]


def test_fallback_out_and_back_hysteresis():
    out = rotate.fallback_flags(four(a=0.1), {}, 10.0, set())
    assert out["a"] == 10.0 and out["b"] is None
    out = rotate.fallback_flags(four(a=0.4), out, 12.0, set())
    assert out["a"] == 10.0
    out = rotate.fallback_flags(four(a=0.6), out, 13.0, set())
    assert out["a"] is None


def test_fallback_not_when_hull_desperate():
    out = rotate.fallback_flags(four(a=0.1, ha=0.2), {}, 1.0, set())
    assert out["a"] is None


def test_fallback_max_time():
    out = rotate.fallback_flags(four(a=0.1), {"a": 0.0}, 31.0, set())
    assert out["a"] is None


def test_cap_two_members_one_falls_back():
    vs = [V("a", 0.1), V("b", 0.05)]
    out = rotate.fallback_flags(vs, {}, 1.0, set())
    assert out["b"] == 1.0 and out["a"] is None


def test_cap_one_member_none():
    assert rotate.fallback_flags([V("a", 0.0)], {}, 1.0, set()) == {"a": None}


def test_cap_fraction_worst_first():
    vs = four(a=0.1, b=0.05, c=0.2)
    out = rotate.fallback_flags(vs, {}, 1.0, set())
    assert [n for n, t in out.items() if t is not None] == ["b"]


def test_fallback_excludes():
    out = rotate.fallback_flags(four(a=0.1), {"a": 0.0}, 1.0, {"a"})
    assert out["a"] is None


def test_fallback_point_behind_anchor():
    assert rotate.fallback_point((0, 0, 0), (10, 0, 0), 100.0) == (-100.0, 0.0, 0.0)


def test_timeout_return_not_reflagged_until_cooldown():
    cd = {}
    out = rotate.fallback_flags(four(a=0.1), {"a": 0.0}, 31.0, set(), cd)
    assert out["a"] is None
    out = rotate.fallback_flags(four(a=0.1), out, 32.0, set(), cd)
    assert out["a"] is None
    out = rotate.fallback_flags(four(a=0.1), out, 61.0, set(), cd)
    assert out["a"] == 61.0


def test_shield_recovery_return_can_reflag_immediately():
    cd = {}
    out = rotate.fallback_flags(four(a=0.7), {"a": 0.0}, 5.0, set(), cd)
    assert out["a"] is None and cd == {}
    out = rotate.fallback_flags(four(a=0.1), out, 6.0, set(), cd)
    assert out["a"] == 6.0


# ── weakest face and hull (Mark's B play test, 2026-11-10) ─────────────────

def F(name, shield=1.0, weak_face=None, hull=1.0):
    return ShipView(name, (0, 0, 0), hull, shield, 1.0, weak_face=weak_face)


def mates(a):
    return [a] + [F(n) for n in "bcd"]


def test_weakest_face_alone_triggers_fallback():
    """One face down with the mean still high: the side being hit counts."""
    out = rotate.fallback_flags(mates(F("a", 0.8, weak_face=0.1)), {}, 1.0,
                                set())
    assert out["a"] == 1.0


def test_stays_until_weakest_face_recovers():
    out = rotate.fallback_flags(mates(F("a", 0.9, weak_face=0.4)),
                                {"a": 0.0}, 5.0, set())
    assert out["a"] == 0.0
    out = rotate.fallback_flags(mates(F("a", 0.9, weak_face=0.6)), out, 6.0,
                                set())
    assert out["a"] is None


def test_view_without_weak_face_uses_mean():
    assert rotate.weak_face(F("a", 0.3)) == 0.3
    assert rotate.weak_face(F("a", 0.3, weak_face=0.1)) == 0.1


def test_hull_below_rotate_out_hull_falls_back_once():
    hs = {}
    a = F("a", hull=0.45)
    out = rotate.fallback_flags(mates(a), {}, 1.0, set(), {}, hs)
    assert out["a"] == 1.0 and hs == {"a": "active"}
    assert rotate.reason("a", a, hs) == "hull"
    # Full shields do not end a hull fall-back: it holds to rotate_max_s.
    out = rotate.fallback_flags(mates(a), out, 20.0, set(), {}, hs)
    assert out["a"] == 1.0
    cd = {}
    out = rotate.fallback_flags(mates(a), out, 31.0, set(), cd, hs)
    assert out["a"] is None and hs == {"a": "spent"}
    # Spent: past the cooldown, hull alone never sends it back again...
    out = rotate.fallback_flags(mates(a), out, 100.0, set(), cd, hs)
    assert out["a"] is None
    # ...but a downed face still does.
    out = rotate.fallback_flags(mates(F("a", 0.9, weak_face=0.1, hull=0.45)),
                                out, 101.0, set(), cd, hs)
    assert out["a"] == 101.0
    assert rotate.reason("a", F("a", 0.9, weak_face=0.1, hull=0.45),
                         hs) == "shields"


def test_hull_fallback_not_below_desperate_hull():
    hs = {}
    out = rotate.fallback_flags(mates(F("a", hull=0.35)), {}, 1.0, set(), {},
                                hs)
    assert out["a"] is None and hs == {}


def test_hull_fallback_respects_the_cap():
    hs = {}
    vs = [F("a", hull=0.45), F("b", hull=0.42), F("c"), F("d")]
    out = rotate.fallback_flags(vs, {}, 1.0, set(), {}, hs)
    assert [n for n, t in out.items() if t is not None] == ["b"]
    assert hs == {"b": "active"}


def test_rotate_out_hull_dial_default():
    assert dials.get("rotate_out_hull") == 0.5
