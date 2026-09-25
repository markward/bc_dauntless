"""Per-ship PART ARTICULATION — named NIF part nodes moved through authored poses.

SPIKE (2026-09-23), visual-only. BC never did this: `BirdOfPrey.py` is a plain
LOD load, its hardpoint file is stock subsystems, and the wing nodes carry
`Controller: None` — there is no keyframe data anywhere in the asset. Every
number here is a DESIGN CHOICE, not a recovered BC value.

What the NIF does give us is a clean part split. BC ship models are three
levels deep and uniform across the fleet::

    Scene Root                (NiNode)
    +-- left wing             (NiNode)   <-- a PART: the only thing we rotate
    |   +-- __NDL_MultiMtl_Node (NiNode) <-- 3ds Max exporter marker
    |       +-- left wing:3   (NiTriShape)  <-- geometry, NOT a Model::Node
    |       +-- left wing:4   (NiTriShape)

Only `NiNode` blocks become `assets::Model::Node` (model_build.cc `walk()`
early-returns on anything else), so the `:N` geometry leaves never appear in
the node array at all. A part is therefore "a named child of Scene Root that
is not `__NDL_MultiMtl_Node`" — which is what makes addressing one by name
safe.

WHY THE POSE AND ANCHOR MUST BE AUTHORED. Every part node in BirdOfPrey.nif carries the
IDENTICAL local translation (0, -56.3314, -6.3288) — the shared 3ds Max scene
origin, not a hinge. Rotating a wing node in place would swing it about a
point common to the whole ship. The NIF cannot tell us where the hinge is, and
it cannot tell us that `left wing01` is the STARBOARD wing (that name is a Max
clone suffix, not anatomy — its geometry spans X +12.4..+102.6). Both facts
have to be AUTHORED, which is what the SPV's Model Parts pane is for.

WHERE THE DATA LIVES — IN THE HARDPOINT FILE, NOT HERE. This module owns no
rig data at all. A ship's parts are `ArticulatedPartProperty` templates
registered by its own hardpoint file — for stock hulls, a `__parts__` block in
the machine-owned `engine/appc/hardpoint_overrides.py`, which the SPV
regenerates on save — and snapshotted per hardpoint leaf by
`articulated_part.parts_for_leaf`. `rig_for` below is a thin case-insensitive,
None-safe wrapper over that lookup. (The hand-authored `_RIGS` dict this
module used to carry, and the docstring that explained why it lived here
rather than in `hardpoint_overrides.py`, are both gone — the arrangement is
now exactly the inverse.)

FOUR STATES, EACH A FULL POSE. Each part authors one rigid POSE per state --
"cruise", "yellow", "red", "warp" (`articulated_part.STATES`) -- a rotation R
and a translation t (`part_pose`, spec 2026-09-25). There is no 0..1
deflection scalar anywhere. Per sim tick `tick_ship` advances each part's
TRANSITION toward `target_pose(part, state_for(ship))` and stores the result in
`ship._articulation_poses` ({part name: (R, t)}) -- the single source every
reader of a live pose consults, via `pose_for_part`.

`state_for` is deliberately ASYMMETRIC: the player keys off alert level, an
NPC off whether it has a target. BC never takes an NPC off Red Alert (measured
on the real exe), so its alert level carries no signal. Warp outranks both.

FRAME AND MATH. A pose is in the part node's PARENT space. Scene Root is
identity in every BC ship NIF, so that is just model space. Poses and the
part's `anchor` are AUTHORED and STORED in SHIP units (model / 100), matching
the derived per-part boxes (`part_boxes_for`) and subsystem mounts; the
translation is converted to the raw-model frame at exactly one place, the C++
call site `host_loop._sync_ship_articulation`, via
`part_pose.matrix4_model(pose, MODEL_TO_SHIP)`. A rotation is unit-agnostic.
The override replaces the node's own local transform::

    local' = M(pose) . local

where M draws a body point x at R.x + t. The identity pose is the pose the
NIF ships in; its matrix is identity, so the native override map stays EMPTY
and the render is byte-identical to an unarticulated ship. For the Bird of
Prey "red" is unset (identity), which is why combat rendering is unchanged.
That is BoP-specific authoring, NOT a rule of this module: another hull may
author a non-identity red.

A TRANSITION (spec §4.1) runs over the part's `transition_seconds`: the part
rotates (slerp) about its `anchor` while the anchor travels straight between
its start and end positions (`part_pose.interpolate`) -- a swing, not a
slide. A state change mid-transition starts a new transition from the
CURRENT pose, so a part never snaps back. For a legacy hinge (anchor on the
axis) this is exactly the old linear angle ease.

THE SAME POSE, IN THREE PLACES, and they must agree or the ship lies:

  * the DRAWN mesh -- `host_loop._sync_ship_articulation` pushes the pose's
    matrix to `set_instance_node_transform`;
  * a MOUNT that must follow its part (beam origins, SPV pins, lights) --
    `part_transform_point` / `part_transform_vector`, the same R.x + t;
  * a QUERY against a REST-baked structure (the derived per-part boxes) --
    `part_severance.part_for_live_point` applies the INVERSE pose to the
    QUERY instead, because the boxes cannot move.
"""

