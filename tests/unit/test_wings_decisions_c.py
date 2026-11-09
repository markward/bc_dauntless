import math

from engine.wings import attack, dials, decisions
from engine.wings.assess import ShipView


def V(name, x=0.0, hull=1.0, shield=1.0, power=1.0, faces=(), down=False,
      wing_id=None, cmd=False):
    return ShipView(name, (x, 0.0, 0.0), hull, shield, power, wing_id, cmd,
                    None, faces, down)


def F(left=0.9, others=0.9):
    f = [others] * 6
    f[4] = left
    return tuple(f)


def setup_function(_):
    dials.reset()
    decisions.reset_registry()


def _by(name):
    return {d.name: d for d in decisions.registered()}[name]


def _ctx(enemies, members=None, eligible=5, current=None):
    members = members or [V("a", power=5.0), V("b", 5, power=5.0)]
    return decisions.Context(members=members, anchor=members[0],
                             enemies=enemies, slot_eligible=eligible,
                             current=current)


def test_registered_order():
    assert [d.name for d in decisions.registered()][-3:] == [
        "focus_face", "envelop", "disable"]


def test_focus_face_scores_with_weak_face_and_two_eligible():
    ctx = _ctx([V("e", 50, faces=F(0.1))], eligible=2)
    assert _by("focus_face").score(ctx) == 1.2


def test_focus_face_zero_when_others_weak():
    ctx = _ctx([V("e", 50, faces=F(0.1, 0.5))], eligible=5)
    assert _by("focus_face").score(ctx) == 0.0


def test_focus_face_zero_with_one_eligible():
    ctx = _ctx([V("e", 50, faces=F(0.1))], eligible=1)
    assert _by("focus_face").score(ctx) == 0.0


def test_focus_face_zero_without_faces():
    ctx = _ctx([V("e", 50)], eligible=5)
    assert _by("focus_face").score(ctx) == 0.0


def test_focus_face_hysteresis():
    d = _by("focus_face")
    e = [V("e", 50, faces=F(0.4))]
    assert d.score(_ctx(e)) == 0.0
    assert d.score(_ctx(e, current="focus_face")) == 1.2
    e = [V("e", 50, faces=F(0.55))]
    assert d.score(_ctx(e)) == 0.0
    assert d.score(_ctx(e, current="focus_face")) == 0.0


def test_focus_face_choose_slots_about_weak_face():
    ctx = _ctx([V("e", 50, faces=F(0.1))], eligible=5)
    c = _by("focus_face").choose(ctx)
    assert c.primary == "e"
    assert len(c.slot_dirs) == 3
    axis = attack.FACE_AXES[4]
    for d in c.slot_dirs:
        dot = sum(a * b for a, b in zip(d, axis))
        assert math.degrees(math.acos(min(1.0, dot))) <= 25.0 + 1e-6


def test_envelop_scores_healthy_target_three_eligible():
    ctx = _ctx([V("e", 50, faces=F())], eligible=3)
    assert _by("envelop").score(ctx) == 1.05
    assert _by("envelop").score(_ctx([V("e", 50, faces=F())], eligible=2)) == 0.0
    assert _by("envelop").score(_ctx([V("e", 50)], eligible=3)) == 0.0


def test_envelop_zero_when_a_face_weak():
    ctx = _ctx([V("e", 50, faces=F(0.2))], eligible=5)
    assert _by("envelop").score(ctx) == 0.0


def test_envelop_choose_rear_left_right():
    ctx = _ctx([V("e", 50, faces=F())], eligible=5)
    c = _by("envelop").choose(ctx)
    assert c.primary == "e"
    assert c.slot_dirs == attack.envelop_dirs(3)
    zero = _ctx([V("e", 50, faces=F())], eligible=0)
    c0 = _by("envelop").choose(zero)
    assert c0.slot_dirs == () and c0.primary == "e"


def _strong(name="big", x=60, **kw):
    return V(name, x, power=10.0, **kw)


