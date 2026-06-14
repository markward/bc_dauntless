"""SP3: place populated bridge officers at their stations (posed + appearance).

Ties together the SP3 building blocks: for each populated bridge-crew
CharacterClass, resolve its station placement clip, assemble its
per-character body+head model, create a bridge render instance, sample the
placement clip's rest-frame pose into a skinning palette, and pin the
instance into bridge-set space.

The placement clip's root track carries the station offset (the officer's
position on the bridge); it rides through the bone palette. So the officer's
world transform is the bridge set's own space — identity here, since the
bridge geometry is rendered at world identity (host_loop._ensure_bridge_for_
session / the bridge pass camera both work in bridge-local frame). The exact
Z-up / X-flip parity with the bridge mesh is a live-tuning concern (see the
SP3 plan's "coordinate alignment" note); identity is the simplest starting
point and lets the palette's root bone do the placement.

`host` is the _dauntless_host bindings module (or a fake in tests) exposing:
  resolve_placement(location)        -> {"nif": str(rel), "hidden": bool} | None
  assemble_officer(b_nif, h_nif, b_tex, h_tex) -> ModelHandle
  create_bridge_instance(model)      -> InstanceId
  sample_placement_pose(model, nif)  -> list[list[float]]  (column-major mat4s)
  set_instance_bone_palette(iid, palette)
  set_world_transform(iid, mat4)
  destroy_instance(iid)              (used to clean up on mid-placement failure)

`data_root` is the absolute game data root (e.g. ".../game"); the placement
NIF path from resolve_placement is data-root-relative and is joined here the
same way host_loop joins bridge/ship NIF paths.
"""
import logging
import os

_logger = logging.getLogger(__name__)

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
    loc = off.GetLocation()
    # GetLocation() returns "" before ConfigureCharacters runs, or a Location
    # object in some SDK forms. Only station-name strings are placeable.
    if not loc or not isinstance(loc, str):
        return None
    placement = host.resolve_placement(loc)
    if not placement or placement.get("hidden"):
        return None

    ap = off.appearance()
    if not ap.get("body_nif"):
        return None

    model = host.assemble_officer(
        ap.get("body_nif"), ap.get("head_nif"),
        ap.get("body_tex") or None, ap.get("head_tex") or None,
    )
    iid = host.create_bridge_instance(model)

    # From here the instance exists in the renderer; if any post-create step
    # raises, destroy the orphaned instance before propagating so place_officers
    # skips this officer without leaking a tracked-nowhere render instance.
    try:
        nif_abs = os.path.join(str(data_root), placement["nif"])
        palette = host.sample_placement_pose(model, nif_abs)
        if palette:
            host.set_instance_bone_palette(iid, palette)
        host.set_world_transform(iid, _BRIDGE_IDENTITY_MAT4)
    except Exception:
        try:
            host.destroy_instance(iid)
        except Exception:
            pass
        raise
    return iid
