// The posed-parts arithmetic -- see part_pose.h. MAP = docs/reference/engine/
// native-combat/posed-parts-map.md.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "dauntless/combat/part_pose.h"

#include <cmath>

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

// part_severance.authored_mount_subsystem (PS:502-514), its operands and
// order exactly: `abs(mount[i] - point[i]) <= eps` per axis, x then y then z
// (Python's `and` short-circuits; no side effect, so the order is moot).
int64_t authored_mount_subsystem(const Mirror& m, const ObjectRow& target,
                                 const Vec3& offset) {
    // Only ShipClass rows get a mount order (native_combat.push_mount_order).
    if (!target.is_ship_class) return kMountUnknown;
    constexpr double eps = 1e-5;
    for (const int64_t h : target.mount_order) {
        // kRefUnrepresentable or a freed row: it might have matched.
        const SubsystemRow* sub = m.subsystem(h);
        if (sub == nullptr) return kMountUnknown;
        const Vec3& mount = sub->_position;
        if (std::fabs(mount[0] - offset[0]) <= eps &&
            std::fabs(mount[1] - offset[1]) <= eps &&
            std::fabs(mount[2] - offset[2]) <= eps)
            return h;
    }
    return kNoMount;
}

}  // namespace dauntless::combat
