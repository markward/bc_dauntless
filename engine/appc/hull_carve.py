"""Pure mappings for the hull-carve (breach) trigger.

No host / renderer dependency: absorbed hull damage -> should-carve bool,
weapon splash radius -> carve radius (GU). The C++ hull-carve pass owns the
actual geometry; this module only computes the scalar inputs the emission
path in engine.appc.hit_feedback feeds to host.hull_carve_add.

Carving 2a is a centered sphere: no depth/direction logic here.
Constants are eye-calibration tuning knobs.
"""

# Absorbed hull damage below this leaves only a scorch decal, no carve.
# Raised from 40 → 60 (Mark 2a feedback: effect triggered too readily; set
# between the phaser dribble and a solid torpedo hit to carve less readily).
MIN_CARVE_HULL = 60.0

# Carve radius = splash radius (GU) * scale, with a floor so a carve always
# has some extent. 0.25 GU floor = 25 model units (~14% of hull radius).
# Toned down from 1.5 → 1.0 (Mark 2a feedback: holes too big).
CARVE_RADIUS_SCALE = 1.0
MIN_CARVE_RADIUS_GU = 0.25

# Game-time seconds between carves emitted on one ship, so a continuous beam
# cannot saturate the carve field (mirrors hit_feedback.DECAL_EMIT_INTERVAL).
CARVE_EMIT_INTERVAL = 0.25


def should_carve(absorbed_hull: float) -> bool:
    """True iff this hit is heavy enough to carve geometry (vs scorch only)."""
    return float(absorbed_hull) >= MIN_CARVE_HULL


def carve_radius_gu(splash_radius_gu: float) -> float:
    """Scale the gameplay splash radius (GU) to a carve radius (GU), floored
    so the carve sphere always has some extent."""
    return max(MIN_CARVE_RADIUS_GU, float(splash_radius_gu) * CARVE_RADIUS_SCALE)
