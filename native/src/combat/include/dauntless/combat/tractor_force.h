#pragma once

#include <cstdint>
#include <vector>

#include "dauntless/combat/mirror.h"
#include "dauntless/transform_store.h"

// The tractor force (fire control native only, M4, ruling R7): a port of
// engine/appc/tractor.py's force, which it replaces. One step per sim tick,
// in the motion stage (`ship_motion.tick_tractors`, profiler row
// `motion.tractors`), after the motion rows and before the publish.
//
// THE LAW. Not a spring-damper: a mass-capped KINEMATIC displacement,
// written straight into the transform store. Each object's engagement speed
// is
//     speed(m) = min(TRACTOR_REFERENCE_SPEED_GUPS * TRACTOR_REFERENCE_MASS
//                    / m, TRACTOR_MAX_SPEED_GUPS)    GU/s
// for a ShipClass (m <= 0 reads TRACTOR_FALLBACK_MASS), 0 (immovable) for
// anything else. Per mode (TractorBeamSystem.TBS_*, App.py:6774-6779), with
// u the unit vector source -> target and the standoff the two radii plus
// TRACTOR_STANDOFF_MARGIN_GU:
//   HOLD   the target moves toward the point it held when grabbed (captured
//          on the first step), at most speed*dt, snapping when within one
//          step; its velocity is zeroed. The source is not moved.
//   TOW    the target moves toward the offset it held when grabbed, in the
//          source's body frame (captured on the first step), rotated by the
//          source now; the source is displaced along u by
//          speed(source) * TRACTOR_TOW_DRAG_FRACTION * dt.
//   PULL   the target moves toward source + u*standoff, then the source
//          toward target_before + (-u)*standoff, each at its own speed.
//   PUSH   the target is displaced along u by speed*dt, the source along -u.
//   DOCK_STAGE_1 / _2  the target moves toward source + u*standoff at
//          speed * TRACTOR_DOCK_GENTLE_FRACTION.
// Coincident centres (|d| < TRACTOR_EPS) do nothing that step. Every float
// is Python's: the same operand order, `** 0.5` as py_pow.
//
// INPUTS (read, never written by anything else in the step): the mirror --
// each ship's `_tractor_beam_system`, that system's `_mode` and engage state
// (engage_kind / engage_point), its children's `_firing` and `_target`, each
// object's is_ship_class, `_mass`, `_radius` and real IsDead -- the
// tractor globals, and every pose in `store`.
//
// OUTPUTS: the pose writes, made in `store` as they are computed (a later
// tractor of the same step reads the moved pose, as Python's did) and
// listed in order; the targets HOLD damps (Python then calls
// SetVelocity(TGPoint3(0, 0, 0))); and the engage geometry captured (also
// written to the mirror; Python stores it as `_engage_state`). So a later
// motion thread can own this step: it touches no Python and no state but
// these.
//
// A tractor whose rows the mirror cannot name (an unrepresentable ref, a
// stale row, the source with no transform) does nothing that step and is
// counted in `skipped`; a single firing projector's target it cannot read
// (no real IsDead, no transform) is skipped and counted alone, the ship's
// other targets still applied. The rest of the step goes on.

namespace dauntless::combat {

// TractorBeamSystem.TBS_* (App.py:6774-6779).
enum class TractorMode : int64_t {
    Hold = 0, Tow = 1, Pull = 2, Push = 3, DockStage1 = 4, DockStage2 = 5
};

// SubsystemRow::engage_kind (mirror.h).
constexpr int64_t kEngageNone = 0, kEngageHold = 1, kEngageTow = 2;

struct TractorPoseWrite {
    int64_t object = -1;
    Vec3 position{0, 0, 0};
};

struct TractorEngageCapture {
    int64_t system = -1;
    int64_t kind = kEngageNone;  // kEngageHold or kEngageTow
    Vec3 point{0, 0, 0};
};

struct TractorForceResult {
    std::vector<TractorPoseWrite> poses;
    std::vector<int64_t> zero_velocity;
    std::vector<TractorEngageCapture> captures;
    int64_t applied = 0;  // firing emitters whose mode was applied
    int64_t skipped = 0;  // tractors / targets the mirror could not name
};

// One step over `ships` (Object handles in host order; -1 or a stale handle
// is skipped and counted), `dt` seconds. dt <= 0 does nothing.
TractorForceResult tractor_force_step(Mirror& m, TransformStore& store,
                                      const std::vector<int64_t>& ships,
                                      double dt);

}  // namespace dauntless::combat
