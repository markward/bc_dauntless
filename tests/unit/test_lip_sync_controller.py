"""Model-agnostic lip-sync controller: timeline (discrete viseme + cross-fade),
the speech controller (start/update/preempt/revert), and the idle blink
scheduler. No engine, no GL -- the controller emits viseme poses to a sink
callback, which is the reuse seam toward the renderer.
"""
import pytest

from engine.appc.lip_data import LipSegment
from engine.appc.phoneme_map import PhonemeMap
from engine.lip_sync import LipTimeline, LipSyncController, BlinkScheduler

# Synthetic map so these tests exercise controller LOGIC, independent of the
# recovered viseme data (which is validated separately in test_phoneme_map).
PM = PhonemeMap({
    "_visemes": {
        "closed": {"openness": 0.0, "texture": "neutral"},
        "open": {"openness": 1.0, "texture": "a"},
        "partly": {"openness": 0.5, "texture": "e"},
    },
    "0": "closed",
    "1": "open",
    "29": "partly",
})


def seg(code, start, dur):
    return LipSegment(code, start, dur)


# --- LipTimeline ------------------------------------------------------------

def test_pose_mid_segment_is_segment_viseme():
    tl = LipTimeline([seg(1, 0.0, 0.5), seg(0, 0.5, 0.5)], PM, t0=10.0)
    tex_a, tex_b, mix, openness = tl.pose_at(10.25)  # mid first segment, past cross-fade
    assert tex_a == "a"
    assert mix == pytest.approx(0.0)
    assert openness == pytest.approx(1.0)


def test_neutral_before_start_and_after_end():
    tl = LipTimeline([seg(1, 0.0, 0.5)], PM, t0=10.0)
    assert tl.pose_at(9.0)[0] == "neutral"
    assert tl.done(10.5) is True
    assert tl.pose_at(11.0)[0] == "neutral"


def test_crossfade_blends_previous_into_new_segment():
    tl = LipTimeline([seg(1, 0.0, 0.30), seg(29, 0.30, 0.30)], PM, t0=0.0, xfade=0.06)
    tex_a, tex_b, mix, openness = tl.pose_at(0.31)  # 0.01 into seg1 -> within the 0.06 cross-fade
    assert tex_a == "a" and tex_b == "e"  # blend of prev('a')+current('e')
    assert 0.0 < mix < 1.0
    tex_a2, tex_b2, mix2, openness2 = tl.pose_at(0.45)  # past the cross-fade -> pure current
    assert tex_a2 == tex_b2 == "e"
    assert mix2 == pytest.approx(0.0)


# --- LipSyncController ------------------------------------------------------

def test_controller_start_update_emits_pose():
    calls = []
    c = LipSyncController(sink=lambda *a: calls.append(a), phoneme_map=PM)
    c.start("Picard", [seg(1, 0.0, 0.5), seg(0, 0.5, 0.5)], t0=0.0)
    c.update(0.25)
    assert calls[-1][0] == "Picard"
    assert calls[-1][1] == "a"


def test_controller_reverts_to_neutral_when_done_then_drops():
    calls = []
    c = LipSyncController(sink=lambda *a: calls.append(a), phoneme_map=PM)
    c.start("Picard", [seg(1, 0.0, 0.2)], t0=0.0)
    c.update(0.5)  # past end
    assert calls[-1] == ("Picard", "neutral", "neutral", 0.0, 0.0)
    calls.clear()
    c.update(0.6)  # timeline already dropped
    assert calls == []


def test_controller_preempt_replaces_timeline():
    calls = []
    c = LipSyncController(sink=lambda *a: calls.append(a), phoneme_map=PM)
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
