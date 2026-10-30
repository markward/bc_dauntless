"""can_detect answers a repeated question once per combat stretch.

In a 64-ship fight the sensor check was ~a fifth of combat time, asked ~100
times a tick, and ~a third of those were repeats: a ship's phaser tick asks
what its held-weapon stop check just asked, and every torpedo it fired at the
same target asks it again. Inside an `engine.core.step_memo` block (the
combat step) a pair is computed once; `step_memo.forget()` (every
combat.apply_hit) drops the answers, because damage can change a sensor's
range or a cloak. Outside a block, every call computes, exactly as before.

Exact only because a repeat of the rule with unchanged inputs returns the
same answer and leaves the lock-break latch where the first call put it;
test_a_repeat_is_idempotent_across_the_latch pins that.
"""
import pytest

from engine.appc import combat, sensor_detection as sd
from engine.core import step_memo
from engine.appc.sensor_detection import can_detect


class _Obj:
    pass


@pytest.fixture
def computed(monkeypatch):
    calls = []

    def fake(observer, target, *, dist_sq_gu, apply_concealment, concealment):
        calls.append((observer, target))
        return target.visible
    monkeypatch.setattr(sd, "_can_detect", fake)
    return calls


def _pair(visible=True):
    a, b = _Obj(), _Obj()
    b.visible = visible
    return a, b


def test_outside_a_step_every_call_computes(computed):
    a, b = _pair()
    assert can_detect(a, b) and can_detect(a, b)
    assert len(computed) == 2


def test_inside_a_step_each_pair_is_computed_once(computed):
    a, b = _pair(True)
    c = _Obj()
    c.visible = False
    a.visible = True
    with step_memo.combat_step():
        assert [can_detect(a, b) for _ in range(3)] == [True] * 3
        assert can_detect(a, c) is False and can_detect(a, c) is False
        assert can_detect(b, a) is True
    assert computed == [(a, b), (a, c), (b, a)]
    can_detect(a, b)
    assert len(computed) == 4                 # the step is over


def test_explicit_arguments_always_compute(computed):
    a, b = _pair()
    with step_memo.combat_step():
        can_detect(a, b, dist_sq_gu=4.0)
        can_detect(a, b, dist_sq_gu=4.0)
        can_detect(a, b, concealment=0.0)
        can_detect(a, b, apply_concealment=False)
    assert len(computed) == 4


def test_forget_drops_the_answers(computed):
    a, b = _pair()
    with step_memo.combat_step():
        can_detect(a, b)
        step_memo.forget()
        can_detect(a, b)
    assert len(computed) == 2


def test_a_nested_step_shares_the_answers(computed):
    a, b = _pair()
    with step_memo.combat_step():
        can_detect(a, b)
        with step_memo.combat_step():
            can_detect(a, b)
        can_detect(a, b)
    assert len(computed) == 1


def test_every_hit_forgets_before_and_after(monkeypatch):
    seen = []
    monkeypatch.setattr(step_memo, "forget", lambda: seen.append("forget"))

    def inner(*a, **k):
        seen.append("hit")
        raise RuntimeError("boom")
    monkeypatch.setattr(combat, "_apply_hit", inner)
    with pytest.raises(RuntimeError):
        combat.apply_hit(object(), 1.0, None, None)
    assert seen == ["forget", "hit", "forget"]


@pytest.mark.parametrize("latched", [False, True])
@pytest.mark.parametrize("offset", [-0.2, -1e-9, 0.0, 0.5, 1.0, 1.0 + 1e-9,
                                    1.5])
def test_a_repeat_is_idempotent_across_the_latch(latched, offset):
    """The answer and the latch after two identical calls equal those after
    one, for concealment across and around the hysteresis band."""
    from engine.appc.ships import ShipClass_Create
    from engine.appc.subsystems import SensorSubsystem
    obs = ShipClass_Create("Galaxy")
    sensors = SensorSubsystem("Sensors")
    sensors._max_condition = sensors._condition = 100.0
    sensors.SetBaseSensorRange(2000.0)
    obs.SetSensorSubsystem(sensors)
    tgt = ShipClass_Create("Galaxy")
    tgt.SetTranslateXYZ(100.0, 0.0, 0.0)
    lo = sd.LOCK_BREAK_T - sd.HYSTERESIS
    conceal = lo + offset * sd.HYSTERESIS
    sd._set_latched(obs, tgt, latched)
    first = sd._can_detect(obs, tgt, dist_sq_gu=None, apply_concealment=True,
                           concealment=conceal)
    after_first = sd._latched(obs, tgt)
    second = sd._can_detect(obs, tgt, dist_sq_gu=None,
                            apply_concealment=True, concealment=conceal)
    assert second == first
    assert sd._latched(obs, tgt) == after_first

