"""SP3/SP2: place populated bridge officers at their stations (posed + appearance).

Ties together the building blocks: for each populated bridge-crew
CharacterClass, resolve its station placement clip, assemble its
per-character body+head model, create a bridge render instance, pin the
instance into bridge-set space, and start its placement animation.

SP2 — GPU bone-palette skinning, not node posing. The officer keeps its
skeleton; assemble_officer loads the placement clip into the composed model's
animations[0]. We then call set_instance_animation(iid, 0, loop=False, ...) so
the renderer plays that clip once and holds the last frame (a stand clip
settles into the standing pose; a movement clip walks the officer to the
station and holds). The renderer poses the body each frame through the GPU bone
palette (world_pose * inverse_bind), which deforms both the rigid and the
skinned shapes of a BC body uniformly. The placement clip's root track carries
the station offset, so the instance's own world transform is the bridge set's
identity space here (the bridge geometry renders at world identity). The exact
Z-up / X-flip parity and root offset are a live-tuning concern; identity is the
simplest starting point.

`host` is the _dauntless_host bindings module (or a fake in tests) exposing:
  resolve_placement(location)        -> {"nif": str(rel), "hidden": bool} | None
  assemble_officer(b_nif, h_nif, b_tex, h_tex, placement_nif) -> ModelHandle
  create_bridge_instance(model)      -> InstanceId
  set_world_transform(iid, mat4)
  set_instance_animation(iid, clip_index, loop, sample_at_start)
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
# itself sits at the bridge origin — EXCEPT for the determinant-normalization
# X-flip every rendered instance needs.
#
# The renderer runs glFrontFace(GL_CW) and assumes every world matrix has
# det < 0 (see host_loop._ship_world_matrix). BC character NIFs are authored
# in a left-handed model frame (left hand at +X), so an officer placed at plain
# identity (det = +1) would render inside-out AND mirrored. Negating the X basis
# axis (row-major col 0) mirrors the body into the renderer's right-handed world
# the same way ships are flipped, giving det < 0 and the correct station pose
# (e.g. db_stand_t_l L-Hand at world ≈ (-21, -107, 23) instead of the mirrored
# +X). Row-major; set_world_transform transposes on input.
_BRIDGE_IDENTITY_MAT4 = [
    -1.0, 0.0, 0.0, 0.0,
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
    try:
        _name = off.GetCharacterName()
    except Exception:
        _name = "?"
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

    # The appearance paths from the SDK config are data-root-relative
    # (e.g. "data/Models/Characters/Bodies/BodyMaleL/BodyMaleL.nif"); the host
    # opens files relative to CWD, so join them to the game data root the same
    # way the placement NIF is resolved.
    def _abs(p):
        return os.path.join(str(data_root), p) if p else None

    # SP2: assemble_officer keeps the skeleton and loads the placement clip into
    # the composed model's animations[0]. We pass the placement NIF so it can
    # load that clip; the per-instance playback is started below via
    # set_instance_animation, and the renderer poses the body through the GPU
    # bone palette each frame. The placement NIF path is data-root-relative.
    placement_nif_abs = os.path.join(str(data_root), placement["nif"])

    # Movement clips (Science/Engineer "to L1") have the officer AT the station
    # at t=0; sample_at_start (forwarded to set_instance_animation) selects that.
    model = host.assemble_officer(
        _abs(ap.get("body_nif")), _abs(ap.get("head_nif")),
        _abs(ap.get("body_tex")), _abs(ap.get("head_tex")),
        placement_nif_abs,
        bool(placement.get("sample_at_start")),
    )
    iid = host.create_bridge_instance(model)

    # From here the instance exists in the renderer; if the world-transform set
    # raises, destroy the orphaned instance before propagating so place_officers
    # skips this officer without leaking a tracked-nowhere render instance.
    try:
        host.set_world_transform(iid, _BRIDGE_IDENTITY_MAT4)
        # SP2: play the placement clip once and hold (clip is animations[0] of
        # the assembled model). sample_at_start = the placement's movement flag.
        host.set_instance_animation(
            iid, 0, False, bool(placement.get("sample_at_start")))
    except Exception:
        try:
            host.destroy_instance(iid)
        except Exception:
            pass
        raise
    return iid
