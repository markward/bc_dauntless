from engine.wings import dials, decisions
from engine.wings.assess import ShipView


def V(name, x=0.0, hull=1.0, shield=1.0, power=1.0, target=None):
    return ShipView(name, (x, 0.0, 0.0), hull, shield, power, None, False,
                    target)


def setup_function(_):
    dials.reset()
    decisions.reset_registry()


def _by(name):
    return {d.name: d for d in decisions.registered()}[name]


def test_registered_after_phase_a():
    assert [d.name for d in decisions.registered()][-2:] == [
        "protect", "withdraw"]


def test_protect_scores_when_threatened():
    p = V("p", 5)
    atk = [V("e", 30, target="p")]
    ctx = decisions.Context(members=[V("a"), p], anchor=V("a"), enemies=atk,
                            protectees=[p], rates={"p": 0.3})
    assert _by("protect").score(ctx) == 1.5
    ctx2 = decisions.Context(members=[V("a"), p], anchor=V("a"), enemies=atk,
                             protectees=[p], rates={"p": 0.0})
    assert _by("protect").score(ctx2) == 0.0


def test_protect_rate_alone_scores_zero():
    """Review I1: damage with no attacker in reach never wins Protect, so
    Phase A's focus stays."""
    p = V("p", 5)
    ctx = decisions.Context(members=[V("a"), p], anchor=V("a"),
                            enemies=[V("x", 50)], protectees=[p],
                            rates={"p": 0.9})
    assert _by("protect").score(ctx) == 0.0
    assert decisions.pick(ctx).name == "swarm_weakest"


def test_protect_choice_attackers():
    p = V("p", 0)
    en = [V("e1", 30, target="p"), V("e2", 10, target="p"),
          V("e3", 20, target="p"), V("e4", 40, target="p"),
          V("e5", 5, target="other")]
    ctx = decisions.Context(members=[p], anchor=p, enemies=en,
                            protectees=[p], rates={"p": 0.5})
    c = _by("protect").choose(ctx)
    assert c.primary == "e2"
    assert c.secondaries == ("e3", "e1")
    assert c.protectee == "p"
    assert not c.withdraw


def _w(**kw):
    ms = [V("a", hull=0.2), V("b", 5, hull=0.2)]
    en = [V("x1", 50), V("x2", 60), V("x3", 70)]
    base = dict(members=ms, anchor=ms[0], enemies=en, armed_strength=3.0,
                now=100.0)
    base.update(kw)
    return decisions.Context(**base)


def test_withdraw_gates_each():
    w = _by("withdraw")
    assert w.score(_w()) == 2.5
    assert w.score(_w(armed_strength=0.6)) == 0.0
    assert w.score(_w(player_commands=True)) == 0.0
    assert w.score(_w(enemies=[V("x", 50)])) == 0.0
    c = w.choose(_w())
    # Every member runs withdraw itself: no gather on the commander.
    assert c.primary is None and not c.gather and c.withdraw


def test_withdraw_max_then_cooldown():
    w = _by("withdraw")
    assert w.score(_w(withdraw_cooldown_until=200.0)) == 0.0
    assert w.score(_w(withdraw_since=50.0)) == 2.5
    assert w.score(_w(withdraw_since=30.0)) == 0.0
    assert w.score(_w(withdraw_since=95.0, clear_since=85.0)) == 0.0
    assert w.score(_w(withdraw_since=95.0, clear_since=95.0)) == 2.5


def test_withdraw_ended_when_odds_recover():
    w = _by("withdraw")
    ms = [V("a", hull=0.2), V("b", 5, hull=0.2)]

    def ctx(hull):
        return decisions.Context(members=ms, anchor=ms[0],
                                 enemies=[V("x", 50, hull=hull)],
                                 armed_strength=3.0, now=100.0,
                                 withdraw_since=95.0)
    assert w.score(ctx(0.8333)) == 2.5
    assert w.score(ctx(0.6)) == 0.0


def test_withdraw_persists_with_no_enemies_in_range():
    w = _by("withdraw")
    ctx = _w(enemies=[], withdraw_since=95.0, clear_since=95.0)
    assert w.score(ctx) == 2.5
    assert w.score(_w(enemies=[], withdraw_since=95.0,
                      clear_since=80.0)) == 0.0


def test_withdraw_beats_regroup():
    ms = [V("a", hull=0.2), V("b", 400, hull=0.2), V("c", 400, hull=0.2)]
    ctx = _w(members=ms, anchor=ms[0])
    assert decisions.pick(ctx).name == "withdraw"


def test_phase_a_scores_unchanged():
    ms = [V("a"), V("b", 10)]
    ctx = decisions.Context(members=ms, anchor=ms[0], enemies=[V("x", 50)])
    s = {d.name: d.score(ctx) for d in decisions.registered()}
    assert s["regroup"] == 0.0 and s["swarm_weakest"] == 1.0
    assert s["swarm_commander"] == 0.3
    assert s["protect"] == 0.0 and s["withdraw"] == 0.0


def test_ended_withdraw_never_wins_on_stickiness():
    """Review M3: a decision scoring 0 gets no stickiness bonus, so an
    ended Withdraw ends even with the dial at 0.5 (outmatched swarm 0.4)."""
    dials._dials["stickiness"] = 0.5
    ended = _w(current="withdraw", withdraw_since=30.0)   # past withdraw_max_s
    assert _by("withdraw").score(ended) == 0.0
    assert decisions.pick(ended).name != "withdraw"
    live = _w(current="withdraw", withdraw_since=95.0)
    assert decisions.pick(live).name == "withdraw"


def test_stickiness_still_holds_a_scoring_current():
    dials._dials["stickiness"] = 0.75
    ms = [V("a"), V("b", 10)]
    ctx = decisions.Context(members=ms, anchor=ms[0], enemies=[V("x", 50)],
                            current="swarm_commander")
    assert decisions.pick(ctx).name == "swarm_commander"   # 0.3 + 0.75 > 1.0
