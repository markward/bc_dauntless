import pytest


# Determinant-normalization note (commit d1ac130 "fix(scale)"):
# The renderer is configured with glFrontFace(GL_CW) and expects det(world) < 0.
# Proper rotations (identity, MakeZRotation, etc. — det = +1) would render
# inside-out, so _ship_world_matrix / _astro_world_matrix negate the X body-axis
# column when det(rot) > 0. These tests assert that convention. When the coupled
# fix lands (AlignToVectors → proper rotation, pipeline.cc → glFrontFace(GL_CCW),
# backdrop/sun cull → GL_BACK), drop the X-column negation in expected values.


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
    """Identity rotation: upper-left 3x3 = diag(-s, +s, +s) under the d1ac130
    X-column negation (det(identity) = +1 → flip applied); translation is the
    world location unchanged."""
    from engine import host_loop

    pose = _make_pose(100.0, 200.0, 300.0)
    natural_scale = 0.5
    m = host_loop._ship_world_matrix(pose, natural_scale)

    assert len(m) == 16
    # Upper-left 3x3: identity * natural_scale with X axis negated (d1ac130).
    assert m[0]  == pytest.approx(-natural_scale)  # row0 col0 (X, flipped)
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
    BC column (X axis negated due to the d1ac130 X-flip)."""
    import math
    from engine import host_loop

    pose = _make_pose(0.0, 0.0, 0.0)
    pose._rot.MakeZRotation(math.radians(45))  # non-symmetric, det = +1

    natural_scale = 0.5
    m = host_loop._ship_world_matrix(pose, natural_scale)

    # Column j of the row-major mat4 lives at positions j, 4+j, 8+j.
    # It must equal R.GetCol(j) * natural_scale (BC body axis j in world),
    # with column 0 (X axis) negated under d1ac130 because det(rot) = +1.
    rgt = pose._rot.GetCol(0)
    fwd = pose._rot.GetCol(1)
    up  = pose._rot.GetCol(2)
    s = natural_scale

    assert m[0]  == pytest.approx(-rgt.x * s)
    assert m[4]  == pytest.approx(-rgt.y * s)
    assert m[8]  == pytest.approx(-rgt.z * s)
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

    # Column 0 (X axis) negated under d1ac130 because det(rot) = +1.
    assert m[0]  == pytest.approx(-rgt.x * s)
    assert m[4]  == pytest.approx(-rgt.y * s)
    assert m[8]  == pytest.approx(-rgt.z * s)
    assert m[1]  == pytest.approx(fwd.x * s)
    assert m[5]  == pytest.approx(fwd.y * s)
    assert m[9]  == pytest.approx(fwd.z * s)
    assert m[2]  == pytest.approx(up.x  * s)
    assert m[6]  == pytest.approx(up.y  * s)
    assert m[10] == pytest.approx(up.z  * s)


def test_astro_world_matrix_scales_mesh_and_position():
    """Identity rotation, natural_scale = radius/native: position is BC
    world-native (unchanged), mesh scaled by natural_scale with X axis
    negated under d1ac130 (det(identity) = +1 → flip applied)."""
    from engine import host_loop
    from engine.scale import PLANET_NIF_NATIVE_RADIUS

    pose = _make_pose(100.0, 200.0, 300.0, radius=170.0)
    natural_scale = 170.0 / PLANET_NIF_NATIVE_RADIUS  # ~3.78
    m = host_loop._astro_world_matrix(pose, natural_scale)

    assert len(m) == 16
    # Upper-left 3x3: identity * natural_scale, X negated (d1ac130).
    assert m[0]  == pytest.approx(-natural_scale)
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
