#pragma once

#include <cstdint>
#include <optional>
#include <stdexcept>
#include <string>

#include "dauntless/combat/mirror.h"

// The posed-parts arithmetic of the native combat geometry (spec
// docs/superpowers/specs/2026-11-01-native-combat-posed-parts-design.md §4.4,
// map docs/reference/engine/native-combat/posed-parts-map.md §4 P1-P2).
//
// WHICH part a mount sits on is never decided here: Python resolves it and
// pushes the subsystem's part slot (an index into its ship's pose table,
// stamped with the part-map generation). This header only reads that slot
// and does the pose arithmetic Python's part_pose.apply does.

namespace dauntless::combat {

// Python None for a target offset's mount subsystem: an offset no mount
// claims (a Manual Aim pick), aimed at as a plain body point (fire control
// native only, M5).
constexpr int64_t kNoMount = -1;

// The posed-part fallbacks a kernel counts by reason (native-combat posed
// parts, Task 4: spec §4.5). Each IS a std::invalid_argument (Python
// ValueError), so every existing `catch (const std::invalid_argument&)`
// takes it exactly as before; a kernel that counts catches the subclass.
//   PartStale    -- a part slot the read needs is not current (stamped
//                   behind the Mirror's part_gen, past the pose table, or
//                   asked on another ship): Python must answer.
//   MountUnknown -- authored_mount_subsystem cannot tell (kMountUnknown).
// An offset no mount claims, or one within 1e-5 of a mount but not its own
// point, is no fallback: a plain body point (fire control native only, M5,
// M8.5).
struct PartStale : std::invalid_argument {
    explicit PartStale(const std::string& what)
        : std::invalid_argument(what) {}
};
struct MountUnknown : std::invalid_argument {
    explicit MountUnknown(const std::string& what)
        : std::invalid_argument(what) {}
};

// P1/P2: part_pose.apply (PP:72-75) on the row-major pose, unless the entry
// is `identity` or `detached` -- then `x` itself, unchanged (a branch, never
// a multiply: a multiply by an identity flips -0.0 and adds a sub-1e-9 t).
Vec3 apply_part_pose(const PartPose& pose, const Vec3& x);

// What a subsystem's pushed part slot says, read only when its ship's
// has_posed_parts is 1:
//   none  -- no pose to apply: the ship is unposed, the slot is -1, or the
//            part is at identity or detached (Python returns the point);
//   ok    -- the part's pose applies;
//   stale -- the slot is not current (part_gen behind the Mirror's) or
//            indexes past the pose table: Python must answer.
enum class SlotState { none, ok, stale };

// The pose a subsystem's slot names on `ship` (the ship the slot was
// resolved against). `*pose` is set only for ok.
SlotState slot_pose(const Mirror& m, const ObjectRow& ship,
                    const SubsystemRow& sub, const PartPose** pose);

// The subsystem's own mount `_position` carried by its part (P1/P2), in the
// ship's body frame, unscaled. `*out` is set for none (the `_position`
// itself) and ok (the posed point); untouched for stale.
SlotState posed_local(const Mirror& m, const ObjectRow& ship,
                      const SubsystemRow& sub, Vec3* out);

// authored_mount_subsystem's "the mirror cannot tell" (Python must answer):
// distinct from kNoMount (Python None). The same value as a ref the mirror
// cannot name, so target_offset_world falls back on it as is.
constexpr int64_t kMountUnknown = kRefUnrepresentable;

// part_severance.authored_mount_subsystem (PS:502-514; MAP §3.4, R3): the
// FIRST subsystem of `target`'s mount_order (combat._iter_subsystems order)
// whose `_position` is within 1e-5 of `offset` on every axis, by Python's
// own `abs(mount[i] - point[i]) <= eps` (a NaN never matches); kNoMount if
// none. kMountUnknown when the mirror cannot answer: an entry it cannot name
// (kRefUnrepresentable, or a since-freed row) reached before a match, or a
// target that is not a ShipClass (its mount_order is never pushed, so an
// empty one says nothing).
int64_t authored_mount_subsystem(const Mirror& m, const ObjectRow& target,
                                 const Vec3& offset);

}  // namespace dauntless::combat
