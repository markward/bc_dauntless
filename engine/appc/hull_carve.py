"""Pure mappings for the hull-carve (breach) trigger.

No host / renderer dependency. Combat damage -> field strength, weapon splash
-> merge-influence radius (GU). The C++ hull-carve field (native/src/scenegraph)
accumulates strength and derives the visible carve radius from it; this module
only computes the scalar inputs the emission path in engine.appc.hit_feedback
feeds to host.hull_carve_add.

BC's DamageTool authored damage as an additive metaball field: strength
accumulates spatially and a hole appears once the summed field crosses an iso
level (the strength->radius curve + iso live in C++ — see
native/.../hull_carve.h). So sustained weak fire (phaser dribble) now builds up
to a breach instead of being hard-gated out per hit. Constants here are
eye-calibration knobs (tunable without a native rebuild).
"""

# Field strength deposited per unit of absorbed hull damage. 1:1 — strength is
# just accumulated absorbed-hull, so geometry damage builds up GRADUALLY over
# sustained fire instead of a single moderate hit one-shotting a full breach
# (which read as all-or-nothing). Heavy hits still deposit proportionally more.
# The C++ curve (kHullCarve* in native/.../hull_carve.h) maps accumulated
# strength -> visible radius, emerging small at the iso and growing. Raise this
# to make geometry damage appear readier per hit.
STRENGTH_PER_HULL = 1.0

# Merge-influence radius (GU): how close repeated hits must land to accumulate
# into the same carve. Floored so phaser hits clustered around a subsystem build
# up together even when the weapon's splash is tiny.
CARVE_INFLU_MIN_GU = 0.5
CARVE_INFLU_SCALE = 1.0

# Visible-radius floor (GU) for carves that carry their own size (authored
# wrecks, core breach) — combat hits pass floor 0 and rely on accumulated
# strength crossing the C++ iso.
MIN_CARVE_RADIUS_GU = 0.25

# Game-time seconds between deposits emitted on one ship, so a continuous beam
# cannot spam the field (mirrors hit_feedback.DECAL_EMIT_INTERVAL).
CARVE_EMIT_INTERVAL = 0.25


def carve_strength(absorbed_hull: float) -> float:
    """Field strength deposited by a hit that absorbed `absorbed_hull` hull."""
    return max(0.0, float(absorbed_hull)) * STRENGTH_PER_HULL


def carve_influ_gu(splash_radius_gu: float) -> float:
    """Merge-influence radius (GU) for a hit, floored so clustered fire
    accumulates even with a tiny weapon splash."""
    return max(CARVE_INFLU_MIN_GU, float(splash_radius_gu) * CARVE_INFLU_SCALE)
