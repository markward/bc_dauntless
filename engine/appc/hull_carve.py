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
#
# ⚠️ DO NOT LOWER THIS TO MAKE HOLES SMALLER. It controls READINESS, not SIZE.
# Cut to 0.25 on 2026-09-23 in response to hulls "carving like butter"; craters
# then stopped appearing AT ALL across three live battles, and it was reverted
# the same day.
#
# Why it fails: strength accumulates PER CARVE SITE, not per ship
# (hull_carve.cc `c.strength += strength`, merged only within ~0.09 GU). The
# C++ iso is 150, and one full-strength weapon hit is ~200-250 absorbed hull
# (BoP PortCannon SetMaxDamage(200); Galaxy VentralPhaser3 250) — so at 1:1 a
# single clean hit just crosses it. At 0.25 it takes four hits landing within
# ~15 m of each other, which on a manoeuvring target essentially never happens.
#
# The denominator that matters is damage AT ONE POINT, never the ship's total
# hull HP. To make holes SMALLER, change kHullCarveRadiusMaxGu in
# native/src/scenegraph/include/scenegraph/hull_carve.h instead.
# Guarded by tests/unit/test_hull_carve_mapping.py::
# test_one_full_strength_hit_can_open_a_hole.
STRENGTH_PER_HULL = 1.0

# Merge-influence radius (GU): how close two hits must land to deepen the SAME
# carve (in place) rather than start a new one. Kept SMALL so a swept beam lays
# down a line of distinct carves (a gouge) instead of all the hits collapsing
# into one — only near-coincident re-hits deepen. Raise it to merge more readily
# (fewer, fatter carves); lower it for a finer gouge.
CARVE_INFLU_MIN_GU = 0.18
CARVE_INFLU_SCALE = 1.0

# Visible-radius floor (GU) for carves that carry their own size (authored
# wrecks, core breach) — combat hits pass floor 0 and rely on accumulated
# strength crossing the C++ iso.
MIN_CARVE_RADIUS_GU = 0.25

# Game-time seconds between deposits emitted on one ship (perf + breach-VFX cap).
# Strength is accumulated between emits so no damage is lost; a smaller interval
# lays a DENSER gouge under a sweeping beam (more carve points along the line) at
# the cost of more hull_carve_add calls + breach events. Raise it if a sweep
# sprays too much debris.
CARVE_EMIT_INTERVAL = 0.1


def carve_strength(absorbed_hull: float) -> float:
    """Field strength deposited by a hit that absorbed `absorbed_hull` hull."""
    return max(0.0, float(absorbed_hull)) * STRENGTH_PER_HULL


def carve_influ_gu(splash_radius_gu: float) -> float:
    """Merge-influence radius (GU) for a hit, floored so clustered fire
    accumulates even with a tiny weapon splash."""
    return max(CARVE_INFLU_MIN_GU, float(splash_radius_gu) * CARVE_INFLU_SCALE)
