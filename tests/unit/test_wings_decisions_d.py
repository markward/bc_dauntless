"""Phase D decisions: reinforce, feint, screen, flank (spec
2026-11-09-wing-leaders-phase-d-design.md §4-§7). Pure."""
import math

from engine.wings import dials, decisions
from engine.wings.allies import WingStatus
from engine.wings.assess import ShipView


def V(name, x=0.0, y=0.0, power=1.0, faces=(), shield=1.0):
    return ShipView(name, (x, y, 0.0), 1.0, shield, power, None, False,
                    None, faces)


def A(wid="B", anchor=(1000.0, 0.0, 0.0), ours=10.0, theirs=5.0,
      engaged=True, centroid=None, frac=1.0, decision="swarm_weakest"):
    return WingStatus(wing_id=wid, side="s", anchor=tuple(anchor),
                      strength_frac=frac, ours=ours, theirs=theirs,
                      enemy_centroid=centroid, engaged=engaged,
                      decision=decision)


def setup_function(_):
    dials.reset()
    decisions.reset_registry()


def _by(name):
    return {d.name: d for d in decisions.registered()}[name]


def _ctx(enemies=(), allies=(), anchor=(0.0, 0.0, 0.0), armed=10.0, **kw):
    x, y, _ = anchor
    members = [V("a", x, y, power=5.0), V("b", x + 5, y, power=5.0)]
    return decisions.Context(members=members, anchor=members[0],
                             enemies=list(enemies), allies=tuple(allies),
                             armed_strength=armed, **kw)


def _near(p, a, b):
    return all(abs(x - y) < 1e-6 for x, y in zip(a, b)) and p


def test_registered_order_phase_d():
    names = [d.name for d in decisions.registered()]
    assert names[-7:] == ["focus_face", "envelop", "disable", "reinforce",
                          "feint", "screen", "flank"]


def test_choice_and_context_defaults():
    c = decisions.Choice(None)
    assert (c.far, c.hold_point, c.hold_kind, c.ally) == (
        False, None, None, None)
    ctx = _ctx()
    assert ctx.reinforce_ally is None and ctx.reinforce_done == frozenset()
    assert ctx.feint_ally is None and ctx.feint_ready is True
    assert ctx.feint_quiet_s == 0.0 and ctx.decision_age_s == 0.0


# --- reinforce -------------------------------------------------------------

def _trouble(wid="B", anchor=(1000.0, 0.0, 0.0), ours=1.0, theirs=5.0):
    return A(wid, anchor, ours=ours, theirs=theirs, engaged=True,
             centroid=anchor)


def _ally_enemies(x=1000.0):
    return [V("e1", x + 50), V("e2", x + 100), V("e3", x + 150),
            V("e4", x + 200), V("far", x + 2000)]


def test_reinforce_scores_when_every_gate_holds():
    ctx = _ctx(_ally_enemies(), [_trouble()])
    assert _by("reinforce").score(ctx) == 1.25


def test_reinforce_zero_when_engaged_and_cannot_spare():
    # ours 10 within engage, theirs 5: 10 < 2.5 * 5.
    ctx = _ctx(_ally_enemies() + [V("x", 100, power=5.0)], [_trouble()])
    assert _by("reinforce").score(ctx) == 0.0


def test_reinforce_engaged_but_can_spare():
    # theirs 1: 10 >= 2.5 * 1.
    ctx = _ctx(_ally_enemies() + [V("x", 100, power=1.0)], [_trouble()])
    assert _by("reinforce").score(ctx) == 1.25


def test_reinforce_zero_when_no_ally_in_trouble():
    ok = A("B", ours=10.0, theirs=5.0, centroid=(1000.0, 0.0, 0.0))
    assert _by("reinforce").score(_ctx(_ally_enemies(), [ok])) == 0.0
    assert _by("reinforce").score(_ctx(_ally_enemies(), [])) == 0.0


def test_reinforce_zero_when_ally_beyond_range():
    ctx = _ctx(_ally_enemies(2000.0), [_trouble(anchor=(2000.0, 0.0, 0.0))])
    assert _by("reinforce").score(ctx) == 0.0


def test_reinforce_zero_when_already_arrived():
    ctx = _ctx(_ally_enemies(150.0), [_trouble(anchor=(150.0, 0.0, 0.0))])
    # The ally's enemies are near us too, but we can spare (theirs small).
    ctx.enemies = []
    assert _by("reinforce").score(ctx) == 0.0


def test_reinforce_skips_ally_in_done():
    ctx = _ctx(_ally_enemies(), [_trouble()], reinforce_done=frozenset({"B"}))
    assert _by("reinforce").score(ctx) == 0.0
    two = _ctx(_ally_enemies(), [_trouble(),
                                 _trouble("C", (0.0, 900.0, 0.0))],
               reinforce_done=frozenset({"B"}))
    assert _by("reinforce").score(two) == 1.25
    assert _by("reinforce").choose(two).ally == "C"


