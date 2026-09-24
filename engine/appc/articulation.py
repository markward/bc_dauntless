"""Per-ship PART ARTICULATION — named NIF part nodes rotated about an authored hinge.

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

WHY THE PIVOT MUST BE AUTHORED. Every part node in BirdOfPrey.nif carries the
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

FOUR STATES, NOT A DEFLECTION. Each part authors one angle per state —
"cruise", "yellow", "red", "warp" (`articulated_part.STATES`). There is no
0..1 deflection scalar anywhere: four independent authored poses cannot be
expressed as one scalar times a maximum, and `ShipClass.Get/SetArticulation
Deflection` no longer exist. Per sim tick `tick_ship` eases each part's
CURRENT angle toward `target_angle(part, state_for(ship))` and stores it in
`ship._articulation_angles` ({part name: degrees}) — the single source every
reader of a live pose consults, via `angle_for_part`.

`state_for` is deliberately ASYMMETRIC: the player keys off alert level, an
NPC off whether it has a target. BC never takes an NPC off Red Alert (measured
on the real exe), so its alert level carries no signal. Warp outranks both.

FRAME AND MATH. `pivot` and `axis` are in the part node's PARENT space. Scene
Root is identity in every BC ship NIF, so that is just model space — raw NIF
units, before the instance's natural scale. A part's `pivot` is AUTHORED and
STORED in SHIP units (model / 100), matching the derived per-part boxes
(`part_boxes_for`) and subsystem mounts; it is converted to the raw-model
frame at exactly one place, the C++ call site
`host_loop._sync_ship_articulation`, via `MODEL_TO_SHIP` below. `axis` is a
direction, not a point, so it is unit-agnostic and needs no conversion. The
override replaces the node's own local transform::

    local' = T(pivot) . R(axis, theta) . T(-pivot) . local

with `theta = radians(the part's current angle)`. At angle 0 the override is
identity, so the emitted map is EMPTY and the render is byte-identical to an
unarticulated ship. Angle 0 is the pose the NIF ships in; for the Bird of Prey
that is also the authored "red" angle, which is why combat rendering is
unchanged. That is BoP-specific authoring, NOT a rule of this module: another
hull may author a non-zero red.

THE SAME HINGE, IN THREE PLACES, and they must agree or the ship lies:

  * the DRAWN mesh — `host_loop._sync_ship_articulation` pushes pivot/axis/
    theta to `set_instance_node_rotation`;
  * a MOUNT that must follow its part (beam origins, SPV pins) —
    `part_transform_point` / `point_at_angle`, the same Rodrigues rotation;
  * a QUERY against a REST-baked structure (the derived per-part boxes) —
    `part_severance.part_for_live_point` inverse-rotates the QUERY instead,
    because the boxes cannot move.

TUNING NOTE: the hinge axis IS the Y axis, so a pivot's Y COMPONENT HAS NO
EFFECT — rotating about a line through the pivot is unchanged by sliding the
pivot along that line. Only X and Z are live. Two numbers per wing.
"""

from __future__ import annotations

import math
from typing import NamedTuple


class Part(NamedTuple):
    """A bare (pivot, axis) carrier — NOT a live rig shape.

    RETIRED as rig data: `rig_for`/`parts_for_leaf` return
    `articulated_part.ArticulatedPartProperty` instances, which is all any
    production path ever sees. The ONLY thing that still builds one of these
    is `rotation_for`'s axis-normalisation / degenerate-axis pair in
    `tests/unit/test_articulation.py`, which needs a `.pivot` and an `.axis`
    and nothing else. Kept for exactly that, and load-bearing only there —
    do not reach for it when adding a part.

    The `.angle_deg` and `.node` duck-type fallbacks in `_swing_range`,
    `_part_name` and `target_angle` exist to keep those tests off the
    exception path; they are defensive, not a live branch.

    node:      NIF node name, matched exactly (BC node names are case-stable).
    pivot:     hinge point, parent/model space, SHIP units (model NIF units
               / 100). Shared units with the derived per-part boxes and
               subsystem mounts on purpose: Task 1 of the hardpoint-parenting
               plan unified them after a MODEL-vs-SHIP mix-up made part
               attribution silently never fire. Converted to model units at
               the ONE C++ call site (host_loop._sync_ship_articulation).
    axis:      hinge axis, parent/model space; normalised on use.
    angle_deg: a single rotation, the pre-four-state shape. Real parts carry
               one angle per state instead.
    """

    node: str
    pivot: tuple[float, float, float]
    axis: tuple[float, float, float]
    angle_deg: float


