"""E1M2's six SetScale(3) debris rocks: the viewscreen feed must frame each
one whole from the first frame (spec 2026-10-20-target-zoom-fit-design.md).

Headless there is no renderer, so no hull box is cached and the sphere path
of the solver runs -- that is the case under test (rocks are spheres).
"""
import math

import pytest

from engine import host_loop
from engine.appc.bridge_set import CameraObjectClass_Create
from engine.appc.camera_modes import _target_radius
from engine.cameras.zoom_fit import FIT_MARGIN
from tests.integration.test_sdk_bridge_load import _fresh_world

E1M2_MODULE = "Maelstrom.Episode1.E1M2.E1M2"
NAMES = ["Debris%d" % i for i in range(1, 7)]


def _d(a, b):
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def _xyz(p):
    return (p.x, p.y, p.z)


def test_viewscreen_frames_each_e1m2_debris_rock_from_the_start(monkeypatch):
    import MissionLib
    _fresh_world()
    _m, _e, _g, mod = host_loop._init_mission(E1M2_MODULE)
    player = MissionLib.GetPlayer()
    vesuvi = player.GetContainingSet()
    rocks = [vesuvi.GetObject(n) for n in NAMES]
    if any(r is None for r in rocks):
        mod.CreateDebris()
        rocks = [vesuvi.GetObject(n) for n in NAMES]
    assert all(r is not None for r in rocks)
    for r in rocks:
        assert r.GetScale() == 3

    cam = CameraObjectClass_Create(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0,
                                   "MainPlayerCamera")

    class _Game:
        def GetPlayerCamera(self):
            return cam
    monkeypatch.setattr(host_loop, "Game_GetCurrentGame", lambda: _Game())

    assert _target_radius(vesuvi.GetObject("Debris4")) == pytest.approx(15.0, rel=0.05)

    tan_v = math.tan(0.61 / 2.0)
    r_player = _target_radius(player)
    rows = []
    for rock in rocks:
        host_loop._VS_ZOOM_SMOOTHER.reset()
        cam._vs_last_player_target = None
        player.SetTarget(rock)
        out = host_loop._viewscreen_scene_feed(player, 0.61, None)
        assert out is not None, rock.GetName()
        eye = out[0]
        centre = _xyz(rock.GetWorldLocation())
        ppos = _xyz(player.GetWorldLocation())
        r = _target_radius(rock)
        d_eye, d_player = _d(eye, centre), _d(ppos, centre)
        rows.append((rock.GetName(), r, d_player, d_eye))
        assert d_eye >= r - 1e-6, rows[-1]                 # (a) outside
        assert d_eye <= d_player + 1e-6, rows[-1]          # (b) not behind player
        fit = r / ((1.0 - FIT_MARGIN) * math.sin(math.atan(tan_v)))
        if d_player - r_player >= fit:                     # (c) whole rock in frame
            ndc = math.tan(math.asin(r / d_eye)) / tan_v
            assert ndc <= 0.9 + 1e-6, rows[-1]