from __future__ import annotations

import math

from engine.appc import part_pose


# Multiply a MODEL (raw NIF) unit by this to reach a SHIP (hardpoint-authored)
# unit -- = BC_MODEL_SCALE. The one call site that needs the OPPOSITE
# direction, host_loop._sync_ship_articulation, therefore DIVIDES a ship-units
# pose translation by this constant (inside `part_pose.matrix4_model`) to reach
# model units for the C++ node-transform call.
MODEL_TO_SHIP = 0.01


# Keyed by HARDPOINT LEAF (the `HardpointFile` value in the ship's
# GetShipStats), matching `hardpoint_overrides.apply(leaf)`. See
# `articulated_part`'s docstring for why the per-leaf result is a SNAPSHOT
# rather than a live query, and this module's for where rig data lives now.
def rig_for(leaf: str | None) -> tuple:
    """Return the articulation parts for a hardpoint leaf, or () if none."""
    if not leaf:
        return ()
    from engine.appc.articulated_part import parts_for_leaf as _parts_for_leaf
    return _parts_for_leaf(str(leaf).lower())


# Same lookup under the name Task 3/4 already call it by
# (`articulated_part.parts_for_leaf`), so either name reaches the identical
# per-leaf snapshot.
parts_for_leaf = rig_for


def _is_player(ship) -> bool:
    """True when `ship` is the current player. Best-effort: False headlessly,
    during teardown, or whenever the game is not resolvable."""
    try:
        import App
        game = (App.Game_GetCurrentGame()
                if hasattr(App, "Game_GetCurrentGame") else None)
        player = (game.GetPlayer()
                  if game is not None and hasattr(game, "GetPlayer") else None)
    except Exception:  # noqa: BLE001 - this runs per rigged ship per tick
        return False
    return player is not None and player is ship


# ── Four-state model ─────────────────────────────────────────────────────────
#
# A CURRENT POSE per part, carried toward the authored pose of one of
# `articulated_part.STATES` ("cruise", "yellow", "red", "warp") by a
# transition (spec 2026-09-25 §4.1). An interrupted transition starts a new
# one from wherever the part already is.

def _is_warping(ship) -> bool:
    """Whether `ship` is at warp. Best-effort: a prop or test double that
    cannot answer is not warping.

    Uses `warp_state.is_ship_warping`, BC's own canonical test
    (`GetWarpEngineSubsystem().GetWarpState() != WES_NOT_WARPING`) -- not a
    `warp.is_at_warp` (no such name exists in `engine.appc.warp`; that was
    the brief's assumption, wrong against this tree). `is_ship_warping` is
    already isinstance(ShipClass)-guarded, so a Planet or other non-ship
    reads as not-warping rather than truthy-stubbing its way to True.
    """
    from engine.appc import warp_state
    try:
        return bool(warp_state.is_ship_warping(ship))
    except Exception:  # noqa: BLE001 - this runs per rigged ship per tick
        return False