# Seconds for a part to traverse its FULL authored range (see `_part_range`).
# A BoP wing transition reads as a couple of seconds on screen; faster looks
# like a glitch, slower reads as broken.
TRAVEL_SECONDS = 2.0

# Multiply a MODEL (raw NIF) unit by this to reach a SHIP (hardpoint-authored)
# unit -- = BC_MODEL_SCALE. The one call site that needs the OPPOSITE
# direction, host_loop._sync_ship_articulation, therefore DIVIDES a ship-units
# pivot by this constant to reach model units for the C++ node-rotation call.
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


def rotation_for(part, angle_deg: float) -> tuple[
        tuple[float, float, float], tuple[float, float, float], float]:
    """Return (pivot, unit_axis, theta_radians) for `part` at `angle_deg`.

    Takes DEGREES, not a 0..1 deflection. Four independent per-state angles
    (cruise/yellow/red/warp) cannot be expressed as one scalar times an
    authored maximum -- see `articulated_part.ArticulatedPartProperty`.

    Kept separate from the matrix build so the C++ binding takes the same three
    values the SPV gizmo would eventually author, rather than a baked matrix.
    """
    ax, ay, az = part.axis
    n = math.sqrt(ax * ax + ay * ay + az * az)
    if n <= 0.0:
        unit = (0.0, 1.0, 0.0)
    else:
        unit = (ax / n, ay / n, az / n)
    theta = math.radians(float(angle_deg))
    return part.pivot, unit, theta


# ── Four-state model (Task 4) ────────────────────────────────────────────────
#
# Replaces the single 0..1 deflection with a CURRENT ANGLE per part, eased
# toward the authored angle of one of `articulated_part.STATES` ("cruise",
# "yellow", "red", "warp"). A scalar deflection cannot express four
# independent authored poses; a per-part current angle can, and needs no
# captured start/end pair -- an interrupted transition just gets a new
# target and keeps easing from wherever it already is.

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


def ease_angle(current: float, target: float, *, part_range: float,
               dt: float) -> float:
    """Move `current` toward `target` at `part_range / TRAVEL_SECONDS` per
    second, clamped so it never overshoots.

    Rate is proportional to the part's OWN range: a full swing always takes
    TRAVEL_SECONDS, and a smaller move is proportionally faster. Two parts
    with EQUAL ranges therefore stay in sync however far between states they
    move -- the real Bird of Prey case, since the wing pair is authored
    mirrored (+45 / -45, equal magnitude). Two parts with DIFFERENT ranges do
    NOT generally arrive together: e.g. a part authored cruise 0 / red 40 /
    warp 90 (range 90) and one authored cruise 0 / red 40 / warp 40 (range
    40) both swing 40 degrees on cruise->red, but the first finishes at
    0.44 * TRAVEL_SECONDS and the second at 1.0 * TRAVEL_SECONDS -- visibly
    desynchronised, driven by a WARP angle neither part is moving to. A
    future ship whose parts need true cross-part sync regardless of range is
    a known, deliberate re-open, not something this function claims to
    solve; see `_part_range`. Interrupting a transition needs no special
    case: the target changes and the part keeps easing from wherever it is.
    """
    if part_range <= 0.0 or TRAVEL_SECONDS <= 0.0:
        return target
    step = abs(part_range) * (float(dt) / TRAVEL_SECONDS)
    delta = target - current
    if abs(delta) <= step:
        return target
    return current + (step if delta > 0 else -step)


def _part_range(part) -> float:
    """Peak-to-peak spread of `part`'s authored angle across every state.

    A single per-part constant rather than a per-transition one. NOT cached
    here: `ArticulatedPartProperty.angle_range` (a property on the part
    itself) already caches this and -- the reason it lives there rather
    than in a `functools.lru_cache` keyed on the part -- invalidates
    correctly the instant `SetStateAngle` re-authors an angle, and is
    released exactly when the part itself is (mission swap /
    `articulated_part.reset()` dropping the snapshot's last reference)
    rather than being pinned alive forever by a free function's cache. A
    part without that property (a bare test double) just gets recomputed on
    every call, which is fine: nothing but a test ever takes this path.
    This gives `ease_angle` a rate that is fixed per part rather than
    recomputed per transition -- see that function's docstring for exactly
    what guarantee that does, and does not, deliver.
    """
    cached = getattr(part, "angle_range", None)
    if cached is not None:
        return cached
    from engine.appc.articulated_part import STATES
    values = [part.angle_for(state) for state in STATES]
    return max(values) - min(values)


