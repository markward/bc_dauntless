# tests/integration/test_e6m1_bridge_cutscene_camera.py
"""E6M1's opening briefing cuts from Starbase 12 to the bridge
(ChangeRenderedSet("bridge") + PlacementWatch("bridge", "Felix Head",
"FelixCam2"), E6M1.py:1663-1708). The bridge shot must drive the bridge camera
and must not be treated as an exterior camera.
Spec: docs/superpowers/specs/2026-10-13-bridge-cutscene-camera-design.md §4"""
import math

import App
from engine.host_loop import (
    _BridgeCamera, _active_cutscene_camera, _bridge_cutscene_camera,
    _sync_bridge_mode_pose,
)
from tests.helpers import headless_mission as hm
from tests.helpers.headless_mission import no_logged_failures  # noqa: F401


def _on_bridge_shot():
    rs = App.g_kSetManager.get_explicit_rendered_set()
    return (rs is not None and rs.GetName() == "bridge"
            and _bridge_cutscene_camera() is not None)


def test_e6m1_briefing_cuts_to_the_bridge(no_logged_failures):
    hm.load("Maelstrom.Episode6.E6M1.E6M1")
    hm.tick_until(_on_bridge_shot, bound_s=90)

    assert _active_cutscene_camera() is None          # not an exterior shot

    cam = _BridgeCamera()
    _sync_bridge_mode_pose(cam, 0.0, exterior_active=False, paused=False)
    eye, target, _up, _fov = cam.compute_camera()

    bridge = App.g_kSetManager.GetSet("bridge")
    src = bridge.GetObject("FelixCam2").GetWorldLocation()
    head = bridge.GetObject("Felix Head").GetWorldLocation()
    assert math.isclose(eye[0], src.x, abs_tol=1e-4)
    assert math.isclose(eye[1], src.y, abs_tol=1e-4)
    assert math.isclose(eye[2], src.z, abs_tol=1e-4)
    # forward points at Felix Head
    f = [target[i] - eye[i] for i in range(3)]
    d = [head.x - eye[0], head.y - eye[1], head.z - eye[2]]
    nf = math.sqrt(sum(c * c for c in f))
    nd = math.sqrt(sum(c * c for c in d))
    assert sum(f[i] * d[i] for i in range(3)) / (nf * nd) > 0.999


def test_e6m1_briefing_releases_the_bridge_camera(no_logged_failures):
    hm.load("Maelstrom.Episode6.E6M1.E6M1")
    hm.tick_until(_on_bridge_shot, bound_s=90)
    hm.tick_until(lambda: _bridge_cutscene_camera() is None, bound_s=120)
    cam = _BridgeCamera()
    base = cam.compute_camera()
    cam.set_mode_pose((1.0, 1.0, 1.0), (1.0, 2.0, 1.0), (0.0, 0.0, 1.0))
    _sync_bridge_mode_pose(cam, 0.0, exterior_active=False, paused=False)
    assert cam.compute_camera() == base               # captain view back
