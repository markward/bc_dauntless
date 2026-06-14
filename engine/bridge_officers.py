"""SP3: place populated bridge officers at their stations (posed + appearance).

Ties together the SP3 building blocks: for each populated bridge-crew
CharacterClass, resolve its station placement clip, assemble its
per-character body+head model PRE-POSED to the placement clip's rest frame,
create a bridge render instance, and pin the instance into bridge-set space.

SP3 pivot — NODE posing, not GPU palette skinning. BC bodies are rigid
NiTriShapes parented to Bip01 NiNodes, so assemble_officer bakes the
placement clip's rest pose into the model's node-local transforms and clears
the skeleton; the officer then renders as a STATIC posed model through the
bridge node-walk (no palette, no inverse-bind). The placement clip's root
track carries the station offset, so the instance's own world transform is
the bridge set's identity space here (the bridge geometry renders at world
identity). The exact Z-up / X-flip parity and root offset are a live-tuning
concern; identity is the simplest starting point.

`host` is the _dauntless_host bindings module (or a fake in tests) exposing:
  resolve_placement(location)        -> {"nif": str(rel), "hidden": bool} | None
  assemble_officer(b_nif, h_nif, b_tex, h_tex, placement_nif) -> ModelHandle
  create_bridge_instance(model)      -> InstanceId
  set_world_transform(iid, mat4)
  destroy_instance(iid)              (used to clean up on mid-placement failure)

`data_root` is the absolute game data root (e.g. ".../game"); the placement
NIF path from resolve_placement is data-root-relative and is joined here the
same way host_loop joins bridge/ship NIF paths.
"""
import logging
import os
import sys

_logger = logging.getLogger(__name__)


def _dbg(msg):
    # TEMP SP3 diagnostic (remove after placement is verified): print to stderr
    # so it surfaces in the terminal regardless of logging config.
    print("[SP3] " + msg, file=sys.stderr)
    sys.stderr.flush()

# Bridge-set-space transform for each officer instance. The placement clip's
# root bone (in the palette) carries the station position, so the instance
# itself sits at the bridge origin. Row-major identity (set_world_transform
# transposes on input).
_BRIDGE_IDENTITY_MAT4 = [
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
]


def place_officers(officers, host, data_root):
    """Render each officer posed at its station. Returns the list of placed
    InstanceIds (for later teardown).

    Officers with no location, an unknown/hidden location, or no body NIF are
    skipped. Every officer is wrapped so one bad NIF can't abort the rest.
    """
    _dbg("place_officers: %d officer(s) enumerated, data_root=%s"
         % (len(list(officers)), data_root))
    placed = []
    for off in officers:
        try:
            iid = _place_one(off, host, data_root)
        except Exception:
            name = ""
            try:
                name = off.GetCharacterName()
            except Exception:
                pass
            _logger.exception("place_officers: failed to place %r", name)
            continue
        if iid is not None:
            placed.append(iid)
    return placed


def _place_one(off, host, data_root):
    try:
        _name = off.GetCharacterName()
    except Exception:
        _name = "?"
    loc = off.GetLocation()
    _dbg("officer %r: location=%r" % (_name, loc))
    # GetLocation() returns "" before ConfigureCharacters runs, or a Location
    # object in some SDK forms. Only station-name strings are placeable.
    if not loc or not isinstance(loc, str):
        _dbg("  -> SKIP (no/non-str location)")
        return None
    placement = host.resolve_placement(loc)
    _dbg("  resolve_placement(%r) -> %r" % (loc, placement))
    if not placement or placement.get("hidden"):
        _dbg("  -> SKIP (unknown/hidden)")
        return None

    ap = off.appearance()
    _dbg("  appearance=%r" % (ap,))
    if not ap.get("body_nif"):
        _dbg("  -> SKIP (no body_nif)")
        return None

    # The appearance paths from the SDK config are data-root-relative
    # (e.g. "data/Models/Characters/Bodies/BodyMaleL/BodyMaleL.nif"); the host
    # opens files relative to CWD, so join them to the game data root the same
    # way the placement NIF is resolved.
    def _abs(p):
        return os.path.join(str(data_root), p) if p else None

    # SP3 node-posing: the officer model is now POSED at assembly time. We pass
    # the placement NIF into assemble_officer, which bakes the clip's rest-frame
    # pose into the model's node-local transforms and clears the skeleton so the
    # model renders as a STATIC posed model through the bridge node-walk. No bone
    # palette is involved anymore (sample_placement_pose / set_instance_bone_
    # palette are gone). The placement NIF path is data-root-relative.
    placement_nif_abs = os.path.join(str(data_root), placement["nif"])
    _dbg("  placement_nif=%s" % (placement_nif_abs,))

    model = host.assemble_officer(
        _abs(ap.get("body_nif")), _abs(ap.get("head_nif")),
        _abs(ap.get("body_tex")), _abs(ap.get("head_tex")),
        placement_nif_abs,
    )
    iid = host.create_bridge_instance(model)
    _dbg("  assembled model=%r instance=%r" % (model, iid))

    # From here the instance exists in the renderer; if the world-transform set
    # raises, destroy the orphaned instance before propagating so place_officers
    # skips this officer without leaking a tracked-nowhere render instance.
    try:
        host.set_world_transform(iid, _BRIDGE_IDENTITY_MAT4)
        _dbg("  -> PLACED instance=%r" % (iid,))
    except Exception:
        try:
            host.destroy_instance(iid)
        except Exception:
            pass
        raise
    return iid
