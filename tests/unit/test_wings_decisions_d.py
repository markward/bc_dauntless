"""Phase D decisions: reinforce, feint, screen, flank (spec
2026-11-09-wing-leaders-phase-d-design.md §4-§7). Pure."""
import math

import pytest

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
    # Reinforce needs an enemy near the ally (its far primary): c1 by C.
    two = _ctx(_ally_enemies() + [V("c1", 0, 950)],
               [_trouble(), _trouble("C", (0.0, 900.0, 0.0))],
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
    by_c = _ally_enemies() + [V("c1", 0, 1250)]
    worse = _trouble("C", (0.0, 1200.0, 0.0), ours=0.5)
    ctx = _ctx(by_c, [_trouble(), worse])
    assert _by("reinforce").choose(ctx).ally == "C"
    tie_far = _trouble("C", (0.0, 1200.0, 0.0))
    ctx = _ctx(by_c, [tie_far, _trouble()])
    assert _by("reinforce").choose(ctx).ally == "B"


# --- feint -----------------------------------------------------------------

def _f(wid="F", anchor=(-500.0, 0.0, 0.0), engaged=False, frac=1.0,
       ours=10.0):
    return A(wid, anchor, ours=ours, theirs=0.0, engaged=engaged, frac=frac)


def _fighting(power=9.0):
    """One enemy near us. Ours is 10: 9 keeps us under feint_max_odds
    (1.25) x theirs, so a feint can enter (fix wave I2)."""
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
    # x (7: under disable_threat x 5) in reach, y beyond it but engaged:
    # theirs 9, so the feint's odds gate holds.
    enemies = [V("x", 100, power=7.0, faces=tuple(f)),
               V("y", 300, power=2.0)]
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
    ctx = _ctx([], [_fair(ours=1.0)], anchor=US, current="flank",
               flank_ally="B")
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
    # The ally's enemy at C (300 GU from it, 670 from us): reinforce's far
    # primary, never near us.
    ec = [V("ec", 600)]
    assert decisions.pick(_ctx(ec, [trouble], anchor=US)).name == "reinforce"
    assert decisions.pick(_ctx(ec, [fair], anchor=US)).name == "flank"
    # A current reinforce whose ally recovers ends (score 0); the next
    # pick is flank, a decision of its own, not a stickiness flip.
    rec = _ctx(ec, [fair], anchor=US, current="reinforce",
               reinforce_ally="B")
    assert _by("reinforce").score(rec) == 0.0
    assert decisions.pick(rec).name == "flank"
    # And the latched flank holds when the ally slips into trouble: no
    # flip back to reinforce tick to tick.
    back = _ctx(ec, [trouble], anchor=US, current="flank", flank_ally="B")
    assert decisions.pick(back).name == "flank"


# --- Task 3 review items ---------------------------------------------------

def test_reinforce_zero_without_a_primary():
    # The ally is in trouble but none of OUR enemies is near its anchor:
    # reinforce would have no far primary to intercept.
    ctx = _ctx([V("far", 3000)], [_trouble()])
    assert _by("reinforce").score(ctx) == 0.0
    latched = _latched([V("far", 3000)], [_trouble()])
    assert _by("reinforce").score(latched) == 0.0
    # Another ally in trouble that does have enemies near it is picked.
    two = _ctx(_ally_enemies(), [_trouble("A", (0.0, 900.0, 0.0), ours=0.1),
                                 _trouble()])
    assert _by("reinforce").choose(two).ally == "B"


def test_screen_zero_when_ally_beyond_reinforce_range():
    far = _weak(anchor=(1600.0, 0.0, 0.0))
    enemies = [V("c1", 2100), V("c2", 2100, 20)]
    assert _by("screen").score(_ctx(enemies, [far])) == 0.0
    dials._dials["reinforce_range_gu"] = 1700.0
    assert _by("screen").score(_ctx(enemies, [far])) == 1.15


def test_flank_latch_keeps_its_ally():
    near_b = _fair()
    near_c = _fair("C", anchor=(0.0, 900.0, 0.0), centroid=(0.0, 700.0, 0.0))
    ctx = _ctx([], [near_b, near_c], anchor=(0.0, 400.0, 0.0),
               current="flank", flank_ally="B")
    c = _by("flank").choose(ctx)
    assert c.ally == "B"
    # Not latched: picks the nearest afresh (C).
    fresh = _ctx([], [near_b, near_c], anchor=(0.0, 400.0, 0.0))
    assert _by("flank").choose(fresh).ally == "C"


def test_flank_latched_ally_gone_ends():
    ctx = _ctx([], [_fair("C", anchor=(0.0, 900.0, 0.0),
                          centroid=(0.0, 700.0, 0.0))],
               anchor=US, current="flank", flank_ally="B")
    assert _by("flank").score(ctx) == 0.0


def test_flank_ally_default():
    assert _ctx().flank_ally is None


# --- stickiness only damps baseline switches (ruling, Task 3 concern 1) ---

class _Fixed:
    def __init__(self, name, value):
        self.name, self.value = name, value

    def score(self, ctx):
        return self.value

    def choose(self, ctx):
        return decisions.Choice(None)


_ORDER = ["regroup", "swarm_weakest", "swarm_commander", "protect",
          "withdraw", "focus_face", "envelop", "disable", "reinforce",
          "feint", "screen", "flank"]


def _pick(monkeypatch, current, **scores):
    """pick() over the stock names in stock order, each at a fixed score
    (0 unless given)."""
    monkeypatch.setattr(decisions, "_registry",
                        [_Fixed(n, scores.get(n, 0.0)) for n in _ORDER])
    return decisions.pick(_ctx(current=current)).name


def test_baseline_current_loses_to_higher_raw_score(monkeypatch):
    assert _pick(monkeypatch, "swarm_weakest", swarm_weakest=1.0,
                 swarm_commander=0.3, focus_face=1.2) == "focus_face"


@pytest.mark.parametrize("name,value", [
    ("feint", 1.2), ("screen", 1.15), ("flank", 1.1), ("envelop", 1.05),
    ("reinforce", 1.25)])
def test_baseline_current_loses_to_each_phase_c_d_decision(
        monkeypatch, name, value):
    assert _pick(monkeypatch, "swarm_weakest", swarm_weakest=1.0,
                 swarm_commander=0.3, **{name: value}) == name


def test_baseline_vs_baseline_keeps_stickiness(monkeypatch):
    assert _pick(monkeypatch, "swarm_weakest", swarm_weakest=1.0,
                 swarm_commander=1.2) == "swarm_weakest"
    assert _pick(monkeypatch, "swarm_weakest", swarm_weakest=1.0,
                 swarm_commander=1.3) == "swarm_commander"


def test_regroup_current_beats_lower_non_baseline(monkeypatch):
    assert _pick(monkeypatch, "regroup", regroup=1.4, swarm_weakest=1.0,
                 focus_face=1.2) == "regroup"


def test_non_baseline_current_keeps_its_bonus(monkeypatch):
    assert _pick(monkeypatch, "focus_face", swarm_weakest=1.0,
                 focus_face=1.2, reinforce=1.25) == "focus_face"


def test_non_baseline_must_beat_the_raw_baseline_top(monkeypatch):
    # Equal is not strictly greater: the baseline winner stands.
    assert _pick(monkeypatch, "swarm_weakest", swarm_weakest=1.0,
                 envelop=1.0) == "swarm_weakest"
    # The sticky baseline winner (weakest, 1.0 + 0.25) is not the raw top
    # (commander 1.2): envelop 1.1 must beat 1.2, so weakest stands.
    assert _pick(monkeypatch, "swarm_weakest", swarm_weakest=1.0,
                 swarm_commander=1.2, envelop=1.1) == "swarm_weakest"
    assert _pick(monkeypatch, "swarm_weakest", swarm_weakest=1.0,
                 swarm_commander=1.2, envelop=1.21) == "envelop"


def test_best_non_baseline_challenges(monkeypatch):
    assert _pick(monkeypatch, "swarm_weakest", swarm_weakest=1.0,
                 focus_face=1.2, reinforce=1.25) == "reinforce"
    # A tie between challengers: registration order (focus_face first).
    assert _pick(monkeypatch, "swarm_weakest", swarm_weakest=1.0,
                 focus_face=1.2, feint=1.2) == "focus_face"


def test_none_current_and_zero_current_unchanged(monkeypatch):
    assert _pick(monkeypatch, None, swarm_weakest=1.0,
                 focus_face=1.2) == "focus_face"
    assert _pick(monkeypatch, "feint", swarm_weakest=1.0,
                 feint=0.0) == "swarm_weakest"


# --- review fixes: flank latch needs its ally; arrival hysteresis ---------

def test_flank_without_ally_is_not_latched():
    # A current flank with no flank_ally (the wing stood down and came
    # back) takes the entry gates: an ally in trouble is no flank.
    ctx = _ctx([], [_fair(ours=1.0)], anchor=US, current="flank")
    assert _by("flank").score(ctx) == 0.0
    far = _fair(anchor=(3000.0, 0.0, 0.0), centroid=(2700.0, 0.0, 0.0))
    ctx = _ctx([], [far], anchor=US, current="flank")
    assert _by("flank").score(ctx) == 0.0


def _ally_at(d):
    """An ally in trouble d GU off along +x, its enemy 300 GU beyond it
    (never near us)."""
    a = _trouble(anchor=(d, 0.0, 0.0))
    return a, [V("e1", d + 300.0)]


@pytest.mark.parametrize("d,current,want", [
    (190.0, "reinforce", 0.0),          # arrived: ends at leash_gu
    (210.0, "reinforce", 1.25),         # latched: still on
    (290.0, "reinforce", 1.25),
    (210.0, None, 0.0),                 # no re-entry inside leash + slack
    (290.0, None, 0.0),
    (310.0, None, 1.25),                # entry beyond leash + slack
])
def test_reinforce_arrival_hysteresis(d, current, want):
    a, enemies = _ally_at(d)
    ctx = _ctx(enemies, [a], current=current,
               reinforce_ally="B" if current else None)
    assert _by("reinforce").score(ctx) == want


@pytest.mark.parametrize("d,current,want", [
    (190.0, "flank", 0.0),              # arrived: ends at leash_gu
    (210.0, "flank", 1.1),              # latched: still on
    (290.0, "flank", 1.1),
    (210.0, None, 0.0),                 # no re-entry inside leash + slack
    (290.0, None, 0.0),
    (310.0, None, 1.1),                 # entry beyond leash + slack
])
def test_flank_arrival_hysteresis(d, current, want):
    # Ally B at (900, 0), its enemies' centroid C (600, 0): the flank
    # point on our side is (600, 250). We sit d GU above it.
    ctx = _ctx([], [_fair()], anchor=(600.0, 250.0 + d, 0.0),
               current=current, flank_ally="B" if current else None)
    assert _by("flank").score(ctx) == want


# --- fix wave I1: protect is trouble only when the odds are close ---------

@pytest.mark.parametrize("ours,want", [(7.0, "reinforce"), (10.0, "flank")])
def test_ally_on_protect_flank_or_reinforce_by_odds(ours, want):
    # B protects a member at 1.4:1 (close: in trouble, reinforce) or 2:1
    # (comfortable: a fair fight, flank).
    b = A("B", (900.0, 0.0, 0.0), ours=ours, theirs=5.0, engaged=True,
          centroid=C, decision="protect")
    assert decisions.pick(_ctx([V("ec", 600)], [b], anchor=US)).name == want


# --- fix wave I2: a feint is a lure for a stronger enemy -------------------

def test_feint_zero_when_comfortably_ahead():
    # Ours 10: enters only while 10 < feint_max_odds (1.25) x theirs.
    assert _by("feint").score(_ctx(_fighting(5.0), [_f()])) == 0.0
    assert _by("feint").score(_ctx(_fighting(8.0), [_f()])) == 0.0
    assert _by("feint").score(_ctx(_fighting(8.1), [_f()])) == 1.2
    dials._dials["feint_max_odds"] = 2.5
    assert _by("feint").score(_ctx(_fighting(5.0), [_f()])) == 1.2


def test_feint_latch_ignores_the_odds_gate():
    ctx = _feinting(_fighting(1.0), [_f()])
    assert _by("feint").score(ctx) == 1.2


# --- fix wave I3: the player's escort wing stays with the player ----------

def test_escorts_player_default_false():
    assert _ctx().escorts_player is False


def test_escort_wing_never_reinforces():
    assert _by("reinforce").score(_ctx(_ally_enemies(), [_trouble()])) == 1.25
    ctx = _ctx(_ally_enemies(), [_trouble()], escorts_player=True)
    assert _by("reinforce").score(ctx) == 0.0
    ctx = _latched(_ally_enemies(), [_trouble()], escorts_player=True)
    assert _by("reinforce").score(ctx) == 0.0


def test_escort_wing_never_feints():
    assert _by("feint").score(_ctx(_fighting(), [_f()])) == 1.2
    ctx = _ctx(_fighting(), [_f()], escorts_player=True)
    assert _by("feint").score(ctx) == 0.0
    ctx = _feinting(_fighting(), [_f()], escorts_player=True)
    assert _by("feint").score(ctx) == 0.0


def test_escort_wing_never_screens():
    assert _by("screen").score(_ctx(_closing(), [_weak()])) == 1.15
    ctx = _ctx(_closing(), [_weak()], escorts_player=True)
    assert _by("screen").score(ctx) == 0.0


def test_escort_wing_never_flanks():
    assert _by("flank").score(_ctx([], [_fair()], anchor=US)) == 1.1
    ctx = _ctx([], [_fair()], anchor=US, escorts_player=True)
    assert _by("flank").score(ctx) == 0.0
    ctx = _ctx([], [_fair()], anchor=US, current="flank", flank_ally="B",
               escorts_player=True)
    assert _by("flank").score(ctx) == 0.0