def state_for(ship) -> str:
    """Which articulation state `ship` is in.

    Warp outranks alert level: wing position is a FLIGHT configuration, so
    warp entry visibly re-configures the ship. A ship running under fire is
    still in its travel shape.

    NPCs key off "has a target" rather than alert level, and therefore never
    show "yellow" -- BC never takes an NPC off Red Alert, so its alert level
    carries no signal. Measured, not assumed (stbc-oracle bible s13 N2).
    """
    if _is_warping(ship):
        return "warp"
    if _is_player(ship):
        import App
        level = ship.GetAlertLevel()
        if level == App.ShipClass.RED_ALERT:
            return "red"
        if level == App.ShipClass.YELLOW_ALERT:
            return "yellow"
        return "cruise"
    getter = getattr(ship, "GetTarget", None)
    if getter is None:
        return "cruise"
    try:
        return "red" if getter() else "cruise"
    except Exception:  # noqa: BLE001
        return "cruise"


def _part_name(part) -> str:
    """Name to key `part` by in `ship._articulation_poses`: the NIF node
    name, which is the template name (`ArticulatedPartProperty.GetName`)."""
    return part.GetName()


def target_pose(part, state: str):
    """The pose `part` should reach at `state` -- `part.pose_for(state)`, the
    NIF pose (identity) for a state its author left unset.

    Public because two callers need it: `tick_ship` (the transition target)
    and `force_pose` (the SPV's FORCED pose, that same authored pose applied
    instantly -- the SPV runs with the sim frozen)."""
    return part.pose_for(state)


def pose_for_part(ship, part):
    """`ship`'s current pose (R, t) for `part`, SHIP units.

    The ONLY source is `ship._articulation_poses` ({name: pose}), written by
    `tick_ship` every sim tick (and snapped by `force_pose` /
    `force_part_pose`) -- this is what every reader of a ship's LIVE pose
    (`host_loop._sync_ship_articulation`, `part_severance.part_for_live_point`,
    `part_transform_point` below) consults. A ship with no entry for `part`
    (never ticked, or still in the NIF pose) reads IDENTITY -- the NIF pose.
    """
    poses = getattr(ship, "_articulation_poses", None)
    if not poses:
        return part_pose.IDENTITY
    return poses.get(_part_name(part), part_pose.IDENTITY)


def _poses_equal(a, b, eps=1e-9) -> bool:
    """Element compare of two poses within `eps`."""
    (Ra, ta), (Rb, tb) = a, b
    return (all(abs(Ra[i][j] - Rb[i][j]) <= eps
                for i in range(3) for j in range(3))
            and all(abs(ta[i] - tb[i]) <= eps for i in range(3)))


# ── Dev override ─────────────────────────────────────────────────────────────
# A forced STATE that outranks the alert/target-driven target, so the poses
# can be judged at a frozen state instead of only in passing. None = follow
# state_for. Dev-only by construction: the only caller is a dev keybinding,
# which `dev_mode` never registers outside --developer.
_dev_override: "str | None" = None


def set_dev_override(state: "str | None") -> None:
    """Force every rigged ship to `state` (one of `articulated_part.STATES`),
    or None to release back to `state_for`."""
    from engine.appc.articulated_part import STATES
    global _dev_override
    if state is not None and state not in STATES:
        raise ValueError(
            "unknown articulation state %r; expected one of %r"
            % (state, STATES))
    _dev_override = state


def dev_override() -> "str | None":
    return _dev_override


