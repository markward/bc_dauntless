# tests/integration/test_camera_path_clip.py
"""Native load_animation_clips must parse the bridge camera-path NIF.

Requires the built _dauntless_host module and the game install. Skips
cleanly when either is absent (CI without assets)."""
import os
import pytest

from tests.helpers import bc_assets

renderer = pytest.importorskip("engine.renderer")

CAMERA_NIF = "data/animations/db_camera_walk_capt.nif"


@pytest.mark.skipif(
    not (bc_assets.GAME_ROOT / "data" / "animations" / "DB_Camera_Walk_Capt.NIF").is_file(),
    reason="game install not present",
)
def test_camera_path_clip_has_motion():
    # CAMERA_NIF is root-relative (matches every SDK-authored asset path);
    # the native side only resolves that against renderer.game_root(),
    # which host_loop's boot sets from the configured BC install (see
    # engine.paths). This test calls load_animation_clips() directly,
    # bypassing that boot wiring, so it must configure the same root
    # itself -- otherwise resolve_asset_path falls back to its
    # process-default "game" (cwd-relative), which is only ever correct
    # when a BC install happens to live at <project>/game. Restore the
    # default afterward so this test cannot leak native global state into
    # a later test in the same process.
    renderer.set_game_root(str(bc_assets.GAME_ROOT))
    try:
        clips = renderer.load_animation_clips(CAMERA_NIF)
    finally:
        renderer.set_game_root("game")
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
