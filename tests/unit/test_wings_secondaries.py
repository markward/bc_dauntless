"""Secondary holders: a share of the wing (secondary_share, rounded DOWN;
Mark 2026-11-13) is ordered onto the secondaries, the members closest to
one each taking the secondary nearest them. Picked before the primary's
slots, so a disable's all-hands assault cannot take them. Pure."""
from engine.wings import attack, dials
from engine.wings.assess import ShipView


def setup_function(_):
    dials.reset()


def V(name, x, y=0.0):
    return ShipView(name=name, pos=(x, y, 0.0), hull=1.0, shield=1.0,
                    power=1.0)


def test_count_rounds_down():
    assert [attack.secondary_count(n, 0.1) for n in (0, 1, 9, 10, 19, 20)] \
        == [0, 0, 0, 1, 1, 2]
    assert attack.secondary_count(4, 0.25) == 1
    assert attack.secondary_count(10, 0.3) == 3      # not 2 (0.3*10 float)
    assert attack.secondary_count(10, 0.0) == 0


def test_closest_members_take_their_nearest_secondary():
    cands = [V("a", 0.0), V("b", 90.0), V("c", 200.0), V("d", 400.0)]
    secs = [V("s1", 100.0), V("s2", 420.0)]
    # d is 20 from s2, b is 10 from s1: both closest, each to its own.
    assert attack.assign_secondaries(cands, secs, 2) == {"b": "s1",
                                                          "d": "s2"}
    assert attack.assign_secondaries(cands, secs, 1) == {"b": "s1"}


def test_nothing_to_assign():
    cands = [V("a", 0.0)]
    assert attack.assign_secondaries(cands, [V("s", 5.0)], 0) == {}
    assert attack.assign_secondaries(cands, [], 3) == {}
    assert attack.assign_secondaries([], [V("s", 5.0)], 3) == {}


def test_more_holders_than_candidates_assigns_everyone():
    cands = [V("a", 0.0), V("b", 50.0)]
    assert attack.assign_secondaries(cands, [V("s", 10.0)], 5) == {
        "a": "s", "b": "s"}


def test_incumbents_keep_their_secondary_while_it_is_listed():
    """No reshuffle each second: a previous holder that is still a
    candidate keeps its secondary while it is still a secondary, even
    when another member has drifted closer."""
    cands = [V("a", 0.0), V("b", 95.0)]
    secs = [V("s1", 100.0)]
    assert attack.assign_secondaries(cands, secs, 1, {"a": "s1"}) == {
        "a": "s1"}
    # s1 is no longer a secondary: the incumbent is released.
    assert attack.assign_secondaries(cands, [V("s2", 90.0)], 1,
                                     {"a": "s1"}) == {"b": "s2"}
    # The share shrank: incumbents beyond it are released, nearest kept.
    assert attack.assign_secondaries(
        cands, secs, 1, {"a": "s1", "b": "s1"}) == {"b": "s1"}


def test_ties_break_by_name():
    cands = [V("b", 0.0, 10.0), V("a", 0.0, -10.0)]
    assert attack.assign_secondaries(cands, [V("s", 0.0)], 1) == {"a": "s"}


def test_dial_default_and_range():
    assert dials.get("secondary_share") == 0.1
    out = dials.step(dials.current(), "secondary_share", -1)
    assert out["secondary_share"] == 0.05
    top = dict(dials.current(), secondary_share=1.0)
    assert dials.step(top, "secondary_share", 1)["secondary_share"] == 1.0
