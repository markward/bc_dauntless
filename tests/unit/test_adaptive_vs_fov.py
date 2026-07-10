import math
from engine import host_loop


class _Pt:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class _Target:
    def __init__(self, loc, radius):
        self._loc, self._r = loc, radius

    def GetWorldLocation(self):
        return self._loc

    def GetRadius(self):
        return self._r


def test_fov_clamps_to_max_when_very_close():
    # radius huge relative to distance -> clamp to VS_FOV_MAX
    t = _Target(_Pt(1.0, 0.0, 0.0), 100.0)
    fov = host_loop._adaptive_vs_fov(t, (0.0, 0.0, 0.0))
    assert abs(fov - host_loop.VS_FOV_MAX) < 1e-6


def test_fov_clamps_to_min_when_very_far():
    t = _Target(_Pt(100000.0, 0.0, 0.0), 1.0)
    fov = host_loop._adaptive_vs_fov(t, (0.0, 0.0, 0.0))
    assert abs(fov - host_loop.VS_FOV_MIN) < 1e-6


def test_fov_midrange_matches_formula():
    # choose r/dist so the clamp is not active: half = 1.6*6/100 = 0.096,
    # between tan(3deg)=0.052 and tan(20deg)=0.364.
    dist = 100.0
    r = 6.0
    t = _Target(_Pt(dist, 0.0, 0.0), r)
    fov = host_loop._adaptive_vs_fov(t, (0.0, 0.0, 0.0))
    expected = 2.0 * math.atan(host_loop.VS_FILL_K * r / dist)
    assert host_loop.VS_FOV_MIN <= fov <= host_loop.VS_FOV_MAX
    assert abs(fov - expected) < 1e-6


def test_fov_degenerate_zero_distance_is_max():
    t = _Target(_Pt(0.0, 0.0, 0.0), 5.0)
    fov = host_loop._adaptive_vs_fov(t, (0.0, 0.0, 0.0))
    assert abs(fov - host_loop.VS_FOV_MAX) < 1e-6
