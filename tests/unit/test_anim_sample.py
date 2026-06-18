import math
from engine.anim_sample import sample_translation, sample_rotation, quat_rotate


def test_translation_lerp_and_clamp():
    keys = [(0.0, 0.0, 0.0, 0.0), (2.0, 10.0, -4.0, 2.0)]
    assert sample_translation(keys, -1.0) == (0.0, 0.0, 0.0)     # clamp low
    assert sample_translation(keys, 3.0) == (10.0, -4.0, 2.0)    # clamp high
    mid = sample_translation(keys, 1.0)
    assert mid == (5.0, -2.0, 1.0)                               # midpoint


def test_rotation_slerp_endpoints_and_midpoint():
    q0 = (0.0, 0.0, 0.0, 1.0)                       # identity
    # 90 deg about +Z
    q1 = (0.0, 0.0, math.sin(math.pi / 4), math.cos(math.pi / 4))
    keys = [(0.0, *q0), (1.0, *q1)]
    r0 = sample_rotation(keys, 0.0)
    assert all(abs(a - b) < 1e-6 for a, b in zip(r0, q0))
    # Midpoint = 45 deg about +Z.
    rm = sample_rotation(keys, 0.5)
    expected = (0.0, 0.0, math.sin(math.pi / 8), math.cos(math.pi / 8))
    assert all(abs(a - b) < 1e-6 for a, b in zip(rm, expected))


def test_quat_rotate_90_about_z():
    q = (0.0, 0.0, math.sin(math.pi / 4), math.cos(math.pi / 4))  # +90 Z
    x, y, z = quat_rotate(q, (1.0, 0.0, 0.0))
    assert abs(x - 0.0) < 1e-6 and abs(y - 1.0) < 1e-6 and abs(z) < 1e-6