def _latched(enemies, allies, **kw):
    kw.setdefault("reinforce_ally", "B")
    return _ctx(enemies, allies, current="reinforce", **kw)


def test_reinforce_latch_ignores_engaged_gate():
    enemies = _ally_enemies() + [V("x", 100, power=5.0)]
    assert _by("reinforce").score(_ctx(enemies, [_trouble()])) == 0.0
    assert _by("reinforce").score(_latched(enemies, [_trouble()])) == 1.25


def test_reinforce_latch_keeps_its_ally():
    # C is in worse trouble, but the latch holds B.
    ctx = _latched(_ally_enemies(), [_trouble(),
                                     _trouble("C", (0, 900.0, 0), ours=0.1)])
    assert _by("reinforce").choose(ctx).ally == "B"


def test_reinforce_ends_on_arrival():
    ctx = _latched([], [_trouble(anchor=(150.0, 0.0, 0.0))])
    assert _by("reinforce").score(ctx) == 0.0


def test_reinforce_ends_when_ally_recovers():
    ok = A("B", ours=10.0, theirs=5.0, centroid=(1000.0, 0.0, 0.0))
    assert _by("reinforce").score(_latched(_ally_enemies(), [ok])) == 0.0


def test_reinforce_ends_when_ally_missing():
    assert _by("reinforce").score(_latched(_ally_enemies(), [])) == 0.0
    other = _trouble("C", (0.0, 900.0, 0.0))
    assert _by("reinforce").score(_latched(_ally_enemies(), [other])) == 0.0


def test_reinforce_ends_at_cap():
    ctx = _latched(_ally_enemies(), [_trouble()], decision_age_s=89.0)
    assert _by("reinforce").score(ctx) == 1.25
    ctx = _latched(_ally_enemies(), [_trouble()], decision_age_s=90.0)
    assert _by("reinforce").score(ctx) == 0.0


def test_reinforce_cap_only_when_current():
    ctx = _ctx(_ally_enemies(), [_trouble()], decision_age_s=500.0,
               current="swarm_weakest")
    assert _by("reinforce").score(ctx) == 1.25


def test_reinforce_choose_far_primary_nearest_ally_anchor():
    ctx = _ctx(_ally_enemies(), [_trouble()])
    c = _by("reinforce").choose(ctx)
    assert c.primary == "e1"
    assert c.secondaries == ("e2", "e3")
    assert c.far is True and c.ally == "B"
    assert c.hold_point is None and c.hold_kind is None


def test_reinforce_choose_worst_odds_then_nearest():
    worse = _trouble("C", (0.0, 1200.0, 0.0), ours=0.5)
    ctx = _ctx(_ally_enemies(), [_trouble(), worse])
    assert _by("reinforce").choose(ctx).ally == "C"
    tie_far = _trouble("C", (0.0, 1200.0, 0.0))
    ctx = _ctx(_ally_enemies(), [tie_far, _trouble()])
    assert _by("reinforce").choose(ctx).ally == "B"


# --- feint -----------------------------------------------------------------

def _f(wid="F", anchor=(-500.0, 0.0, 0.0), engaged=False, frac=1.0,
       ours=10.0):
    return A(wid, anchor, ours=ours, theirs=0.0, engaged=engaged, frac=frac)


def _fighting(power=5.0):
    return [V("x", 100, power=power)]


def test_feint_scores_when_every_gate_holds():
    assert _by("feint").score(_ctx(_fighting(), [_f()])) == 1.2


def test_feint_zero_when_not_engaged():
    assert _by("feint").score(_ctx([V("x", 1000)], [_f()])) == 0.0


def test_feint_zero_when_we_are_weak():
    ctx = _ctx(_fighting(), [_f()], armed=30.0)    # 10 / 30 < 0.5
    assert _by("feint").score(ctx) == 0.0


def test_feint_zero_when_ally_engaged():
    assert _by("feint").score(_ctx(_fighting(), [_f(engaged=True)])) == 0.0


def test_feint_zero_when_ally_weak():
    assert _by("feint").score(_ctx(_fighting(), [_f(frac=0.5)])) == 0.0


def test_feint_zero_when_ally_too_far():
    ctx = _ctx(_fighting(), [_f(anchor=(-900.0, 0.0, 0.0))])
    assert _by("feint").score(ctx) == 0.0


def test_feint_zero_when_ally_within_engage():
    ctx = _ctx(_fighting(), [_f(anchor=(-300.0, 0.0, 0.0))])
    assert _by("feint").score(ctx) == 0.0


