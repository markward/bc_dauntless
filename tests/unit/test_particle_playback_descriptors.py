"""Library fields reach the render descriptor (spec 2026-10-16 §7.4, §7.5)."""
from engine.appc import particles as P


def test_descriptor_carries_library_fields_and_scaled_sizes():
    P.reset()
    c = P.AnimTSParticleController_Create()
    c.AddSizeKey(0.0, 2.0)
    c._playback, c._fps, c._pivot, c._orient = 2, 8.0, (0.0, -1.0), 1
    c._size_scale, c._roll_rate = 0.5, 2.0
    P.EffectAction_Create(c).Start()
    (d,) = P.snapshot_descriptors()
    assert (d["playback"], d["fps"], d["pivot"], d["orient"], d["roll_rate"]) == (2, 8.0, (0.0, -1.0), 1, 2.0)
    assert d["size_keys"] == [(0.0, 1.0)]
    P.reset()
