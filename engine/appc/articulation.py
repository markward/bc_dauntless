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
have to come from here.

FRAME AND MATH. `pivot` and `axis` are in the part node's PARENT space. Scene
Root is identity in every BC ship NIF, so that is just model space — raw NIF
units, before the instance's natural scale. `Part.pivot` itself, however, is
AUTHORED and STORED in SHIP units (model / 100), matching `PART_BOXES` and
subsystem mounts; it is converted to this raw-model frame only at the one C++
call site, `host_loop._sync_ship_articulation`, via `MODEL_TO_SHIP` below.
`axis` is a direction, not a point, so it is unit-agnostic and needs no such
conversion. The override replaces the node's own local transform::

    local' = T(pivot) . R(axis, theta) . T(-pivot) . local

`theta = deflection * angle_deg`. At deflection 0 the override is identity, so
the emitted map is EMPTY and the render is byte-identical to an unarticulated
ship — which is deliberately the ARMED (red alert) pose, because that is the
pose the model ships in and the one combat runs in.

TUNING NOTE: the hinge axis IS the Y axis, so a pivot's Y COMPONENT HAS NO
EFFECT — rotating about a line through the pivot is unchanged by sliding the
pivot along that line. Only X and Z are live. Two numbers per wing.

Data lives here rather than in `hardpoint_overrides.py` because that file is
machine-owned ("the SPV regenerates this file on save") and subsystem-property
shaped. The keying matches it (hardpoint leaf name) so this can fold into the
SPV-authored file later, once the gizmo can place a hinge.
"""

from __future__ import annotations

import functools
import math
from typing import NamedTuple


class Part(NamedTuple):
    """One articulated part node on a ship.

    node:      NIF node name, matched exactly (BC node names are case-stable).
    pivot:     hinge point, parent/model space, SHIP units (model NIF units
               / 100). Shares units with PART_BOXES and subsystem mounts on
               purpose: Task 1 of the hardpoint-parenting plan unified them
               after a MODEL-vs-SHIP mix-up made part attribution silently
               never fire. Converted to model units at the ONE C++ call site
               (host_loop._sync_ship_articulation).
    axis:      hinge axis, parent/model space; normalised on use.
    angle_deg: rotation applied at deflection 1.0. Sign is per-part and
               explicit — the two wings mirror, so they carry opposite signs
               rather than sharing a magnitude and inferring a side.
    """

    node: str
    pivot: tuple[float, float, float]
    axis: tuple[float, float, float]
    angle_deg: float


# Seconds for a full 0<->1 travel. A BoP wing transition reads as a couple of
# seconds on screen; faster looks like a glitch, slower reads as broken.
TRAVEL_SECONDS = 2.0

# Multiply a MODEL (raw NIF) unit by this to reach a SHIP (hardpoint-authored)
# unit -- = BC_MODEL_SCALE. The one call site that needs the OPPOSITE
# direction, host_loop._sync_ship_articulation, therefore DIVIDES a ship-units
# pivot by this constant to reach model units for the C++ node-rotation call.
MODEL_TO_SHIP = 0.01


# Keyed by HARDPOINT LEAF (the `HardpointFile` value in the ship's
# GetShipStats), matching `hardpoint_overrides.apply(leaf)`.
#
# Bird of Prey only, deliberately: it is the one stock hull we want this on.
# The mechanism is general (the Warbird ships seven part nodes, including
# `rom wing top left`/`right`) but the DATA is a set of one.
#
# Geometry these numbers were read off (model-space AABB, NIF units):
#   left wing     X[-102.58 -12.36]  Y[-67.77 53.44]  Z[-71.25 18.62]
#   left wing01   X[  12.36 102.58]  Y[-67.77 53.44]  Z[-71.25 18.62]
#   birdofprey    X[ -31.12  31.37]  Y[-70.44 29.22]  Z[-13.31 21.25]
# Wing tip sits ~41 deg below horizontal relative to a root near (|X|=16, Z=5),
# so ~45 deg brings the wings flat -- "flatter and wider" at green/yellow.
_RIGS: dict[str, tuple[Part, ...]] = {
    "birdofprey": (
        # Angle SIGNS are load-bearing and were wrong on the first pass:
        # rotating right-handed about +Y, a POSITIVE angle lifts the PORT
        # (-X) wing and SINKS the starboard one. Verified by
        # tests/unit/test_articulation.py, which rotates the real tip
        # coordinate and asserts it rises.
        Part(node="left wing",   pivot=(-0.16, 0.0, 0.05),
             axis=(0.0, 1.0, 0.0), angle_deg=45.0),
        Part(node="left wing01", pivot=(0.16, 0.0, 0.05),
             axis=(0.0, 1.0, 0.0), angle_deg=-45.0),
    ),
}


def rig_for(leaf: str | None) -> tuple[Part, ...]:
    """Return the articulation parts for a hardpoint leaf, or () if none."""
    if not leaf:
        return ()
    return _RIGS.get(str(leaf).lower(), ())


def has_rig(leaf: str | None) -> bool:
    """True when this hardpoint leaf has an articulation rig."""
    return bool(rig_for(leaf))


def deflection_target(alert_level: int) -> float:
    """Wing deflection wanted at `alert_level`.

    0.0 = the model's authored rest pose = wings DOWN = weapons armed.
    1.0 = fully deflected = wings UP = weapons cold.

    RED is the only armed level (`ShipClass.SetAlertLevel` powers weapons on at
    RED and off at every other level), so this keys off exactly that condition
    rather than re-deriving "armed" from subsystem power.
    """
    from engine.appc.ships import ShipClass

    return 0.0 if int(alert_level) == ShipClass.RED_ALERT else 1.0


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


def deflection_target_for(ship) -> float:
    """Wing deflection wanted for `ship`. THE SIGNAL DIFFERS BY WHO FLIES IT.

    **Player: alert level.** The alert keys are how a human tells the ship to
    brace, so that is what the wings answer.

    **NPC: does it have a TARGET.** BC's alert level does not vary on an NPC.
    It is RED from spawn -- measured on the original exe across eleven
    campaign missions (`ships.py`, stbc-oracle bible section 13 N2: every
    non-player ship, station and asteroid reads alert 2 from the first
    snapshot) -- and nothing in the SDK lowers it again. Keying NPC wings off
    alert would therefore leave every AI Bird of Prey permanently
    attack-posed, and the transition would only ever be visible on a
    player-flown ship.

    A target DOES vary: the SDK's `SelectTarget` preprocessor sets one at
    runtime (`ai_driver.py:1452`). So it is the signal that actually answers
    "is this ship fighting", which is the question the wings pose asks.

    This is a DELIBERATE asymmetry, not an oversight -- see OQ-11 in
    `docs/superpowers/specs/2026-09-23-ship-part-articulation-design.md`. The
    measured RED spawn default is left untouched; we simply stop treating
    alert level as a combat signal for ships it was never a combat signal for.

    Falls back to alert level for an object with no `GetTarget`, so a prop or
    a test double holds its spawn pose rather than raising on the 60 Hz tick.
    """
    if _is_player(ship):
        try:
            return deflection_target(ship.GetAlertLevel())
        except Exception:  # noqa: BLE001
            return 0.0

    getter = getattr(ship, "GetTarget", None)
    if getter is None:
        try:
            return deflection_target(ship.GetAlertLevel())
        except Exception:  # noqa: BLE001
            return 0.0
    try:
        target = getter()
    except Exception:  # noqa: BLE001
        return 0.0
    # A target may be an object reference OR an unresolved string name
    # (ships.py SetTarget accepts both); either counts as hunting.
    return 0.0 if target else 1.0


def ease(current: float, target: float, dt: float) -> float:
    """Ramp `current` toward `target` at the fixed travel rate.

    Linear. A spike wants a motion that is obviously right or obviously wrong;
    an ease curve would hide a bad pivot behind pleasant motion.
    """
    if TRAVEL_SECONDS <= 0.0:
        return target
    step = dt / TRAVEL_SECONDS
    delta = target - current
    if abs(delta) <= step:
        return target
    return current + (step if delta > 0 else -step)


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


@functools.lru_cache(maxsize=None)
def _part_range(part) -> float:
    """Peak-to-peak spread of `part`'s authored angle across every state.

    A single per-part constant rather than a per-transition one, computed
    once and cached (parts are long-lived: either a module-level `Part` in
    `_RIGS` or a snapshot entry in `articulated_part._BY_LEAF` that lives for
    the leaf's lifetime), so `tick_ship` does not rebuild a 4-element list
    every part every tick. This gives `ease_angle` a rate that is fixed per
    part rather than recomputed per transition -- see that function's
    docstring for exactly what guarantee that does, and does not, deliver.
    """
    from engine.appc.articulated_part import STATES
    values = [part.angle_for(state) for state in STATES]
    return max(values) - min(values)


def _swing_range(part) -> float:
    """`ease_angle`'s `part_range` for `part`, whichever rig system it is
    from. A NEW-rig part (`ArticulatedPartProperty`) uses `_part_range`
    (peak-to-peak across all four states). An OLD-rig part (this module's
    hardcoded `Part`) only ever swings between 0 and its own `angle_deg`, so
    its range IS `abs(angle_deg)`."""
    if callable(getattr(part, "angle_for", None)):
        return _part_range(part)
    return abs(part.angle_deg)


def _part_name(part) -> str:
    """Name to key `part` by in `ship._articulation_angles`. Both part
    shapes are supported: the NEW `ArticulatedPartProperty`
    (`.GetName()`) and this module's OLD hardcoded `Part` (`.node`)."""
    getter = getattr(part, "GetName", None)
    return getter() if callable(getter) else part.node


def _target_angle(part, state: str) -> float:
    """Degrees `part` should swing to at `state`.

    A NEW-rig part carries one authored angle per state via `.angle_for`. An
    OLD-rig `Part` -- still the only data that exists for the stock Bird of
    Prey until Task 5 migrates it into the template format -- carries a
    single `angle_deg` for a binary swing: RED is the model's rest pose
    (down/armed) and everything else, including "warp", is the fully
    deflected one (up/cold). Warp folding into "cold" rather than getting
    its own pose is the 4-state rule (wing position is a flight
    configuration) applied to the only data an OLD-rig part actually has.
    """
    angle_for = getattr(part, "angle_for", None)
    if callable(angle_for):
        return angle_for(state)
    return 0.0 if state == "red" else part.angle_deg


def angle_for_part(ship, part) -> float:
    """`ship`'s current eased angle (degrees) for `part`.

    Primary source is `ship._articulation_angles` ({name: degrees}),
    written by `tick_ship` every sim tick -- this is what every reader of a
    ship's LIVE pose (`host_loop._sync_ship_articulation`,
    `part_severance.part_for_live_point`, `part_transform_point` below)
    consults; `GetArticulationDeflection`/`SetArticulationDeflection` are no
    longer written anywhere in this module.

    Falls back to the OLD scalar `ship.GetArticulationDeflection() *
    part.angle_deg` for an OLD-rig `Part` whose ship was never ticked
    through this module -- e.g. a render-sync unit test that drives
    `_sync_ship_articulation` directly, with no prior `tick_ship` call. This
    is scaffolding for an un-ticked ship / pre-existing test double, not a
    live production path: a real ship gets ticked every frame
    (`engine.core.loop`), so the primary branch above is what production
    code actually takes.
    """
    name = _part_name(part)
    angles = getattr(ship, "_articulation_angles", None)
    if angles and name in angles:
        return angles[name]
    angle_deg = getattr(part, "angle_deg", None)
    if angle_deg is None:
        return 0.0
    try:
        return float(angle_deg) * float(ship.GetArticulationDeflection())
    except Exception:  # noqa: BLE001 - not a ShipClass (test double / prop)
        return 0.0


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

    Parts come from the NEW per-state template
    (`articulated_part.parts_for_leaf`) when one is registered for `leaf`;
    otherwise this falls back to this module's OLD hardcoded `rig_for` --
    the only data the stock Bird of Prey has until Task 5 migrates it -- read
    through `_target_angle`'s 2-state fold (RED = down/armed, everything
    else = up/cold). Either way the result lands in
    `ship._articulation_angles` ({name: degrees}), which is what every
    reader of a ship's LIVE pose now consults; nothing writes
    `ship.SetArticulationDeflection` any more.

    A ship with no parts under EITHER system is skipped before any
    allocation, so the overwhelming majority of hulls pay one leaf lookup.
    """
    from engine.appc.articulated_part import parts_for_leaf
    leaf = leaf_for(ship)
    parts = parts_for_leaf(leaf) or rig_for(leaf)
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
        target = _target_angle(part, state)
        if current != target:
            angles[name] = ease_angle(current, target,
                                      part_range=_swing_range(part), dt=dt)


def parts_for_ship(ship) -> tuple[Part, ...]:
    """Articulation parts for `ship`, or () when it has no rig."""
    return rig_for(leaf_for(ship))


# ── Part geometry and detachability (phase 2a) ───────────────────────────────
# Per-part AABBs in SHIP/BODY units (model NIF units / 100 -- BC_MODEL_SCALE is
# 0.01, so hardpoint positions and these boxes share one frame).
#
# AUTHORED rather than read from the model at runtime, because nothing exposes
# per-part bounds to Python: `model_bounds` returns unnamed per-shape spheres
# and cannot be mapped back to a named node. A `model_part_bounds` binding
# would generalise this; against a data set of one ship it is not yet worth a
# new boundary crossing. Measured from BirdOfPrey.nif -- see spec section 2.4.
#
# NOTE the wing boxes OVERLAP the body box (wings start at |x| 0.1236, the body
# reaches 0.31): the wing roots are embedded in the hull. That overlap is why
# attribution falls back to the body when a point is inside more than one box —
# see part_severance.part_for_point.
PART_BOXES = {
    "birdofprey": {
        # name: ((min_x, min_y, min_z), (max_x, max_y, max_z))
        "head":        ((-0.1010, 0.1377, -0.0885), (0.1010, 0.9044, 0.0747)),
        "left wing":   ((-1.0258, -0.6777, -0.7125), (-0.1236, 0.5344, 0.1862)),
        "left wing01": ((0.1236, -0.6777, -0.7125), (1.0258, 0.5344, 0.1862)),
        "birdofprey":  ((-0.3112, -0.7044, -0.1331), (0.3137, 0.2922, 0.2125)),
    },
}

# Parts that may SHEAR OFF, and the share of the ship's MAX hull each must
# absorb before it does. Authored, never automatic: the body must never detach,
# and the head coming off is not wanted either. A part absent from here
# accumulates nothing and can never be lost.
#
# 0.20 -> a 4000-hull Bird of Prey sheds a wing after 800 damage attributed to
# it; both wings cost 40% of the hull. Tunable here with no rebuild, which is
# deliberate: this is the number most likely to need a live adjustment.
DETACHABLE = {
    "birdofprey": {
        "left wing":   0.20,
        "left wing01": 0.20,
    },
}


def part_boxes_for(leaf):
    """Authored per-part AABBs (ship units) for a hardpoint leaf, or {}."""
    if not leaf:
        return {}
    return PART_BOXES.get(str(leaf).lower(), {})


def detachable_for(leaf):
    """{part name: hull fraction that shears it} for a leaf, or {}."""
    if not leaf:
        return {}
    return DETACHABLE.get(str(leaf).lower(), {})


def part_transform_point(ship, point):
    """Where a body-frame point ends up once its part has articulated.

    In and out are BODY frame, SHIP units (what subsystem mounts and
    PART_BOXES use). Identity for a ship with no rig, for a point on no
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
    """
    parts = rig_for(leaf_for(ship))
    if not parts:
        return point

    from engine.appc.part_severance import part_for_point, is_detached
    name = part_for_point(leaf_for(ship), point)
    if name is None:
        return point
    if is_detached(ship, name):
        # A severed part has no hinge left to follow -- rotating a mount
        # about a phantom wing would drag it along with a wing that is no
        # longer there. See host_loop._sync_ship_articulation for the
        # render-side twin of this guard.
        return point
    part = next((p for p in parts if p.node == name), None)
    if part is None:
        return point

    angle_deg = angle_for_part(ship, part)
    if angle_deg == 0.0:
        return point
    return point_at_angle(part, point, angle_deg)


def point_at_angle(part, point, angle_deg):
    """Where `point` (body frame, ship units) ends up when `part` alone sits
    at `angle_deg` degrees about its hinge.

    The ship-free, angle-based twin of `point_at_deflection`: no
    attribution, no severance check, no read of any ship state. Used by the
    LIVE-pose readers (`part_transform_point`,
    `part_severance.part_for_live_point`), which already have a concrete
    current angle in hand (from `angle_for_part`) rather than a 0..1
    fraction of an authored maximum.
    """
    pivot, axis, theta = rotation_for(part, angle_deg)
    return _rotate_about(point, pivot, axis, theta)


def point_at_deflection(part, point, deflection):
    """Where `point` (body frame, SHIP units) ends up when `part` alone sits
    at `deflection`.

    The ship-free half of `part_transform_point`: no attribution, no
    severance check, and — the reason it exists separately — no read of any
    ship's LIVE deflection. `hull_bounds.bound_radius` needs the reach at
    deflection 1.0 while the ship is at rest, which the ship-driven call
    cannot give it. Kept taking a deflection fraction (not a raw angle,
    unlike its sibling `point_at_angle`) because both of its OLD-rig callers
    (`hull_bounds.py`, `test_part_severance_emitters.py`'s `_posed` fixture)
    already speak in that unit.
    """
    # rotation_for now takes raw degrees (Task 4); this function's own
    # contract is unchanged (a 0..1 fraction of `part`'s authored max), so the
    # conversion happens HERE, at the one remaining OLD-rig call site, rather
    # than by asking every caller to redo the multiplication.
    pivot, axis, theta = rotation_for(part, part.angle_deg * deflection)
    return _rotate_about(point, pivot, axis, theta)


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