def _swing_range(part) -> float:
    """`ease_angle`'s `part_range` for `part`.

    Every part `rig_for`/`parts_for_leaf` can return since Task 5's migration
    is an `ArticulatedPartProperty`, so this is `_part_range` (peak-to-peak
    across all four states, cached and invalidated on the part itself). The
    `angle_deg` fallback for this module's OLD hardcoded `Part` (retired from
    `rig_for`'s output, but still constructed directly by a couple of
    `rotation_for`-only unit tests) is kept as a defensive duck-type guard,
    not a live path."""
    if callable(getattr(part, "angle_for", None)):
        return _part_range(part)
    return abs(part.angle_deg)


def _part_name(part) -> str:
    """Name to key `part` by in `ship._articulation_angles`.

    `.GetName()` is what every real `ArticulatedPartProperty` (the only
    shape `rig_for` returns since Task 5) answers. The `.node` fallback for
    this module's OLD hardcoded `Part` is kept as a defensive duck-type
    guard, not a live path -- see `_swing_range`."""
    getter = getattr(part, "GetName", None)
    return getter() if callable(getter) else part.node


def target_angle(part, state: str) -> float:
    """Degrees `part` should swing to at `state`.

    Public because two callers need it: `tick_ship` (the eased sim target)
    and `host_loop._sync_spv_articulation` (the SPV's FORCED pose, which is
    that same authored angle applied instantly, with no easing and no sim
    tick -- the SPV runs with the sim frozen).

    Every part `rig_for` can return since Task 5's migration carries one
    authored angle per state via `.angle_for`. The `.angle_deg` binary-swing
    fallback (RED = the model's rest pose, everything else = fully
    deflected) is this module's retired OLD-rig `Part` shape, kept as a
    defensive duck-type guard -- see `_swing_range`."""
    angle_for = getattr(part, "angle_for", None)
    if callable(angle_for):
        return angle_for(state)
    return 0.0 if state == "red" else part.angle_deg


def angle_for_part(ship, part) -> float:
    """`ship`'s current eased angle (degrees) for `part`.

    The ONLY source is `ship._articulation_angles` ({name: degrees}),
    written by `tick_ship` every sim tick -- this is what every reader of a
    ship's LIVE pose (`host_loop._sync_ship_articulation`,
    `part_severance.part_for_live_point`, `part_transform_point` below)
    consults. A ship with no entry for `part` (never ticked, or ticked but
    still at its starting angle before any state changed it) reads 0.0 --
    the NIF pose -- which is the honest answer, not a scalar nothing in
    production writes any more (`GetArticulationDeflection`/
    `SetArticulationDeflection` are gone from `ShipClass`; there is no
    fallback to fall back to).
    """
    angles = getattr(ship, "_articulation_angles", None)
    if not angles:
        return 0.0
    return angles.get(_part_name(part), 0.0)


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
    """SNAP every rigged part of `ship` to `state` NOW, with no easing.

    `state` is None for the ANCHOR pose (every part at angle 0 -- the pose the
    NIF ships in, and the frame a hardpoint mount is STORED in), or a name
    from `articulated_part.STATES` for that state's authored angles.

    WHY THIS EXISTS, AND WHY IT IS AN EVENT-EDGE CALL. `ship.
    _articulation_angles` is the ONE source every reader of a live pose
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
    mutation on the sim side. The render sweep then reads live angles like
    everything else, and mesh and mounts agree by construction rather than by
    two code paths being kept in step.

    NOT for the per-frame render path: `_sync_ship_articulation` is documented
    read-only on game state, and that rule exists because a game-state
    mutation in the render path once gave the player's phasers half a second
    aiming at a destroyed subsystem.

    Harmless when the sim is NOT frozen: this only seeds the angles, and the
    next `tick_ship` eases on from wherever they are -- toward the same
    `state` while `_dev_override` names it, and back toward `state_for(ship)`
    once it is released (which is what makes the wings ease home when the
    viewer closes, rather than snapping).

    A ship with no rig, or one that rejects the attribute (a prop, a test
    double), is left alone.
    """
    parts = parts_for_ship(ship)
    if not parts:
        return
    angles = {_part_name(p): (0.0 if state is None else target_angle(p, state))
              for p in parts}
    try:
        ship._articulation_angles = angles
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
    """Advance one ship's PER-PART articulation angles by `dt` (Task 4's
    4-state model), easing each part toward its target angle at
    `state_for(ship)` (or the dev override state).

    Parts come from the per-state template snapshot
    (`articulated_part.parts_for_leaf`, reached here via `rig_for`) when one
    is registered for `leaf` -- the only rig data any ship carries since
    Task 5 retired the hardcoded dict. The result lands in
    `ship._articulation_angles` ({name: degrees}), which is what every
    reader of a ship's LIVE pose now consults; nothing writes
    `ship.SetArticulationDeflection` any more.

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
    angles = getattr(ship, "_articulation_angles", None)
    if angles is None:
        angles = {}
        try:
            ship._articulation_angles = angles
        except Exception:  # noqa: BLE001 - test double / prop may reject
            return
    for part in parts:
        name = _part_name(part)
        current = angles.get(name, 0.0)
        target = target_angle(part, state)
        if current != target:
            angles[name] = ease_angle(current, target,
                                      part_range=_swing_range(part), dt=dt)


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
    derived per-part boxes use). Identity for a ship with no rig, for a point on no
    articulated part, and at angle 0 -- so an unarticulated hull is
    byte-identical to not calling this.

    This is what makes a hardpoint FOLLOW its part. A BoP's wingtip cannon
    sits at (1.008, 0.450, -0.670); with the wings up that mount is ~0.9 ship
    units (~150 m) from where the gun is drawn, and the beam fires from the
    stale point.

    Reads the part's CURRENT angle via `angle_for_part` (Task 4) rather than
    a ship-wide deflection: a per-part angle is what the state machine
    actually produces, and different parts on the same ship can be mid-ease
    at different angles at once.

    `part` is the part NAME when the caller already knows it -- `hull_bounds`
    does: every cached piece carries its tag, decided once at cache time.
    Passing it skips `part_for_point`, which would otherwise re-derive that
    same answer with a full sorted distance scan over every box on the hull,
    per piece, per sweep, per frame. Omit it and attribution runs as before.
    """
    parts = rig_for(leaf_for(ship))
    if not parts:
        return point

    from engine.appc.part_severance import part_for_point, is_detached
    name = part if part is not None else part_for_point(leaf_for(ship), point)
    if name is None:
        return point
    if is_detached(ship, name):
        # A severed part has no hinge left to follow -- rotating a mount
        # about a phantom wing would drag it along with a wing that is no
        # longer there. See host_loop._sync_ship_articulation for the
        # render-side twin of this guard.
        return point
    part = next((p for p in parts if p.GetName() == name), None)
    if part is None:
        return point

    angle_deg = angle_for_part(ship, part)
    if angle_deg == 0.0:
        return point
    return point_at_angle(part, point, angle_deg)


