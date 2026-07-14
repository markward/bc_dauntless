"""Regression: get_instance_head_center must classify head vertices by the
welded head/body partition (model->head_mesh_begin), not by the "Bip01 Head"
bone index.

BodyMaleM + miguel_head is one of the 4 bind-mismatched SDK pairs (see
native/tests/renderer/head_weld_seam_test.cc): the weld (§3.5) remaps every
grafted head vertex onto an ALIAS bone (name = body bone + "@head-bind"), not
onto the body skeleton's own "Bip01 Head" bone index. A classification that
tests bone index == "Bip01 Head" therefore misses the visible, welded head
vertices; the [model->head_mesh_begin, meshes.size()) mesh-range partition is
the one that always finds them (it's the same partition graft_head_cpu builds
and the renderer's bridge_pass.cc already uses for its own head/body split).
"""
import os
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GAME = PROJECT_ROOT / "game"
BODY_NIF = GAME / "data/Models/Characters/Bodies/BodyMaleM/BodyMaleM.NIF"
HEAD_NIF = GAME / "data/Models/Characters/Heads/HeadMiguel/miguel_head.NIF"
PLACEMENT_NIF = GAME / "data/animations/DB_stand_H_M.NIF"

pytestmark = pytest.mark.skipif(
    not all(p.exists() for p in [BODY_NIF, HEAD_NIF, PLACEMENT_NIF]),
    reason="needs game/ assets",
)


def test_head_center_uses_welded_head_on_mismatched_pair():
    """Compose the mismatched BodyMaleM + miguel_head pair, pose it at the
    placement clip's held ("stand") frame, and check the returned head centre
    lands at the WELDED head's height.

    Reference value (65.40 GU on Z) was measured against the fixed
    (head_mesh_begin-partition) classification on this exact pair/clip; it
    matches native/tests/renderer/head_weld_seam_test.cc's independently
    computed "Bip01 Head" bind-pose world Z (~62.3) to within that test's own
    8-unit tolerance. Reverting to the old bone-index classification (which
    falls through to the body's own unwelded, unrendered head mesh -- still
    present in model->meshes, just unlinked from the node walk -- rather than
    the visible welded head) was verified during test authoring to move this
    value to ~61.2, a ~4.2-unit shift; the 2.0-unit tolerance below is tight
    enough to catch that regression without being tripped by float jitter.
    """
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host

    try:
        _dauntless_host.init(640, 480, "test-get-instance-head-center")
    except RuntimeError as e:
        pytest.skip(f"no GL context available: {e}")
    try:
        h = _dauntless_host.assemble_officer(
            str(BODY_NIF), str(HEAD_NIF), None, None, str(PLACEMENT_NIF), False
        )
        assert h > 0
        iid = _dauntless_host.create_bridge_instance(h)

        # clip_index=0 is the placement clip baked in by assemble_officer;
        # at_start=False holds the LAST frame (stand pose), matching
        # engine/host_loop.py's _place_one_character.
        _dauntless_host.set_instance_rest_pose(iid, 0, False)
        _dauntless_host.frame()  # runs update_animations -> builds bone_palette

        head = _dauntless_host.get_instance_head_center(iid)
        assert head is not None, (
            "get_instance_head_center returned None -- bone_palette never "
            "populated (pose step regressed)"
        )
        _, _, z = head
        assert abs(z - 65.40) < 2.0, (
            f"head centre z={z!r} has drifted from the welded head's measured "
            "height (65.40 +/- 2.0) -- classification likely fell back to the "
            "bone-index test and picked up the body's unwelded ghost head "
            "mesh instead of the visible, welded one"
        )
    finally:
        _dauntless_host.shutdown()
