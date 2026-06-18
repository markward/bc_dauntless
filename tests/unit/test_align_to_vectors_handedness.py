"""AlignToVectors must build a RIGHT-HANDED (det = +1) basis.

Historically BC's AlignToVectors built ``right = up × forward`` (det = -1, a
reflection), and the renderer compensated by negating the X column — which
drew every ship mirror-imaged (proven by backwards hull registry text). The
convention was converted to right-handed on 2026-06-18: ``right = forward × up``
(det = +1), so ``GetCol(0)`` is the TRUE starboard and the renderer draws R
directly with no reflection. See docs/superpowers/plans/2026-06-18-render-
handedness-unmirror.md.
"""
from engine.appc.math import TGPoint3
from engine.appc.objects import ObjectClass


def _det(R):
    m = R._m
    return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
          - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
          + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))


def test_align_to_vectors_is_right_handed():
    o = ObjectClass()
    o.AlignToVectors(TGPoint3(0.0, 1.0, 0.0), TGPoint3(0.0, 0.0, 1.0))
    R = o.GetWorldRotation()
    assert abs(_det(R) - 1.0) < 1e-9            # right-handed
    col0 = R.GetCol(0)
    assert (round(col0.x, 6), round(col0.y, 6), round(col0.z, 6)) == (1.0, 0.0, 0.0)  # +X starboard
    col1 = R.GetCol(1)
    assert (round(col1.x, 6), round(col1.y, 6), round(col1.z, 6)) == (0.0, 1.0, 0.0)  # +Y forward
    col2 = R.GetCol(2)
    assert (round(col2.x, 6), round(col2.y, 6), round(col2.z, 6)) == (0.0, 0.0, 1.0)  # +Z up


def test_align_to_vectors_arbitrary_is_right_handed():
    o = ObjectClass()
    o.AlignToVectors(TGPoint3(0.3, 0.9, 0.1), TGPoint3(0.0, 0.1, 1.0))
    assert abs(_det(o.GetWorldRotation()) - 1.0) < 1e-9
