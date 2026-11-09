from engine.wings import allies, dials, roster
from engine.wings.allies import WingStatus


def _st(wid="a", side="s", ours=10.0, theirs=5.0, engaged=True,
        decision=None):
    return WingStatus(wing_id=wid, side=side, anchor=(0.0, 0.0, 0.0),
                      strength_frac=1.0, ours=ours, theirs=theirs,
                      enemy_centroid=None, engaged=engaged, decision=decision)


def _wing(wid, side, status=None):
    w = roster.Wing(wing_id=wid, enemy_group=object(), target_group=None)
    w.side, w.status = side, status
    return w


def test_in_trouble_losing_odds():
    dials.reset()
    assert allies.in_trouble(_st(ours=4.0, theirs=5.0))
    assert not allies.in_trouble(_st(ours=6.0, theirs=5.0))


def test_in_trouble_protect_and_withdraw():
    assert allies.in_trouble(_st(decision="protect"))
    assert allies.in_trouble(_st(decision="withdraw"))
    assert not allies.in_trouble(_st(decision="swarm"))


def test_in_trouble_requires_engaged():
    assert not allies.in_trouble(_st(ours=0.0, theirs=9.0, engaged=False,
                                     decision="withdraw"))


def test_side_allies_same_side_sorted_excluding_self_and_none():
    me = _wing("m", "x", _st("m", "x"))
    b = _wing("b", "x", _st("b", "x"))
    a = _wing("a", "x", _st("a", "x"))
    none = _wing("n", "x", None)
    other = _wing("o", "y", _st("o", "y"))
    got = allies.side_allies(me, [me, b, none, other, a])
    assert [s.wing_id for s in got] == ["a", "b"]


def test_side_of_default_and_explicit():
    g = object()
    w = roster.Wing(wing_id="w", enemy_group=g, target_group=None)
    assert allies.side_of(w) == str(id(g))
    w.side = "friendly"
    assert allies.side_of(w) == "friendly"
