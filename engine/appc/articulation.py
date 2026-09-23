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

# Ship units -> model (NIF) units, for the C++ boundary only. = BC_MODEL_SCALE.
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


def rotation_for(part: Part, deflection: float) -> tuple[
        tuple[float, float, float], tuple[float, float, float], float]:
    """Return (pivot, unit_axis, theta_radians) for `part` at `deflection`.

    Kept separate from the matrix build so the C++ binding takes the same three
    values the SPV gizmo would eventually author, rather than a baked matrix.
    """
    ax, ay, az = part.axis
    n = math.sqrt(ax * ax + ay * ay + az * az)
    if n <= 0.0:
        unit = (0.0, 1.0, 0.0)
    else:
        unit = (ax / n, ay / n, az / n)
    theta = math.radians(part.angle_deg) * float(deflection)
    return part.pivot, unit, theta


# ── Dev override ─────────────────────────────────────────────────────────────
# A forced deflection that outranks the alert-driven target, so the pivots can
# be judged at a frozen pose instead of only in passing. None = follow alert.
# Dev-only by construction: the only caller is a dev keybinding, which
# `dev_mode` never registers outside --developer.
_dev_override: "float | None" = None


def set_dev_override(value: "float | None") -> None:
    """Force every rigged ship to a fixed deflection, or None to release."""
    global _dev_override
    _dev_override = None if value is None else max(0.0, min(1.0, float(value)))


def dev_override() -> "float | None":
    return _dev_override


def reset() -> None:
    """Drop dev state. Called on mission swap and from the test fixture."""
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
    """Advance one ship's articulation deflection by `dt`.

    A ship with no rig is skipped before any easing, so the overwhelming
    majority of hulls pay one cached-attribute read.
    """
    if not has_rig(leaf_for(ship)):
        return
    forced = _dev_override
    if forced is not None:
        target = forced
    else:
        try:
            target = deflection_target(ship.GetAlertLevel())
        except Exception:  # noqa: BLE001
            return
    try:
        current = float(ship.GetArticulationDeflection())
    except Exception:  # noqa: BLE001 - not a ShipClass (test double / prop)
        return
    if current != target:
        ship.SetArticulationDeflection(ease(current, target, dt))


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
