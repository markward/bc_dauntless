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

# TGAnimPosition holds the clip's START frame (frame 0) for EVERY placement
# clip. The SetPosition clips are all "stand-up-from-station" / "move-from-
# station" sequences whose FRAME 0 is the officer at the console (the working
# pose) and whose LAST frame is the officer stood up / walked away. So the
# faithful rest pose is always frame 0 (sample_at_start=True).
#
# Confirmed in-GUI (2026-06-19): holding the LAST frame for the "stand" clips
# (the earlier db_StoL1/EtoL1/L1to heuristic, which classified only the
# move-FROM clips as frame-0 and let the rest play-and-hold to their end) left
# every standing officer frozen in the stood-up / leaving pose. Holding frame 0
# uniformly is the correct TGAnimPosition behaviour for all stations.


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
        # TGAnimPosition holds frame 0 (the at-station pose) for every clip.
        "sample_at_start": True,
    }