def force_pose(ship, state: "str | None") -> None:
    """SNAP every rigged part of `ship` to `state` NOW, with no transition.

    `state` is None for the NIF pose (every part at IDENTITY -- the pose the
    NIF ships in, and the frame a hardpoint mount is STORED in), or a name
    from `articulated_part.STATES` for that state's authored poses. Any
    in-flight transition is dropped.

    WHY THIS EXISTS, AND WHY IT IS AN EVENT-EDGE CALL. `ship.
    _articulation_poses` is the ONE source every reader of a live pose
    consults -- the render sweep (`host_loop._sync_ship_articulation`), every
    mount (`subsystems.subsystem_world_position` via `part_transform_point`),
    the derived-box queries (`part_severance.part_for_live_point`) and the SPV
    overlays. `tick_ship` normally owns it. But the Ship Property Viewer
    FREEZES THE SIM, so `tick_ship` never runs while it is open and the dict
    stays at whatever it held the instant the pause menu opened.

    Shipping a forced pose down the RENDER path instead is what produced the
    live bug this replaces: the hull drew its wings down at the forced anchor
    pose while every disruptor-cannon pin floated at its stale raised
    position, because only one of the two halves knew about the override.

    So the forced pose is applied HERE, to the shared dict, at the SPV's own
    event edges (panel open, Preview clicked) -- an explicit, named, dev-only
    mutation on the sim side. The render sweep then reads live poses like
    everything else, and mesh and mounts agree by construction rather than by
    two code paths being kept in step.

    NOT for the per-frame render path: `_sync_ship_articulation` is documented
    read-only on game state, and that rule exists because a game-state
    mutation in the render path once gave the player's phasers half a second
    aiming at a destroyed subsystem.

    Harmless when the sim is NOT frozen: this only seeds the poses, and the
    next `tick_ship` transitions on from wherever they are -- toward the same
    `state` while `_dev_override` names it, and back toward `state_for(ship)`
    once it is released (which is what makes the wings ease home when the
    viewer closes, rather than snapping).

    A ship with no rig, or one that rejects the attribute (a prop, a test
    double), is left alone.
    """
    parts = parts_for_ship(ship)
    if not parts:
        return
    poses = {_part_name(p): (part_pose.IDENTITY if state is None
                             else target_pose(p, state))
             for p in parts}
    _store_forced(ship, poses)


def force_part_pose(ship, part_name: str, pose) -> None:
    """SNAP ONE part of `ship` to `pose` and every other part to IDENTITY
    (the NIF pose), dropping any in-flight transition. The SPV uses it to
    preview a single part's pose in isolation; same event-edge contract as
    `force_pose`. A ship with no rig is left alone."""
    parts = parts_for_ship(ship)
    if not parts:
        return
    poses = {_part_name(p): (pose if _part_name(p) == part_name
                             else part_pose.IDENTITY)
             for p in parts}
    _store_forced(ship, poses)


def _store_forced(ship, poses) -> None:
    try:
        ship._articulation_poses = poses
        ship._articulation_transitions = {}
    except Exception:  # noqa: BLE001 - a prop / test double may reject it
        pass


def reset() -> None:
    """Drop dev state. Currently called only from the test fixture
    (tests/conftest.py) -- there is no mission-swap call site yet, so a dev
    override left set by a --developer session would otherwise survive a
    mission swap in a live run."""
    global _dev_override
    _dev_override = None


# ── Per-tick ─────────────────────────────────────────────────────────────────

def leaf_for(ship) -> str:
    """Hardpoint leaf for `ship`, resolved once and cached on the ship.

    Returns "" for a ship whose script cannot be resolved -- which also caches,
    so a ship without a rig costs one attribute read per tick rather than a
    repeated module import.
    """
    cached = getattr(ship, "_articulation_leaf", None)
    if cached is not None:
        return cached
    from engine.appc.override_routing import hardpoint_leaf_for_ship
    try:
        leaf = hardpoint_leaf_for_ship(ship) or ""
    except Exception:  # noqa: BLE001 - a bad ship script must not stall the tick
        leaf = ""
    leaf = str(leaf).lower()
    try:
        ship._articulation_leaf = leaf
    except Exception:  # noqa: BLE001 - test doubles may reject attribute set
        pass
    return leaf


