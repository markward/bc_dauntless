"""SPIKE — confirm gesture clips retarget onto the officer skeleton.

Gates Tasks 4-7 (idle gestures + hit reactions).

Evidence-based approach
-----------------------
The brief's draft test compared against load_animation_clips(BODY_NIF), but a
skinned body/officer NIF contains no keyframe clips — the reader returns [] and
the comparison produces a false negative.

Instead we compare the gesture clip's track node names against a KNOWN-WORKING
placement clip (e.g. DB_stand_H_M.NIF) that already drives officers in Task 2.
Both clips use the "Bip01 ..." biped naming family.  If the gesture's node set
is a subset of the placement clip's node set, the retarget mechanism works by
the same lookup: the renderer walks gesture tracks, finds each "Bip01 ..." bone
in the assembled officer skeleton, and drives it — identical to how placement
clips already drive officers.

Findings (2026-06-19)
---------------------
Gesture  react_console_left.NIF  → 31 tracks, all "Bip01 ..." names.
Placement DB_stand_H_M.NIF       → 41 tracks, 31 "Bip01 ..." + 10 "Dummy..." prop nodes.
Overlap:  31 / 31  (gesture nodes ⊆ placement nodes, Dummy nodes are irrelevant props).

Verdict: RETARGET-OK — proceed to Tasks 4-7.
"""
import pathlib

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
GAME = PROJECT_ROOT / "game"
GESTURE_NIF = GAME / "data" / "animations" / "react_console_left.NIF"
PLACEMENT_NIF = GAME / "data" / "animations" / "DB_stand_H_M.NIF"

pytestmark = pytest.mark.skipif(
    not (GESTURE_NIF.exists() and PLACEMENT_NIF.exists()),
    reason="needs game/ assets",
)


def test_gesture_tracks_subset_of_placement_rig():
    """Gesture clip node names are a strict subset of the placement clip's node
    names, confirming both clips target the same Bip01 biped rig.  The
    placement clips already drive officers successfully (Task 2), so gesture
    clips will retarget by the identical mechanism."""
    from engine import renderer

    gesture_clips = renderer.load_animation_clips(str(GESTURE_NIF))
    assert gesture_clips, f"gesture NIF parsed to zero clips: {GESTURE_NIF}"

    placement_clips = renderer.load_animation_clips(str(PLACEMENT_NIF))
    assert placement_clips, f"placement NIF parsed to zero clips: {PLACEMENT_NIF}"

    gesture_nodes = {t["node"] for clip in gesture_clips for t in clip["tracks"]}
    placement_nodes = {t["node"] for clip in placement_clips for t in clip["tracks"]}

    assert gesture_nodes, "gesture clip has no tracks"
    assert placement_nodes, "placement clip has no tracks"

    # All gesture clip nodes must appear in the placement clip's rig.
    missing = gesture_nodes - placement_nodes
    assert not missing, (
        f"Gesture clip targets {len(missing)} node(s) absent from the placement rig — "
        f"retargeting will fail.\n"
        f"Missing: {sorted(missing)}\n"
        f"Gesture nodes ({len(gesture_nodes)}): {sorted(gesture_nodes)}\n"
        f"Placement nodes ({len(placement_nodes)}): {sorted(placement_nodes)}"
    )

    # Sanity: gesture nodes must all be Bip01 biped names (same family as placement).
    non_bip = {n for n in gesture_nodes if not n.startswith("Bip01")}
    assert not non_bip, (
        f"Unexpected non-Bip01 names in gesture clip: {sorted(non_bip)}"
    )

    # Report the overlap for transparency.
    overlap = gesture_nodes & placement_nodes
    assert len(overlap) == len(gesture_nodes), (
        f"Only {len(overlap)}/{len(gesture_nodes)} gesture nodes in placement rig"
    )
