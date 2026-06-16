"""Pure mappings for the persistent hull-deformation (crater) store.

No host / renderer dependency: absorbed hull damage -> crater depth (GU),
weapon splash radius -> crater radius (GU), and the inward shove direction.
The C++ HullCraterField owns the actual records (see
native/src/scenegraph/hull_craters.*) and converts GU -> model units; this
module only computes the scalar/vector inputs the emission path in
engine.appc.hit_feedback feeds to host.hull_deform_add.

Mirrors engine.appc.damage_decals. Constants here and the shader's
RUPTURE_MIN/RUPTURE_MAX (native/src/renderer/shaders/opaque.frag) are
eye-calibration knobs; see docs/superpowers/plans/...-plan6-hit-trigger.md.
"""

# Absorbed hull damage below this leaves only a scorch decal, no geometry
# crater. Set near the spark threshold (hit_feedback.SPARK_HULL_THRESHOLD =
# 80) so a torpedo/ram dents but per-tick phaser dribble (~0.28/tick) does
# not. Tuning knob.
MIN_DEFORM_HULL = 40.0

# GU of crater depth deposited per unit of absorbed hull damage, and the
# per-hit depth cap. The crater field also caps the *cumulative* merged depth
# (HullCraterField::kMaxDepth, in model units). Tuning knobs — calibrate by
# eye against the live renderer together with RUPTURE_MIN/MAX.
DEPTH_GU_PER_HULL = 0.0004
MAX_CRATER_DEPTH_GU = 0.5

# Crater radius = splash radius (GU) * scale, with a floor so a crater always
# has falloff extent. Independent of the decal radius scale. Tuning knobs.
DEFORM_RADIUS_SCALE = 1.5
MIN_DEFORM_RADIUS_GU = 0.15

# Game-time seconds between craters emitted on one ship, so a continuous beam
# cannot saturate the 24-slot crater field in a fraction of a second (mirrors
# hit_feedback.DECAL_EMIT_INTERVAL). Tuning knob.
DEFORM_EMIT_INTERVAL = 0.25


def should_deform(absorbed_hull: float) -> bool:
    """True iff this hit is heavy enough to deform geometry (vs scorch only)."""
    return float(absorbed_hull) >= MIN_DEFORM_HULL


def crater_depth_gu(absorbed_hull: float) -> float:
    """Map hull damage actually dealt to a crater depth in game units.

    Monotonic in absorbed_hull, saturating at MAX_CRATER_DEPTH_GU. Zero for
    non-positive input.
    """
    if absorbed_hull <= 0.0:
        return 0.0
    return min(MAX_CRATER_DEPTH_GU, float(absorbed_hull) * DEPTH_GU_PER_HULL)


def crater_radius_gu(splash_radius_gu: float) -> float:
    """Scale the gameplay splash radius (GU) to a crater radius (GU), floored
    so the displacement always has some extent."""
    return max(MIN_DEFORM_RADIUS_GU, float(splash_radius_gu) * DEFORM_RADIUS_SCALE)


def _normalize(v, fallback):
    """Unit vector for v=(x,y,z), or `fallback` when v is ~zero-length."""
    x, y, z = v
    m = (x * x + y * y + z * z) ** 0.5
    if m <= 1e-9:
        return fallback
    return (x / m, y / m, z / m)


def impact_direction(normal, source_pos=None, hit_point=None):
    """Unit inward shove direction in WORLD space, as an (x, y, z) tuple.

    Prefers the weapon ray (source -> hit point) when both positions are
    given and the ray points INTO the surface; otherwise falls back to the
    inward surface normal (-normal). The guard guarantees the hull is never
    displaced outward. All arguments are (x, y, z) tuples.
    """
    nx, ny, nz = normal
    inward = _normalize((-nx, -ny, -nz), fallback=(-nx, -ny, -nz))
    if source_pos is None or hit_point is None:
        return inward
    ray = _normalize(
        (hit_point[0] - source_pos[0],
         hit_point[1] - source_pos[1],
         hit_point[2] - source_pos[2]),
        fallback=None)
    if ray is None:
        return inward
    if ray[0] * inward[0] + ray[1] * inward[1] + ray[2] * inward[2] <= 0.0:
        return inward
    return ray