def tick_ship(ship, dt: float) -> None:
    """Advance one ship's PER-PART transitions by `dt` (spec 2026-09-25
    §4.1), carrying each part toward its pose at `state_for(ship)` (or the
    dev override state).

    Per part: `target = part.pose_for(state)`. With no transition, or one
    heading to a different state, and the current pose not already equal to
    `target`, a new transition starts FROM THE CURRENT POSE (u = 0) -- so an
    interrupted transition never snaps back. `u` advances by
    `dt / duration`; the pose is `part_pose.interpolate(pose0,
    target, anchor, u)`, a swing about the part's anchor. At u >= 1 the pose
    is stored as `target` exactly and the transition is dropped. A state
    change whose target POSE equals the in-flight one (BoP cruise -> yellow)
    keeps the transition running rather than restarting it.

    Each transition's duration is `transition_seconds` scaled by the fraction
    of the part's full swing still to travel (`_transition_duration`), so a
    partial move takes proportionally less -- the old constant-rate feel,
    exactly, for a hinge.

    The result lands in `ship._articulation_poses` ({name: pose}); in-flight
    transitions in `ship._articulation_transitions` ({name: (pose0,
    target_state, u, duration)}).

    A ship with no parts is skipped before any allocation, so the
    overwhelming majority of hulls pay one leaf lookup.
    """
    leaf = leaf_for(ship)
    parts = rig_for(leaf)
    if not parts:
        return
    forced = _dev_override
    if forced is not None:
        state = forced
    else:
        try:
            state = state_for(ship)
        except Exception:  # noqa: BLE001
            return
    poses = getattr(ship, "_articulation_poses", None)
    transitions = getattr(ship, "_articulation_transitions", None)
    if poses is None or transitions is None:
        poses = {} if poses is None else poses
        transitions = {} if transitions is None else transitions
        try:
            ship._articulation_poses = poses
            ship._articulation_transitions = transitions
        except Exception:  # noqa: BLE001 - test double / prop may reject
            return
    for part in parts:
        name = _part_name(part)
        current = poses.get(name, part_pose.IDENTITY)
        target = target_pose(part, state)
        tr = transitions.get(name)
        if tr is not None and _poses_equal(target_pose(part, tr[1]), target):
            # Same destination POSE (e.g. cruise -> yellow on the BoP): keep
            # the in-flight transition, only re-label its state.
            tr = (tr[0], state, tr[2], tr[3])
        else:
            if _poses_equal(current, target):
                transitions.pop(name, None)
                continue
            tr = (current, state, 0.0, _transition_duration(part, current,
                                                            target))
        pose0, _state, u, duration = tr
        u += float(dt) / max(duration, 1e-6)
        if u >= 1.0:
            poses[name] = target
            transitions.pop(name, None)
            continue
        anchor = part.anchor or (0.0, 0.0, 0.0)
        poses[name] = part_pose.interpolate(pose0, target, anchor, u)
        transitions[name] = (pose0, state, u, duration)


def _rot_angle(R0, R1) -> float:
    """Angle (radians) of R0^T . R1."""
    tr = sum(R0[i][j] * R1[i][j] for i in range(3) for j in range(3))
    return math.acos(max(-1.0, min(1.0, (tr - 1.0) / 2.0)))


def _dist(a, b) -> float:
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


_SPREAD_EPS = 1e-9


def _anchor_of(part):
    return part.anchor or (0.0, 0.0, 0.0)


def _swing_spreads(part):
    """(largest pairwise rotation angle, largest pairwise ANCHOR travel)
    among IDENTITY and the part's authored poses -- the part's FULL swing.

    Translation is measured where the anchor lands (P.a), not by the raw t:
    the anchor is what `part_pose.interpolate` moves in a straight line, and
    t depends on where the body origin happens to sit. For a hinge with its
    anchor on the axis the anchor never moves, so the rotation alone sets
    the pace -- exactly the old constant angular rate. With no anchor (the
    origin) P.a IS t, so the two measures coincide."""
    a = _anchor_of(part)
    poses = [part_pose.IDENTITY] + [part.pose_for(s)
                                    for s in part.authored_states()]
    ends = [part_pose.apply(P, a) for P in poses]
    rot = trans = 0.0
    for i in range(len(poses)):
        for j in range(i + 1, len(poses)):
            rot = max(rot, _rot_angle(poses[i][0], poses[j][0]))
            trans = max(trans, _dist(ends[i], ends[j]))
    return rot, trans


