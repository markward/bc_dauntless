"""zoom_fit: fit-to-frame distance, player cap, surface rule, smoothing."""
import math
from types import SimpleNamespace

import pytest

from engine.cameras import zoom_fit as zf


def _v(x, y, z):
    return SimpleNamespace(x=x, y=y, z=z)


class _Rot:
    def __init__(self, cols):
        self._c = cols

    def GetCol(self, i):
        return _v(*self._c[i])


IDENT = _Rot([(1, 0, 0), (0, 1, 0), (0, 0, 1)])


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _rotz(a):
    c, s = math.cos(a), math.sin(a)
    return [(c, s, 0), (-s, c, 0), (0, 0, 1)]


def _rotx(a):
    c, s = math.cos(a), math.sin(a)
    return [(1, 0, 0), (0, c, s), (0, -s, c)]


def _apply(cols, v):
    return tuple(sum(cols[j][i] * v[j] for j in range(3)) for i in range(3))


def _ndc(p, eye, fwd, up, fov_y, aspect):
    right = _cross(fwd, up)
    q = tuple(p[i] - eye[i] for i in range(3))
    x, y, z = _dot(q, right), _dot(q, up), _dot(q, fwd)
    tv = math.tan(fov_y / 2)
    return x / (z * tv * aspect), y / (z * tv)


def _corners(ext):
    out = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            for sz in (-1, 1):
                l = (sx * ext.half[0], sy * ext.half[1], sz * ext.half[2])
                w = _apply(ext.axes, l)
                out.append(tuple(ext.centre[i] + w[i] for i in range(3)))
    return out


def test_sphere_fit_puts_the_silhouette_at_ninety_percent():
    ext = zf.TargetExtent((0, 0, 0), None, None, 15.0)
    fov = math.radians(35)
    d = zf.fit_distance(ext, (0, 1, 0), (0, 0, 1), fov, 16 / 9)
    assert d == pytest.approx(15 / (0.9 * math.sin(math.radians(17.5))))


AXES = {
    "side": [(1, 0, 0), (0, 1, 0), (0, 0, 1)],
    "nose": _rotz(math.pi / 2),
    "yawpitch": [_apply(_rotx(math.radians(20)), c)
                 for c in _rotz(math.radians(30))],
}


@pytest.mark.parametrize("orient", ["side", "nose", "yawpitch"])
@pytest.mark.parametrize("aspect", [16 / 9, 4 / 3, 640 / 360])
def test_box_fit_keeps_every_corner_inside_the_margin(orient, aspect):
    centre = (10.0, -5.0, 3.0)
    ext = zf.TargetExtent(centre, tuple(AXES[orient]), (2.3, 8.0, 0.7), 8.5)
    fwd, up = (0, 1, 0), (0, 0, 1)
    fov = math.radians(35)
    d = zf.fit_distance(ext, fwd, up, fov, aspect)
    eye = tuple(centre[i] - d * fwd[i] for i in range(3))
    m = 0.0
    for p in _corners(ext):
        nx, ny = _ndc(p, eye, fwd, up, fov, aspect)
        assert abs(nx) <= 0.9 + 1e-6 and abs(ny) <= 0.9 + 1e-6
        m = max(m, abs(nx), abs(ny))
    assert m == pytest.approx(0.9, abs=1e-6)


def test_box_fit_frames_a_long_hull_tighter_than_its_sphere():
    half = (2.3, 8.0, 0.7)
    box = zf.TargetExtent((0, 0, 0), tuple(AXES["side"]), half, 8.5)
    rad = math.sqrt(sum(h * h for h in half))
    sph = zf.TargetExtent((0, 0, 0), None, None, rad)
    args = ((1, 0, 0), (0, 0, 1), math.radians(35), 16 / 9)
    assert zf.fit_distance(box, *args) < zf.fit_distance(sph, *args)


def test_surface_distance_box_and_sphere():
    box = zf.TargetExtent((0, 0, 0), tuple(AXES["side"]), (5, 10, 2), 11.0)
    assert zf.surface_distance(box, (0, 1, 0)) == pytest.approx(10)
    sph = zf.TargetExtent((0, 0, 0), None, None, 15.0)
    assert zf.surface_distance(sph, (0, 1, 0)) == pytest.approx(15)


def test_cap_spills_when_the_player_is_close():
    assert zf.zoom_target_distance(
        d_fit=60, zoom=1, player_dist=40, r_player=4, d_surface=15) == 36


def test_surface_wins_over_own_hull_when_hugging():
    assert zf.zoom_target_distance(
        d_fit=600, zoom=1, player_dist=130, r_player=4, d_surface=128) == 128


def test_never_behind_the_player_even_inside_the_surface():
    assert zf.zoom_target_distance(
        d_fit=600, zoom=1, player_dist=100, r_player=4, d_surface=150) == 100


def test_planet_in_low_orbit_keeps_the_eye_outside_the_sphere():
    ext = zf.TargetExtent((0, 0, 0), None, None, 900.0)
    d_fit = zf.fit_distance(ext, (0, 1, 0), (0, 0, 1), math.radians(35), 16 / 9)
    d = zf.zoom_target_distance(
        d_fit=d_fit, zoom=1, player_dist=1050, r_player=4,
        d_surface=zf.surface_distance(ext, (0, 1, 0)))
    assert 900 <= d <= 1050


def test_target_extent_without_a_box_is_a_sphere_at_the_pose():
    class Plain:
        def GetRadius(self):
            return 2.0

    ext = zf.target_extent(Plain(), _v(1, 2, 3), IDENT)
    assert ext.axes is None and ext.half is None
    assert tuple(ext.centre) == (1, 2, 3)
    assert ext.radius == 2


def test_target_extent_box_centre_is_offset_through_the_rotation():
    class Boxed:
        _shield_hull_box = ((0, 1, 0), (1, 2, 1))

        def GetRadius(self):
            return 2.0

    ext = zf.target_extent(Boxed(), _v(10, 0, 0), _Rot(_rotz(math.pi / 2)))
    assert ext.centre == pytest.approx((9, 0, 0))
    assert ext.half == (1, 2, 1)


def test_smoother_eases_snaps_on_retarget_and_holds_when_paused():
    s = zf.DistanceSmoother()
    assert s.step("a", 10, None) == 10
    v = s.step("a", 20, 0.25)
    assert v == pytest.approx(10 + 10 * (1 - math.exp(-1)))
    assert s.step("a", 20, 0.0) == v
    assert s.step("b", 50, 0.1) == 50
    s.reset()
    assert s.step("b", 7, 0.1) == 7