def test_disable_scores_against_much_stronger():
    ctx = _ctx([_strong()])
    assert _by("disable").score(ctx) == 1.3


def test_disable_zero_when_weapons_down():
    ctx = _ctx([_strong(down=True)])
    assert _by("disable").score(ctx) == 0.0


def test_disable_zero_when_not_stronger_enough():
    ctx = _ctx([V("e", 50, power=6.0)])    # 6 < 1.5 * 5
    assert _by("disable").score(ctx) == 0.0
    assert _by("disable").score(_ctx([])) == 0.0
    assert _by("disable").score(_ctx([_strong(x=5000)])) == 0.0


def test_disable_choose_weapons_first_all_slots():
    ctx = _ctx([V("weak", 40, power=1.0), _strong(), V("mid", 70, power=2.0)],
               eligible=0)
    c = _by("disable").choose(ctx)
    assert c.primary == "big"
    assert c.weapons_first and c.slot_all
    assert "big" not in c.secondaries
    assert c.slot_dirs == attack.envelop_dirs(1)


def test_disable_beats_focus_beats_envelop_beats_swarm():
    e = [_strong(faces=F(0.1)), V("s", 40, power=0.1, faces=F())]
    ctx = _ctx(e, eligible=5)
    assert decisions.pick(ctx).name == "disable"
    ctx = _ctx([V("e", 50, faces=F(0.1))], eligible=5)
    assert decisions.pick(ctx).name == "focus_face"
    ctx = _ctx([V("e", 50, faces=F())], eligible=5)
    assert decisions.pick(ctx).name == "envelop"
    ctx = _ctx([V("e", 50, faces=F())], eligible=2)
    assert decisions.pick(ctx).name == "swarm_weakest"


def test_zero_score_no_stickiness_for_new_decisions():
    ctx = _ctx([_strong(down=True)], current="disable")
    assert decisions.pick(ctx).name != "disable"


# ── disable latch (final review I1) ────────────────────────────────────────

def _latched(enemies, primary="big", done=frozenset(), current="disable"):
    ctx = _ctx(enemies, current=current)
    ctx.current_primary = primary
    ctx.disable_done = done
    return ctx


def test_disable_latch_holds_below_the_gate():
    """Shield damage halves strength: once disabling, the target is held
    without the strength ratio being re-checked."""
    weak = V("big", 60, power=6.0)          # 6 < 1.5 * 5: under the gate
    assert _by("disable").score(_ctx([weak])) == 0.0
    ctx = _latched([weak])
    assert _by("disable").score(ctx) == 1.3
    c = _by("disable").choose(ctx)
    assert c.primary == "big" and c.weapons_first and c.slot_all


def test_disable_latch_holds_on_its_target_not_a_stronger_one():
    ctx = _latched([V("big", 60, power=6.0), V("huge", 70, power=20.0)])
    assert _by("disable").choose(ctx).primary == "big"


def test_disable_latch_ends_on_weapons_down_gone_or_out_of_reach():
    d = _by("disable")
    assert d.score(_latched([V("big", 60, power=6.0, down=True)])) == 0.0
    assert d.score(_latched([V("other", 60, power=20.0)])) == 0.0
    assert d.score(_latched([V("big", 5000, power=20.0)])) == 0.0


def test_disable_never_reenters_against_a_done_target():
    d = _by("disable")
    done = frozenset({"big"})
    assert d.score(_latched([_strong()], done=done, current=None)) == 0.0
    assert d.score(_latched([_strong()], done=done)) == 0.0
    # another strong ship in reach is still a disable target
    ctx = _latched([_strong(), _strong("big2", x=70)], primary=None,
                   done=done, current=None)
    assert d.score(ctx) == 1.3
    assert d.choose(ctx).primary == "big2"


def test_disable_with_no_current_primary_uses_the_gate():
    ctx = _latched([_strong()], primary=None)
    assert _by("disable").score(ctx) == 1.3
    ctx = _latched([V("e", 50, power=6.0)], primary=None)
    assert _by("disable").score(ctx) == 0.0