def _transition_duration(part, current, target) -> float:
    """`transition_seconds` x the fraction of the part's full swing still to
    travel from `current` to `target`, clamped to [0, 1]: the larger of the
    rotation still to turn over the largest rotation spread, and the anchor
    travel still to go over the largest anchor-travel spread.

    `transition_seconds` is the time for a FULL swing between the part's two
    farthest poses; a partial move takes proportionally less. For a hinge
    that is exactly the retired constant-rate `ease_angle`, so an interrupted
    Bird of Prey swing (reversing at 22.5 degrees takes 1 s, not 2 s) feels
    identical to before. A spread of 0 contributes 0; if both spreads are 0
    but the poses still differ, the fraction is 1."""
    rot_spread, trans_spread = _swing_spreads(part)
    # A spread at float-noise level is a spread of 0: a hinge's anchor sits
    # on its axis and "travels" ~1e-17, and noise over noise is not a
    # fraction of anything.
    rot_spread = rot_spread if rot_spread > _SPREAD_EPS else 0.0
    trans_spread = trans_spread if trans_spread > _SPREAD_EPS else 0.0
    a = _anchor_of(part)
    f = 0.0
    if rot_spread > 0.0:
        f = max(f, _rot_angle(current[0], target[0]) / rot_spread)
    if trans_spread > 0.0:
        f = max(f, _dist(part_pose.apply(current, a),
                         part_pose.apply(target, a)) / trans_spread)
    if rot_spread <= 0.0 and trans_spread <= 0.0:
        f = 1.0
    f = max(0.0, min(1.0, f))
    return float(part.transition_seconds) * f


def parts_for_ship(ship) -> tuple:
    """Articulation parts for `ship` (ArticulatedPartProperty instances), or
    () when it has no rig."""
    return rig_for(leaf_for(ship))


# ── Part geometry and detachability (phase 2a) ───────────────────────────────
# Per-part AABBs in SHIP/BODY units (model NIF units / 100 -- BC_MODEL_SCALE is
# 0.01, so hardpoint positions and these boxes share one frame).
#
# DERIVED from the model, not authored (Task 5 of
# docs/superpowers/specs/2026-09-23-spv-part-articulation-authoring-design.md):
# `host_io.model_nodes(iid)` now exposes per-node bounds keyed by NIF node
# name, so the hand-drawn `PART_BOXES` constant this used to be is gone.
#
# Cached PER LEAF, not per instance, once any caller supplies a real render
# instance id: the boxes are a property of the MODEL, identical for every
# ship of the same hull, and several callers of the geometry this feeds
# (`part_transform_point` below, `subsystems.subsystem_world_position`,
# `part_detach_render._spawn_chunk`) have no instance id in hand at all --
# only the ship-realize path (`host_loop._cache_ship_hull_pieces`) does.
# Keying by leaf means the first ship of a class to realize a render instance
# warms the box lookup for every later mount/attribution query against any
# ship of that class, including ones with no iid to offer.
#
# NOTE the wing boxes now DERIVED from the mesh are TIGHTER than the old
# hand-drawn ones, which deliberately swallowed the body box at the wing
# roots. Attribution near a wing root that used to fall back to "unattributed"
# may now resolve to the wing -- deliberate, not a bug; see the migration
# report referenced above.
_derived_boxes: dict = {}


