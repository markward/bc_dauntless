from engine.wings import dials, decisions
from engine.wings.assess import ShipView


def V(name, x=0.0, hull=1.0, shield=1.0, power=1.0, wing_id=None, cmd=False):
    return ShipView(name, (x, 0.0, 0.0), hull, shield, power, wing_id, cmd)


def setup_function(_):
    dials.reset()
    decisions.reset_registry()


def _ctx(members, enemies, current=None, anchor=None):
    return decisions.Context(members=members, anchor=anchor or members[0],
                             enemies=enemies, current=current)


def _scores(ctx):
    return {d.name: d.score(ctx) for d in decisions.registered()}


def test_regroup_wins_when_most_strayed():
    ms = [V("a", 0), V("b", 400), V("c", 400), V("d", 400), V("e", 10)]
    ctx = _ctx(ms, [V("x", 50)])
    s = _scores(ctx)
    assert s["regroup"] == 1.5
    assert decisions.pick(ctx).name == "regroup"


def test_swarm_weakest_when_not_outmatched():
    ctx = _ctx([V("a"), V("b", 10)], [V("x", 50)])
    s = _scores(ctx)
    assert s["swarm_weakest"] == 1.0
    assert s["swarm_commander"] == 0.3
    assert decisions.pick(ctx).name == "swarm_weakest"


def test_swarm_commander_when_outmatched_and_commander_visible():
    en = [V("x1", 50, wing_id="w"), V("x2", 60, wing_id="w", cmd=True),
          V("x3", 70, wing_id="w"), V("x4", 80, wing_id="w")]
    ctx = _ctx([V("a")], en)
    s = _scores(ctx)
    assert s["swarm_commander"] == 1.0
    assert s["swarm_weakest"] == 0.4
    d = decisions.pick(ctx)
    assert d.name == "swarm_commander"
    ch = d.choose(ctx)
    assert ch.primary == "x2"
    assert ch.secondaries == ("x1", "x3")


def test_swarm_commander_low_without_enemy_commander():
    en = [V("x1", 50), V("x2", 60), V("x3", 70)]
    ctx = _ctx([V("a")], en)
    s = _scores(ctx)
    assert s["swarm_commander"] == 0.3
    assert s["swarm_weakest"] == 0.4


def test_stickiness_keeps_current_on_near_tie():
    # not outmatched: weakest 1.0, commander 0.3; current commander +0.25 = 0.55
    ctx = _ctx([V("a")], [V("x", 50)], current="swarm_commander")
    assert decisions.pick(ctx).name == "swarm_weakest"
    # outmatched, no commander: weakest 0.4 vs commander 0.3+0.25
    en = [V("x1", 50), V("x2", 60), V("x3", 70)]
    ctx = _ctx([V("a")], en, current="swarm_commander")
    assert decisions.pick(ctx).name == "swarm_commander"
    ctx = _ctx([V("a")], en, current="swarm_weakest")
    assert decisions.pick(ctx).name == "swarm_weakest"


def test_register_replaces_by_name_and_reset_restores_stock():
    names = [d.name for d in decisions.registered()]
    assert names == ["regroup", "swarm_weakest", "swarm_commander",
                     "protect", "withdraw"]

    class Fake:
        name = "swarm_weakest"

        def score(self, ctx):
            return 9.0

        def choose(self, ctx):
            return decisions.Choice(None, (), False)

    f = Fake()
    decisions.register(f)
    reg = decisions.registered()
    assert [d.name for d in reg] == names
    assert reg[1] is f
    decisions.reset_registry()
    assert decisions.registered()[1] is not f


def test_choose_returns_none_primary_when_nothing_in_reach():
    ctx = _ctx([V("a")], [V("far", 900, cmd=True)])
    for d in decisions.registered():
        assert d.choose(ctx).primary is None


def test_choose_weakest_and_regroup_gather():
    en = [V("s", 10, hull=0.9), V("w", 20, hull=0.1), V("m", 30, hull=0.5),
          V("z", 40, hull=0.6)]
    ctx = _ctx([V("a")], en)
    ch = decisions.SwarmWeakest().choose(ctx)
    assert (ch.primary, ch.secondaries, ch.gather) == ("w", ("m", "z"), False)
    rg = decisions.Regroup().choose(ctx)
    assert (rg.primary, rg.secondaries, rg.gather) == ("w", ("m", "z"), True)