def test_feint_zero_when_both_wings_cannot_beat_them():
    # theirs 25 > (10 + 10) * 1.0
    assert _by("feint").score(_ctx(_fighting(25.0), [_f()])) == 0.0
    assert _by("feint").score(_ctx(_fighting(20.0), [_f()])) == 1.2


def test_feint_zero_when_not_ready():
    ctx = _ctx(_fighting(), [_f()], feint_ready=False)
    assert _by("feint").score(ctx) == 0.0


def _feinting(enemies, allies, **kw):
    kw.setdefault("feint_ally", "F")
    return _ctx(enemies, allies, current="feint", **kw)


def test_feint_latch_ignores_entry_gates():
    # Not engaged any more, and the odds now fail: still feinting.
    ctx = _feinting([V("x", 1000, power=50.0)], [_f()], feint_ready=False)
    assert _by("feint").score(ctx) == 1.2


def test_feint_ends_near_the_ally():
    ctx = _feinting(_fighting(), [_f(anchor=(-160.0, 0.0, 0.0))])
    assert _by("feint").score(ctx) == 1.2
    ctx = _feinting(_fighting(), [_f(anchor=(-150.0, 0.0, 0.0))])
    assert _by("feint").score(ctx) == 0.0


def test_feint_ends_when_ally_engaged_or_missing():
    assert _by("feint").score(
        _feinting(_fighting(), [_f(engaged=True)])) == 0.0
    assert _by("feint").score(_feinting(_fighting(), [])) == 0.0
    assert _by("feint").score(_feinting(_fighting(), [_f("G")])) == 0.0


def test_feint_ends_when_quiet():
    assert _by("feint").score(
        _feinting(_fighting(), [_f()], feint_quiet_s=9.9)) == 1.2
    assert _by("feint").score(
        _feinting(_fighting(), [_f()], feint_quiet_s=10.0)) == 0.0


def test_feint_ends_at_cap():
    assert _by("feint").score(
        _feinting(_fighting(), [_f()], decision_age_s=45.0)) == 0.0


def test_feint_choose_lure_point():
    c = _by("feint").choose(_ctx(_fighting(), [_f()]))
    assert c.primary is None and c.hold_kind == "feint" and c.ally == "F"
    assert _near(True, c.hold_point, (-400.0, 0.0, 0.0))
    c = _by("feint").choose(_feinting([], [_f(anchor=(0.0, -600.0, 0.0))]))
    assert _near(True, c.hold_point, (0.0, -500.0, 0.0))


def test_focus_face_beats_fresh_feint_current_feint_keeps_winning():
    f = [0.9] * 6
    f[4] = 0.1
    enemies = [V("x", 100, power=5.0, faces=tuple(f))]
    fresh = _ctx(enemies, [_f()], slot_eligible=2)
    assert _by("focus_face").score(fresh) == 1.2
    assert _by("feint").score(fresh) == 1.2
    assert decisions.pick(fresh).name == "focus_face"
    cur = _ctx(enemies, [_f()], slot_eligible=2, current="feint",
               feint_ally="F")
    assert decisions.pick(cur).name == "feint"


# --- screen ----------------------------------------------------------------

def _weak(wid="W", anchor=(500.0, 0.0, 0.0), frac=0.3,
          decision="swarm_weakest", engaged=False):
    return A(wid, anchor, ours=1.0, theirs=0.0, engaged=engaged, frac=frac,
             decision=decision)


def _closing():
    return [V("c1", 1000), V("c2", 1000, 20)]


def test_screen_scores_when_every_gate_holds():
    assert _by("screen").score(_ctx(_closing(), [_weak()])) == 1.15


def test_screen_zero_when_we_are_engaged():
    ctx = _ctx(_closing() + [V("x", -100)], [_weak()])
    assert _by("screen").score(ctx) == 0.0


def test_screen_zero_when_we_are_weak():
    ctx = _ctx(_closing(), [_weak()], armed=20.0)    # 10 / 20 < 0.6
    assert _by("screen").score(ctx) == 0.0


def test_screen_zero_when_ally_not_weak_unless_withdrawing():
    assert _by("screen").score(_ctx(_closing(), [_weak(frac=0.5)])) == 0.0
    ctx = _ctx(_closing(), [_weak(frac=0.9, decision="withdraw")])
    assert _by("screen").score(ctx) == 1.15


def test_screen_zero_when_enemies_already_on_the_ally():
    ctx = _ctx([V("c1", 600), V("c2", 1000, 20)], [_weak()])
    assert _by("screen").score(ctx) == 0.0


def test_screen_zero_when_nothing_closing():
    ctx = _ctx([V("c1", 1300)], [_weak()])     # 800 > screen_watch 700
    assert _by("screen").score(ctx) == 0.0
    assert _by("screen").score(_ctx([], [_weak()])) == 0.0


