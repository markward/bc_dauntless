import pytest


# Right-handed convention (2026-06-18 un-mirror): _world_matrix_from sends the
# rotation to the GPU UNTOUCHED — no X-column negation. The old determinant-
# normalization flip (commit d1ac130) reflected every ship and was removed in
# concert with AlignToVectors (now right-handed, det > 0) and pipeline.cc
# (glFrontFace(GL_CCW)). See docs/superpowers/plans/2026-06-18-render-handedness-
# unmirror.md. These tests assert the un-reflected matrix (col0 positive).


def _make_pose(x, y, z, radius=0.0):
    """Minimal stand-in for a ship or planet object with the pose API."""
    from engine.appc.math import TGPoint3, TGMatrix3

    class _Pose:
        def __init__(self):
            self._loc = TGPoint3(x, y, z)
            self._rot = TGMatrix3()  # identity by default
            self._radius = radius

        def GetWorldLocation(self):
            return self._loc

        def GetWorldRotation(self):
            return self._rot

        def GetRadius(self):
            return self._radius

    return _Pose()


def test_ship_world_matrix_scales_mesh_not_position():
    """Identity rotation: upper-left 3x3 = diag(+s, +s, +s) — no reflection
    (right-handed un-mirror); translation is the world location unchanged."""
    from engine import host_loop

    pose = _make_pose(100.0, 200.0, 300.0)
    natural_scale = 0.5
    m = host_loop._ship_world_matrix(pose, natural_scale)

    assert len(m) == 16
    # Upper-left 3x3: identity * natural_scale, NOT negated.
    assert m[0]  == pytest.approx(natural_scale)  # row0 col0 (X)
    assert m[5]  == pytest.approx(natural_scale)   # row1 col1
    assert m[10] == pytest.approx(natural_scale)   # row2 col2
    # Off-diagonal rotation elements -> 0
    assert m[1]  == pytest.approx(0.0)
    assert m[4]  == pytest.approx(0.0)
    # Translation column: unchanged world position
    assert m[3]  == pytest.approx(100.0)
    assert m[7]  == pytest.approx(200.0)
    assert m[11] == pytest.approx(300.0)
    # Homogeneous row
    assert m[12] == pytest.approx(0.0)
    assert m[13] == pytest.approx(0.0)
    assert m[14] == pytest.approx(0.0)
    assert m[15] == pytest.approx(1.0)


def test_ship_world_matrix_columns_are_body_axes_in_world():
    """BC's TGMatrix3 is column-vector (cols = body axes in world; see
    CLAUDE.md ↦ "Rotation matrix convention"). The OpenGL shader also
    expects column-vector u_model, so the matrix is sent to the renderer
    *directly*, no transpose. Each output column must equal the matching
    BC column * scale — no reflection (right-handed un-mirror)."""
    import math
    from engine import host_loop

    pose = _make_pose(0.0, 0.0, 0.0)
    pose._rot.MakeZRotation(math.radians(45))  # non-symmetric, det = +1

    natural_scale = 0.5
    m = host_loop._ship_world_matrix(pose, natural_scale)

    # Column j of the row-major mat4 lives at positions j, 4+j, 8+j.
    # It must equal R.GetCol(j) * natural_scale (BC body axis j in world),
    # with NO X-column negation.
    rgt = pose._rot.GetCol(0)
    fwd = pose._rot.GetCol(1)
    up  = pose._rot.GetCol(2)
    s = natural_scale

    assert m[0]  == pytest.approx(rgt.x * s)
    assert m[4]  == pytest.approx(rgt.y * s)
    assert m[8]  == pytest.approx(rgt.z * s)
    assert m[1]  == pytest.approx(fwd.x * s)
    assert m[5]  == pytest.approx(fwd.y * s)
    assert m[9]  == pytest.approx(fwd.z * s)
    assert m[2]  == pytest.approx(up.x  * s)
    assert m[6]  == pytest.approx(up.y  * s)
    assert m[10] == pytest.approx(up.z  * s)


def test_astro_world_matrix_columns_are_body_axes_in_world():
    """Same row/column convention as ships, applied to planet/moon meshes
    so non-spherical astro objects render with their BC-convention body axes
    matching the camera/physics view."""
    import math
    from engine import host_loop
    from engine.scale import PLANET_NIF_NATIVE_RADIUS

    pose = _make_pose(0.0, 0.0, 0.0, radius=170.0)
    pose._rot.MakeZRotation(math.radians(45))

    # Caller computes natural_scale = GetRadius() / NIF_extent at load.
    natural_scale = 170.0 / PLANET_NIF_NATIVE_RADIUS
    m = host_loop._astro_world_matrix(pose, natural_scale)

    rgt = pose._rot.GetCol(0)
    fwd = pose._rot.GetCol(1)
    up  = pose._rot.GetCol(2)
    s = natural_scale

    # No X-column negation (right-handed un-mirror).
    assert m[0]  == pytest.approx(rgt.x * s)
    assert m[4]  == pytest.approx(rgt.y * s)
    assert m[8]  == pytest.approx(rgt.z * s)
    assert m[1]  == pytest.approx(fwd.x * s)
    assert m[5]  == pytest.approx(fwd.y * s)
    assert m[9]  == pytest.approx(fwd.z * s)
    assert m[2]  == pytest.approx(up.x  * s)
    assert m[6]  == pytest.approx(up.y  * s)
    assert m[10] == pytest.approx(up.z  * s)


def test_astro_world_matrix_scales_mesh_and_position():
    """Identity rotation, natural_scale = radius/native: position is BC
    world-native (unchanged), mesh scaled by natural_scale with NO X-column
    negation (right-handed un-mirror)."""
    from engine import host_loop
    from engine.scale import PLANET_NIF_NATIVE_RADIUS

    pose = _make_pose(100.0, 200.0, 300.0, radius=170.0)
    natural_scale = 170.0 / PLANET_NIF_NATIVE_RADIUS  # ~3.78
    m = host_loop._astro_world_matrix(pose, natural_scale)

    assert len(m) == 16
    # Upper-left 3x3: identity * natural_scale, NOT negated.
    assert m[0]  == pytest.approx(natural_scale)
    assert m[5]  == pytest.approx(natural_scale)
    assert m[10] == pytest.approx(natural_scale)
    # Off-diagonal rotation elements -> 0
    assert m[1]  == pytest.approx(0.0)
    assert m[4]  == pytest.approx(0.0)
    # Translation column: BC world-native position, no global multiplier
    assert m[3]  == pytest.approx(100.0)
    assert m[7]  == pytest.approx(200.0)
    assert m[11] == pytest.approx(300.0)
    # Homogeneous row
    assert m[15] == pytest.approx(1.0)


def test_world_matrix_from_matches_manual_build():
    from engine.appc.math import TGMatrix3, TGPoint3
    from engine.host_loop import _world_matrix_from

    rot = TGMatrix3(); rot.MakeYRotation(0.0)  # identity-ish, det +1
    loc = TGPoint3(3.0, -2.0, 5.0)
    m = _world_matrix_from(loc, rot, 0.5)
    # No reflection: scale 0.5 on all axes, col0 NOT negated.
    assert m[3] == 3.0 and m[7] == -2.0 and m[11] == 5.0  # translation
    assert m[0] == rot._m[0][0] * 0.5  # col0 not negated
    assert m[1] == rot._m[0][1] * 0.5
    assert m[15] == 1.0
