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


def _resolve_builder_sequence(character, suffix):
    """Look up the SDK-registered builder for ``<location>+suffix`` and call it.

    Returns the resulting TGSequence if it is non-None and has at least one
    action, else None.  Wraps the import / builder call in try/except so any
    import error or builder exception collapses to None.
    """
    import importlib
    import App  # noqa: F401 — side-effects: registers path_for entries

    location = character.GetLocation()
    if not location:
        return None
    key = str(location) + suffix
    module_path = None
    for entry in getattr(character, "_animations", []):
        if entry and len(entry) >= 2 and str(entry[0]) == key:
            module_path = entry[1]
            break
    if not module_path:
        return None

    try:
        mod_name, func_name = module_path.rsplit(".", 1)
        func = getattr(importlib.import_module(mod_name), func_name)
        seq = func(character)
    except Exception:
        return None
    if seq is None or seq.GetNumActions() == 0:
        return None
    return seq


def _nif_path_for_clip(clip_name):
    """Return the data-root-relative NIF path for *clip_name*, or None/falsy."""
    import App
    return App.g_kAnimationManager.path_for(clip_name)


def capture_registered_clip(character, suffix):
    """Resolve the officer's SDK-registered "<location>"+suffix animation to its
    clip NIF, or None.

    The registered entry's module path is called as the SDK builder; the last
    action's clip name resolves to a NIF via path_for. Used for the layered
    idle/turn clips (suffix "Breathe", "BreatheTurned", "TurnCaptain",
    "BackCaptain"). Returns {"clip_nif": <data-root-relative path>} or None
    (no location / no <location>+suffix registration / unresolvable).
    """
    seq = _resolve_builder_sequence(character, suffix)
    if seq is None:
        return None
    # Seated TurnCaptain sequences interleave the officer's BODY clip (on the
    # character's anim node, kind="character") with the CHAIR clip (on the
    # bridge set node, kind="object") — and the chair comes LAST. Pick the last
    # action targeting the CHARACTER so we get the officer's actual turn clip,
    # not the bridge chair animation. Fall back to the last action.
    action = None
    for i in range(seq.GetNumActions() - 1, -1, -1):
        a = seq.GetAction(i)
        if getattr(getattr(a, "_anim_node", None), "kind", None) == "character":
            action = a
            break
    if action is None:
        action = seq.GetAction(seq.GetNumActions() - 1)
    clip_name = getattr(action, "_clip", "") or getattr(action, "name", "")
    if not clip_name:
        return None

    clip_nif = _nif_path_for_clip(clip_name)
    if not clip_nif:
        _logger.warning("capture_registered_clip: no path for %r", clip_name)
        return None
    return {"clip_nif": clip_nif}


def capture_chair_clip(character, suffix):
    """The CHAIR clip from a multi-action TurnCaptain/BackCaptain builder: the
    last action whose anim node is the BRIDGE node (kind=="object"), e.g.
    db_chair_H_face_capt. Returns {"clip_nif": path} or None when the builder
    has no object action or no resolvable path. Shares builder resolution with
    capture_registered_clip (DRY)."""
    seq = _resolve_builder_sequence(character, suffix)
    if seq is None:
        return None
    action = None
    for i in range(seq.GetNumActions() - 1, -1, -1):
        a = seq.GetAction(i)
        if getattr(getattr(a, "_anim_node", None), "kind", None) == "object":
            action = a
            break
    if action is None:
        return None
    clip_name = getattr(action, "_clip", "") or getattr(action, "name", "")
    path = _nif_path_for_clip(clip_name)
    if not path:
        _logger.warning("capture_chair_clip: no path for %r", clip_name)
        return None
    return {"clip_nif": path}


def capture_breathing(character):
    """The officer's looping breathe idle clip (SDK "<location>Breathe"), or None."""
    return capture_registered_clip(character, "Breathe")