def test_screen_choose_hold_point_between():
    c = _by("screen").choose(_ctx(_closing(), [_weak()]))
    assert c.hold_kind == "screen" and c.ally == "W"
    # centroid (1000, 10, 0): 150 GU out from (500, 0, 0) toward it.
    d = math.hypot(500.0, 10.0)
    exp = (500.0 + 150.0 * 500.0 / d, 150.0 * 10.0 / d, 0.0)
    assert _near(True, c.hold_point, exp)
    assert c.primary is None and c.far is False


# --- flank -----------------------------------------------------------------

C = (600.0, 0.0, 0.0)


def _fair(wid="B", anchor=(900.0, 0.0, 0.0), ours=10.0, theirs=5.0,
          engaged=True, centroid=C):
    return A(wid, anchor, ours=ours, theirs=theirs, engaged=engaged,
             centroid=centroid)


US = (0.0, 300.0, 0.0)


def test_flank_scores_when_every_gate_holds():
    assert _by("flank").score(_ctx([], [_fair()], anchor=US)) == 1.1


def test_flank_zero_when_we_are_engaged():
    ctx = _ctx([V("x", 0, 400)], [_fair()], anchor=US)
    assert _by("flank").score(ctx) == 0.0


def test_flank_zero_when_ally_not_engaged():
    ctx = _ctx([], [_fair(engaged=False, centroid=None)], anchor=US)
    assert _by("flank").score(ctx) == 0.0


def test_flank_zero_when_ally_in_trouble():
    ctx = _ctx([], [_fair(ours=1.0)], anchor=US)
    assert _by("flank").score(ctx) == 0.0


def test_flank_zero_when_ally_beyond_range():
    far = _fair(anchor=(2000.0, 0.0, 0.0), centroid=(1700.0, 0.0, 0.0))
    assert _by("flank").score(_ctx([], [far], anchor=US)) == 0.0


def test_flank_zero_when_already_at_hold_point():
    ctx = _ctx([], [_fair()], anchor=(600.0, 400.0, 0.0))
    assert _by("flank").score(ctx) == 0.0


def test_flank_latch_ignores_trouble_gate():
    ctx = _ctx([], [_fair(ours=1.0)], anchor=US, current="flank")
    assert _by("flank").score(ctx) == 1.1


def test_flank_ends_on_arrival():
    # Hold point (600, 250, 0): within leash 200.
    ctx = _ctx([], [_fair()], anchor=(600.0, 420.0, 0.0), current="flank")
    assert _by("flank").score(ctx) == 0.0


def test_flank_ends_when_engaged():
    ctx = _ctx([V("x", 0, 400)], [_fair()], anchor=US, current="flank")
    assert _by("flank").score(ctx) == 0.0


def test_flank_ends_when_ally_not_engaged_or_missing():
    ctx = _ctx([], [_fair(engaged=False, centroid=None)], anchor=US,
               current="flank")
    assert _by("flank").score(ctx) == 0.0
    assert _by("flank").score(_ctx([], [], anchor=US, current="flank")) == 0.0


def test_flank_choose_hold_point_on_our_side():
    c = _by("flank").choose(_ctx([], [_fair()], anchor=US))
    assert c.hold_kind == "flank" and c.ally == "B"
    assert _near(True, c.hold_point, (600.0, 250.0, 0.0))
    below = _by("flank").choose(_ctx([], [_fair()], anchor=(0.0, -300.0, 0.0)))
    assert _near(True, below.hold_point, (600.0, -250.0, 0.0))


def test_flank_choose_keeps_swarm_primary():
    ctx = _ctx([V("r", 150, 300)], [_fair()], anchor=US)
    # r is 150 from us: engaged, so flank scores 0, but choose still
    # carries the swarm choice (anything in reach stays the target).
    c = _by("flank").choose(ctx)
    assert c.primary == "r"


# --- reinforce vs flank ----------------------------------------------------

def test_no_flip_between_reinforce_and_flank():
    trouble = _fair(ours=1.0)
    fair = _fair()
    assert decisions.pick(_ctx([], [trouble], anchor=US)).name == "reinforce"
    assert decisions.pick(_ctx([], [fair], anchor=US)).name == "flank"
    # A current reinforce whose ally recovers ends (score 0); the next
    # pick is flank, a decision of its own, not a stickiness flip.
    rec = _ctx([], [fair], anchor=US, current="reinforce",
               reinforce_ally="B")
    assert _by("reinforce").score(rec) == 0.0
    assert decisions.pick(rec).name == "flank"
    # And the latched flank holds when the ally slips into trouble: no
    # flip back to reinforce tick to tick.
    back = _ctx([], [trouble], anchor=US, current="flank")
    assert decisions.pick(back).name == "flank"
