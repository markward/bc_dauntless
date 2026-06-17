# tests/integration/test_camera_path_clip.py
"""Native load_animation_clips must parse the bridge camera-path NIF.

Requires the built _dauntless_host module and the game install. Skips
cleanly when either is absent (CI without assets)."""
import os
import pytest

renderer = pytest.importorskip("engine.renderer")

CAMERA_NIF = "data/animations/db_camera_walk_capt.nif"


@pytest.mark.skipif(
    not os.path.exists("game/data/animations/DB_Camera_Walk_Capt.NIF"),
    reason="game install not present",
)
def test_camera_path_clip_has_motion():
    clips = renderer.load_animation_clips(CAMERA_NIF)
    assert len(clips) >= 1
    clip = clips[0]
    assert clip["duration"] > 0.0
    # At least one track must carry both translation and rotation keys —
    # the moving camera node.
    moving = [t for t in clip["tracks"]
              if t["translation"] and t["rotation"]]
    assert moving, "no track with translation+rotation keys"
    # Key tuples have the documented arity.
    assert len(moving[0]["translation"][0]) == 4   # (t, x, y, z)
    assert len(moving[0]["rotation"][0]) == 5       # (t, x, y, z, w)