def part_boxes_for(leaf, iid=None):
    """Per-part AABBs (ship units) for a hardpoint leaf, derived from the
    realized model's own geometry, or {} when there is nothing to derive
    them from yet -- headless, no ship of this leaf has ever realized a
    render instance, or `iid` does not name one. That degrades attribution
    to "unattributed", the same safe answer an unboxed part has always had.

    `host_io.model_nodes` is called best-effort: `iid` may be a FAKE or
    otherwise foreign id (a test's stand-in renderer, or -- as this call
    site once shipped -- a MODEL handle mistaken for an INSTANCE id, an
    incompatible pybind type that raises TypeError rather than degrading to
    []). A malformed id must not abort the caller (`cache_hull_bound_spheres`
    at ship-realize time), which would otherwise lose ALL of a ship's pieces,
    not just their part tags.
    """
    if not leaf:
        return {}
    leaf = str(leaf).lower()
    cached = _derived_boxes.get(leaf)
    if cached is not None:
        return cached
    if iid is None:
        return {}
    from engine import host_io
    try:
        nodes = host_io.model_nodes(iid)
    except Exception:  # noqa: BLE001 - a bad iid must degrade, not raise
        return {}
    boxes = {}
    for node in nodes:
        if not node.get("candidate"):
            continue                      # e.g. __NDL_MultiMtl_Node
        boxes[node["name"]] = (tuple(node["bounds_min"]),
                               tuple(node["bounds_max"]))
    if boxes:                             # do not cache an empty derivation
        _derived_boxes[leaf] = boxes
    return boxes


def detachable_for(leaf):
    """{part name: hull fraction that shears it} for a leaf, or {}.

    Reads `detach_fraction` straight off the registered templates -- see
    `articulated_part.ArticulatedPartProperty.detach_fraction` (0.20 for
    both Bird of Prey wings; absent, never 0.0, for anything that must not
    come off, e.g. the head and the body)."""
    return {p.GetName(): p.detach_fraction
            for p in rig_for(leaf) if p.detach_fraction is not None}


def part_transform_point(ship, point, part=None):
    """Where a body-frame point ends up once its part has articulated.

    In and out are BODY frame, SHIP units (what subsystem mounts and the
    derived per-part boxes use). Identity for a ship with no rig, for a point
    on no articulated part, and at the identity pose -- so an unarticulated
    hull is byte-identical to not calling this.

    This is what makes a hardpoint FOLLOW its part. A BoP's wingtip cannon
    sits at (1.008, 0.450, -0.670); with the wings up that mount is ~0.9 ship
    units (~150 m) from where the gun is drawn, and the beam fires from the
    stale point.

    Reads the part's CURRENT pose via `pose_for_part`: different parts on the
    same ship can be mid-transition at different poses at once.

    `part` is the part NAME when the caller already knows it -- `hull_bounds`
    does: every cached piece carries its tag, decided once at cache time.
    Passing it skips `part_for_point`, which would otherwise re-derive that
    same answer with a full sorted distance scan over every box on the hull,
    per piece, per sweep, per frame. Omit it and attribution runs as before.
    """
    found = _live_part(ship, part, point)
    if found is None:
        return point
    pose = pose_for_part(ship, found)
    if part_pose.is_identity(pose):
        return point
    return part_pose.apply(pose, point)


def part_transform_vector(ship, vec, part_name):
    """Where a body-frame DIRECTION points once part `part_name` has
    articulated: the pose's rotation, no translation. Unchanged for a ship
    with no rig, an unknown part, a detached part, or the identity pose.
    `part_transform_point` is for positions; a spot light's direction and up
    are directions."""
    found = _live_part(ship, part_name, None)
    if found is None:
        return vec
    pose = pose_for_part(ship, found)
    if part_pose.is_identity(pose):
        return vec
    return part_pose.apply_vector(pose, vec)


def _live_part(ship, name, point):
    """The rigged, NOT-detached part `name` of `ship` (attributed from
    `point` when `name` is None), or None."""
    parts = rig_for(leaf_for(ship))
    if not parts:
        return None

    from engine.appc.part_severance import part_for_point, is_detached
    if name is None:
        if point is None:
            return None
        name = part_for_point(leaf_for(ship), point)
    if name is None:
        return None
    if is_detached(ship, name):
        # A severed part has no pose left to follow -- moving a mount with a
        # phantom wing would drag it along with a wing that is no longer
        # there. See host_loop._sync_ship_articulation for the render-side
        # twin of this guard.
        return None
    return next((p for p in parts if p.GetName() == name), None)