def point_at_angle(part, point, angle_deg):
    """Where `point` (body frame, ship units) ends up when `part` alone sits
    at `angle_deg` degrees about its hinge.

    The ship-free, angle-based twin of `part_transform_point`: no
    attribution, no severance check, no read of any ship state. Used by the
    LIVE-pose readers (`part_transform_point`,
    `part_severance.part_for_live_point`), which already have a concrete
    current angle in hand (from `angle_for_part`), and by `hull_bounds`'s
    travel-reach maths, which evaluates it at each state's own authored
    angle rather than at a ship's live pose.
    """
    pivot, axis, theta = rotation_for(part, angle_deg)
    return _rotate_about(point, pivot, axis, theta)


def vector_at_angle(part, vec, angle_deg):
    """Where a body-frame DIRECTION points when `part` sits at `angle_deg`:
    the hinge's rotation without its translation. `point_at_angle` is for
    positions; a spot light's direction and up are directions."""
    _pivot, axis, theta = rotation_for(part, angle_deg)
    return _rotate_about(vec, (0.0, 0.0, 0.0), axis, theta)


def _rotate_about(point, pivot, axis, theta):
    """Rodrigues rotation of `point` about the line (pivot, unit axis) by
    `theta` radians. Right-handed, matching the renderer's column-vector
    convention (CLAUDE.md) and glm::rotate in set_instance_node_rotation, so
    the mount and the drawn mesh agree by construction."""
    if theta == 0.0:
        return point
    vx = point[0] - pivot[0]
    vy = point[1] - pivot[1]
    vz = point[2] - pivot[2]
    ax, ay, az = axis
    c = math.cos(theta)
    s = math.sin(theta)
    dot = ax * vx + ay * vy + az * vz
    cx = ay * vz - az * vy
    cy = az * vx - ax * vz
    cz = ax * vy - ay * vx
    return (pivot[0] + vx * c + cx * s + ax * dot * (1.0 - c),
            pivot[1] + vy * c + cy * s + ay * dot * (1.0 - c),
            pivot[2] + vz * c + cz * s + az * dot * (1.0 - c))
