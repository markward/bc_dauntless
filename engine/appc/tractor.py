"""Per-tick tractor-beam EFFECT — moves the tractored target each tick.

A firing tractor emitter (one sustained grab beam per system; see
TractorBeamSystem) applies its mode's physics to the locked target. Modes
(sdk/.../App.py:6774-6779):

    HOLD  — pin the target at the world-point it occupied when grabbed and
            damp its velocity to rest (stops a moving ship, holds it there).
    TOW   — lock the target at the offset (in the SOURCE body frame) it held
            when grabbed, so it follows the tower (per AI/PlainAI/Warp.py
            SetupTowing).
    PULL  — draw the target toward the source.
    PUSH  — drive the target away from the source.
    DOCK_STAGE_1 / DOCK_STAGE_2 — gentle guided PULL toward a dock standoff
            point just off the source (stub: no full staged docking handshake).

The force is NATIVE (fire control native only, M4 and ruling R7):
native/src/combat/include/dauntless/combat/tractor_force.h is its law,
line for line, and native_combat.tractor_force_step its driver. It is a
mass-capped KINEMATIC displacement written straight into the transform store
(not a spring-damper, and no MaxDamage term):

  * Each ship has a mass-scaled engagement *speed*:
        speed(m) = clamp(REF_SPEED · REF_MASS / m, 0, MAX_SPEED)
    so a shuttle (m≈10) is flung, a Galaxy (m≈120) is sluggish, and a starbase
    (m≈1e6) is effectively immovable — for free. Non-ship bodies (planets,
    suns) are immovable (speed 0). Mirrors collisions.py's inverse-mass split.
  * The effect is a DIRECT position displacement each tick, recomputed from
    live geometry — NOT a write to `_velocity` (the motion integrator
    overwrites that every frame for AI ships). Because the force is
    recomputed each tick it self-corrects and needs no persistent decaying
    overlay (unlike collisions).
  * Reciprocity (Newton's 3rd law): PULL/PUSH/TOW also move the SOURCE,
    opposite-direction, at speed(m_source) — momentum-consistent because
    speed(m)∝1/m. HOLD anchors the target only (no source reaction).

Run once per tick from the motion stage (ship_motion.tick_tractors,
`motion.tractors` under `gl.motion`: Mark 2026-11-04), after every motion
row and before the stage's publish, so a beam the held-weapon pump grips in
a tick's combat step first pulls in the next tick. No-op for ships
without a firing tractor, so production combat for non-tractor ships stays
byte-identical.

The constants below are the force's ONE home: native_combat pushes them to
the kernel as globals (with `_EPS` as TRACTOR_EPS).
"""
# -- Tuning constants (tuned by feel; game units, 1 GU = 175 m) ---------------
TRACTOR_REFERENCE_MASS      = 100.0   # mid-hull reference (Galaxy ≈ 120)
TRACTOR_REFERENCE_SPEED_GUPS = 5.0    # engagement speed for a reference-mass hull
TRACTOR_MAX_SPEED_GUPS      = 20.0    # cap so a light hull isn't flung absurdly
TRACTOR_FALLBACK_MASS       = 1.0e4   # ship reporting mass<=0 → heavy (≈immovable);
                                      # matches collisions.COLLISION_FALLBACK_MASS
TRACTOR_TOW_DRAG_FRACTION   = 0.25    # how much a towed hull drags the tower
TRACTOR_DOCK_GENTLE_FRACTION = 0.4    # docking approach is gentler than a PULL
TRACTOR_STANDOFF_MARGIN_GU  = 3.0     # gap held beyond the combined hull radii so
                                      # PULL/DOCK settle the target NEAR the
                                      # emitting ship, never inside its hull

_EPS = 1e-6     # coincident centres: no beam direction, no force that tick


def advance_tractors(ships, dt: float) -> None:
    """Apply every firing tractor's mode physics to its target for one tick
    (the native tractor force step)."""
    from engine.appc import native_combat
    native_combat.tractor_force_step(ships, dt)
