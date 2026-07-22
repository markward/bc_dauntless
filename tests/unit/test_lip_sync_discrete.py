from engine.appc.lip_data import LipSegment
from engine.appc.phoneme_map import default_phoneme_map
from engine.lip_sync import LipTimeline, LipSyncController


def test_pose_settles_on_current_viseme_after_xfade():
    pm = default_phoneme_map()
    segs = [LipSegment(56, 0.0, 0.5)]          # AA -> open / a / openness 1.0
    tl = LipTimeline(segs, pm, t0=0.0, xfade=0.06)
    tex_a, tex_b, mix, openness = tl.pose_at(0.3)   # well past xfade
    assert tex_a == "a"
    assert openness == 1.0


def test_pose_crossfades_openness_from_previous_viseme():
    pm = default_phoneme_map()
    # closed (openness 0) -> open (openness 1) at t=0.5, xfade 0.10
    segs = [LipSegment(0, 0.0, 0.5), LipSegment(56, 0.5, 0.5)]
    tl = LipTimeline(segs, pm, t0=0.0, xfade=0.10)
    _, _, _, op_mid = tl.pose_at(0.55)          # 0.05 into the 0.10 xfade -> ~0.5
    assert 0.3 < op_mid < 0.7


def test_controller_emits_jaw_channel_and_neutral_on_done():
    pm = default_phoneme_map()
    events = []
    ctrl = LipSyncController(sink=lambda *a: events.append(a), phoneme_map=pm)
    ctrl.start("Kiska", [LipSegment(56, 0.0, 0.2)], t0=0.0)
    ctrl.update(0.1)
    assert events[-1][0] == "Kiska" and len(events[-1]) == 5   # (name,a,b,mix,openness)
    ctrl.update(0.5)                                            # past end -> neutral+rest
    assert events[-1] == ("Kiska", "neutral", "neutral", 0.0, 0.0)


def test_runtime_sink_drives_face_and_jaw():
    from engine.lip_sync_runtime import LipSyncRuntime

    class _FakeR:
        def __init__(self): self.face = []; self.jaw = []
        def set_officer_face(self, iid, a, b, mix): self.face.append((iid, a, b, mix))
        def set_officer_jaw(self, iid, openness): self.jaw.append((iid, openness))

    class _Ch:
        _character_name = "Kiska"
        _render_instance = 7

    r = _FakeR()
    rt = LipSyncRuntime(r, lambda: [_Ch()])
    rt._sink("Kiska", "a", "a", 0.0, 1.0)
    assert r.face == [(7, "a", "a", 0.0)]
    assert r.jaw == [(7, 1.0)]
