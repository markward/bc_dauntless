"""Model-agnostic lip-sync controller: timeline (cross-fade + amplitude),
the speech controller (start/update/preempt/revert), and the idle blink
scheduler. No engine, no GL -- the controller emits viseme poses to a sink
callback, which is the reuse seam toward the renderer.
"""
import pytest

from engine.appc.lip_data import LipSegment
from engine.lip_sync import LipTimeline, LipSyncController, BlinkScheduler

# Synthetic table so these tests exercise controller LOGIC, independent of the
# recovered viseme data (which is validated separately in test_lip_visemes).
TABLE = {0: {"neutral": 1.0}, 1: {"a": 1.0}, 29: {"e": 1.0}}


def seg(code, start, dur):
    return LipSegment(code, start, dur)


# --- LipTimeline ------------------------------------------------------------

def test_pose_mid_segment_is_segment_viseme():
    tl = LipTimeline([seg(1, 0.0, 0.5), seg(0, 0.5, 0.5)], TABLE, t0=10.0)
    a, b, mix = tl.pose_at(10.25)  # mid first segment, past the cross-fade
    assert a == "a"
    assert mix == pytest.approx(0.0)


def test_neutral_before_start_and_after_end():
    tl = LipTimeline([seg(1, 0.0, 0.5)], TABLE, t0=10.0)
    assert tl.pose_at(9.0)[0] == "neutral"
    assert tl.done(10.5) is True
    assert tl.pose_at(11.0)[0] == "neutral"


def test_crossfade_blends_previous_into_new_segment():
    tl = LipTimeline([seg(1, 0.0, 0.30), seg(29, 0.30, 0.30)], TABLE, t0=0.0, xfade=0.06)
    w = tl.weights_at(0.31)  # 0.01 into seg1 -> within the 0.06 cross-fade
    assert w.get("a", 0) > 0 and w.get("e", 0) > 0  # blend of prev(a)+current(e)
    w2 = tl.weights_at(0.45)  # past the cross-fade -> pure current
    assert w2.get("e", 0) == pytest.approx(1.0)


def test_amplitude_zero_pulls_toward_neutral():
    tl = LipTimeline([seg(1, 0.0, 0.5)], TABLE, t0=0.0, amplitude=[0.0])
    w = tl.weights_at(0.25)
    assert w.get("neutral", 0) == pytest.approx(1.0)  # silent syllable -> closed


# --- LipSyncController ------------------------------------------------------

def test_controller_start_update_emits_pose():
    calls = []
    c = LipSyncController(sink=lambda *a: calls.append(a), table=TABLE)
    c.start("Picard", [seg(1, 0.0, 0.5), seg(0, 0.5, 0.5)], t0=0.0)
    c.update(0.25)
    assert calls[-1][0] == "Picard"
    assert calls[-1][1] == "a"


def test_controller_reverts_to_neutral_when_done_then_drops():
    calls = []
    c = LipSyncController(sink=lambda *a: calls.append(a), table=TABLE)
    c.start("Picard", [seg(1, 0.0, 0.2)], t0=0.0)
    c.update(0.5)  # past end
    assert calls[-1] == ("Picard", "neutral", "neutral", 0.0)
    calls.clear()
    c.update(0.6)  # timeline already dropped
    assert calls == []


def test_controller_preempt_replaces_timeline():
    calls = []
    c = LipSyncController(sink=lambda *a: calls.append(a), table=TABLE)
    c.start("Picard", [seg(29, 0.0, 1.0)], t0=0.0)   # 'e'
    c.start("Picard", [seg(1, 0.0, 1.0)], t0=0.5)    # preempt -> 'a'
    c.update(0.75)
    assert calls[-1][1] == "a"


# --- BlinkScheduler ---------------------------------------------------------

def test_blink_runs_stage_sequence_then_idles():
    # rng=0 + interval (1,1) -> blink fires exactly at now+1.
    bs = BlinkScheduler(rng=lambda: 0.0, interval=(1.0, 1.0), stage_dt=0.03)
    bs.arm("Picard", now=0.0)
    assert bs.slot_at("Picard", 0.5) is None       # before the blink
    assert bs.slot_at("Picard", 1.0) == "blink1"   # stage 0
    assert bs.slot_at("Picard", 1.03) == "blink2"  # stage 1
    assert bs.slot_at("Picard", 1.06) == "eyesclosed"  # stage 2
    # After the 5-stage sequence the eyes are open again (None).
    assert bs.slot_at("Picard", 1.0 + 5 * 0.03 + 0.001) is None
