"""capture_placement — read an officer's station placement from the SDK.

The SDK's authoritative station-placement logic is
Bridge/Characters/CommonAnimations.py::SetPosition(pCharacter): a switch on
pCharacter.GetLocation() that, for the matched branch, does

    kAM.LoadAnimation("data/animations/db_stand_t_l.nif", "db_stand_t_l")
    pSequence.AppendAction(App.TGAnimPosition_Create(pAnimNode, "db_stand_t_l"))

and, for the "moving-to-L1" branches, also calls pCharacter.SetHidden(1).

SetPosition is never called from SDK Python — the original C++ engine invokes it
post-load. We invoke the same SDK function to CAPTURE the clip it selects (no
invented location->clip table), the same recording pattern step 3 used for
g_kModelManager.LoadModel -> env_for. The selected clip name is read back from
the TGSequence SetPosition returns; its NIF path comes from
App.g_kAnimationManager.path_for.

Headless: imports SDK Python only (no renderer). SDK is importable via
conftest._SDKFinder (tests) / tools.mission_harness.setup_sdk (live).
"""
import logging

_logger = logging.getLogger(__name__)

# Clip-name fragments whose station end is frame 0: the move-FROM-station clips.
# sample_at_start=True holds the officer at frame 0 (standing at the console)
# instead of letting the clip walk them away. This covers the standard visible
# bridge crew: Science (db_StoL1_S) and Engineer (db_EtoL1_s). In-place
# "stand"/"seated" clips contain none of these and correctly play-and-hold
# (sample_at_start=False) — e.g. EBridge Science's EB_stand_s_s, so the rule
# keys off the clip name, not the station role.
#
# Known-incomplete by design: the SDK has other transition clips this list does
# NOT match (EB_L2toG2_M, EB_G*toL*_M gallery walks, DB/EB_C1toC_M). Those are
# either hidden locations (SetHidden(1) -> the caller skips them regardless) or
# non-standard E-Bridge gallery/seat positions outside the standard-crew path.
# sample_at_start is a live-tunable heuristic (see the step-4 design doc); extend
# this list only after visually verifying the affected clip against the renderer.
_FRAME0_FRAGMENTS = ("stol1", "etol1", "l1to")


def _samples_at_start(clip_name: str) -> bool:
    low = clip_name.lower()
    return any(frag in low for frag in _FRAME0_FRAGMENTS)


def capture_placement(character):
    """Return the officer's station placement, or None when unplaceable.

    {"clip_nif": <data-root-relative path>, "hidden": bool,
     "sample_at_start": bool}, or None if the character has no location or no
    matching SetPosition branch (nothing to place).
    """
    import App
    import Bridge.Characters.CommonAnimations as _CommonAnim

    seq = _CommonAnim.SetPosition(character)
    # The matched branch appends exactly one TGAnimPosition; an unmatched /
    # empty location appends none.
    if seq is None or seq.GetNumActions() == 0:
        return None
    action = seq.GetAction(seq.GetNumActions() - 1)
    clip_name = getattr(action, "name", "")
    if not clip_name:
        return None

    clip_nif = App.g_kAnimationManager.path_for(clip_name)
    if not clip_nif:
        _logger.warning("capture_placement: no path recorded for clip %r", clip_name)
        return None

    hidden = bool(character.IsHidden())
    return {
        "clip_nif": clip_nif,
        "hidden": hidden,
        "sample_at_start": _samples_at_start(clip_name),
    }
