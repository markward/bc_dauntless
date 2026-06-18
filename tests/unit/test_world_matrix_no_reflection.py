"""The render world matrix must NOT negate the X column.

The old _world_matrix_from negated body-X when det(rot) > 0 to force det < 0
(satisfying the old glFrontFace(GL_CW)). That negation reflected the model —
the cause of mirrored hull registry text. Post un-mirror (2026-06-18) the
rotation goes to the GPU untouched. See docs/superpowers/plans/2026-06-18-
render-handedness-unmirror.md.

_world_matrix_from returns a flat 16-element row-major list:
  [m00, m01, m02, tx,  m10, m11, m12, ty,  m20, m21, m22, tz,  0,0,0,1]
Column 0 (the body-X basis, scaled) lives at indices 0, 4, 8.
"""
from engine.appc.math import TGPoint3, TGMatrix3
from engine.host_loop import _world_matrix_from


def test_world_matrix_does_not_negate_x_for_det_pos():
    R = TGMatrix3()  # identity, det +1
    m = _world_matrix_from(TGPoint3(0.0, 0.0, 0.0), R, 2.0)
    # Column 0 must be (+2, 0, 0) — NOT negated to (-2, 0, 0).
    assert m[0] == 2.0
    assert m[4] == 0.0
    assert m[8] == 0.0
    # Columns 1 and 2 keep positive scale.
    assert m[5] == 2.0   # m11
    assert m[10] == 2.0  # m22


def test_world_matrix_preserves_det_neg_rotation_unchanged():
    # A det<0 rotation (legacy / stray placement) is ALSO passed through
    # untouched now — no conditional flip remains.
    R = TGMatrix3()
    R.SetCol(0, TGPoint3(-1.0, 0.0, 0.0))  # det = -1
    m = _world_matrix_from(TGPoint3(0.0, 0.0, 0.0), R, 1.0)
    assert m[0] == -1.0  # col0 passed through, not re-negated to +1
