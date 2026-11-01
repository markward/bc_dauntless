// The posed-parts arithmetic -- see part_pose.h. MAP = docs/reference/engine/
// native-combat/posed-parts-map.md.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "dauntless/combat/part_pose.h"

#include "geometry_internal.h"

namespace dauntless::combat {

// part_pose.apply (part_pose.py:72-75; MAP P1), or the point itself (P2):
// articulation.part_transform_point returns `point` for an identity pose,
// and _live_part names no part for a detached one.
Vec3 apply_part_pose(const PartPose& pose, const Vec3& x) {
    if (pose.identity || pose.detached) return x;
    const Vec3 r = detail::mult_matrix_left(pose.r, x);
    return {r[0] + pose.t[0], r[1] + pose.t[1], r[2] + pose.t[2]};
}

SlotState slot_pose(const Mirror& m, const ObjectRow& ship,
                    const SubsystemRow& sub, const PartPose** pose) {
    // An unposed ship is the identity everywhere; its slots are not audited
    // (the table is empty) and are never read.
    if (!ship.has_posed_parts) return SlotState::none;
    // The stamp first: a never-resolved slot is (-1, 0) and must not read
    // as "no part".
    if (sub.part_gen != m.part_gen()) return SlotState::stale;
    if (sub.part_slot < 0) return SlotState::none;
    const auto i = static_cast<size_t>(sub.part_slot);
    if (i >= ship.part_poses.size()) return SlotState::stale;
    const PartPose& p = ship.part_poses[i];
    if (p.identity || p.detached) return SlotState::none;
    *pose = &p;
    return SlotState::ok;
}

SlotState posed_local(const Mirror& m, const ObjectRow& ship,
                      const SubsystemRow& sub, Vec3* out) {
    const PartPose* pose = nullptr;
    const SlotState st = slot_pose(m, ship, sub, &pose);
    if (st == SlotState::none) *out = sub._position;
    if (st == SlotState::ok) *out = apply_part_pose(*pose, sub._position);
    return st;
}

}  // namespace dauntless::combat
