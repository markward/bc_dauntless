// The native weapon geometry -- see weapon_geometry.h. Each function ports the
// Python function of the same name (file:line in its comment), statement by
// statement: keep them in step. K1M = docs/reference/engine/native-combat/
// k1-fire-control-map.md.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "dauntless/combat/weapon_geometry.h"

#include <cmath>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <string>
#include <unordered_set>

#include "dauntless/combat/part_pose.h"
#include "dauntless/combat/py_math.h"
#include "geometry_internal.h"

namespace dauntless::combat {

namespace {

using detail::dot;
using detail::fall_back;
using detail::fall_back_as;
using detail::length;
using detail::mult_matrix_left;
using detail::obj;
using detail::sub;
using detail::world_location;
using detail::xform;

// An Object ref field's referent handle (checked), or -1 for None.
int64_t obj_ref(const Mirror& m, int64_t ref, const char* field) {
    if (ref == -1) return -1;
    if (ref == kRefUnrepresentable || !m.object(ref)) fall_back(field);
    return ref;
}

Vec3 minus(const Vec3& a, const Vec3& b) {  // TGPoint3.__sub__
    return {a[0] - b[0], a[1] - b[1], a[2] - b[2]};
}

// `(x*x + y*y + z*z) ** 0.5` -- py_pow, NOT sqrt (K1M F7; py_math.h says why).
double pow_half_length(double x, double y, double z) {
    return py_pow(x * x + y * y + z * z, 0.5);
}

// ObjectClass.GetContainingSet (objects.py:329): the set handle or -1.
int64_t containing_set(const Mirror& m, const ObjectRow& o) {
    const int64_t h = o._containing_set;
    if (h == -1) return -1;
    if (h == kRefUnrepresentable || !m.set(h)) fall_back("_containing_set");
    return h;
}

// ShipSubsystem._climb_to_ship (subsystems.py:952): an Object handle or -1.
int64_t climb_to_ship(const Mirror& m, const SubsystemRow& s) {
    if (s._parent_ship != -1) return obj_ref(m, s._parent_ship, "_parent_ship");
    // Each ancestor's `_parent_ship` FIELD; `seen` bounds a cyclic chain.
    std::unordered_set<int64_t> seen;
    int64_t node = s._parent_subsystem;
    while (node != -1 && !seen.count(node)) {
        if (node == kRefUnrepresentable) fall_back("_parent_subsystem");
        seen.insert(node);
        const SubsystemRow* n = m.subsystem(node);
        if (!n) fall_back("_parent_subsystem is gone");
        if (n->_parent_ship != -1)
            return obj_ref(m, n->_parent_ship, "_parent_ship");
        node = n->_parent_subsystem;
    }
    return -1;
}

// A part slot is resolved against the subsystem's OWN ship (Python's
// resolve_part_slots walks that ship): read on another ship it would index
// the wrong pose table. Python resolves the part on `ship`'s leaf, so that
// is Python's -- part_stale. ShipClass.SetHull attaches the hull, so
// climb_to_ship returns its owner and the owner check applies to it too.
void check_slot_owner(const Mirror& m, const SubsystemRow& s, int64_t ship) {
    const int64_t owner = climb_to_ship(m, s);
    if (owner == -1 || owner != ship) fall_back_as<PartStale>("part_stale");
}

// subsystems._subsystem_world_position (subsystems.py:62; MAP P3).
Vec3 mount_position(const Mirror& m, int64_t sub_h, int64_t ship_arg) {
    const SubsystemRow& s = sub(m, sub_h);
    int64_t ship = ship_arg == -1 ? -1 : (obj(m, ship_arg), ship_arg);
    if (ship == -1) ship = climb_to_ship(m, s);
    if (ship == -1) return {0.0, 0.0, 0.0};
    const ObjectRow& o = obj(m, ship);
    const auto& t = xform(m, o);
    // part_transform_point (articulation.py:724) BEFORE the rotation: the
    // pushed slot names the part, the point itself when there is none or it
    // is at identity / detached. No slot is read while the ship is unposed.
    Vec3 local = s._position;
    if (o.has_posed_parts) {
        if (ship_arg != -1) check_slot_owner(m, s, ship);
        if (posed_local(m, o, s, &local) == SlotState::stale)
            fall_back_as<PartStale>("part_stale");
    }
    const Vec3 offset = mult_matrix_left(t.rot, local);
    return {t.pos[0] + offset[0], t.pos[1] + offset[1], t.pos[2] + offset[2]};
}

}  // namespace

// ShipSubsystem._climb_to_ship for a Subsystem handle (public face of the
// helper above, shared with fire_gates.cc).
int64_t climb_to_ship_of(const Mirror& m, int64_t subsystem) {
    return climb_to_ship(m, sub(m, subsystem));
}

// ── subsystems.py:32 subsystem_world_position ───────────────────────────────

Vec3 subsystem_world_position(Mirror& m, int64_t sub_h, int64_t ship_arg,
                              bool use_memo) {
    if (use_memo) {
        auto& memo = m.sensor_state().mounts;
        const HandlePair key{sub_h, ship_arg};
        auto it = memo.find(key);
        if (it != memo.end()) return it->second;
        const Vec3 p = mount_position(m, sub_h, ship_arg);
        memo[key] = p;
        return p;
    }
    return mount_position(m, sub_h, ship_arg);
}

// ── weapon_subsystems.py:80 _resolve_aim_world ──────────────────────────────

Vec3 _resolve_aim_world(const Mirror& m, int64_t ship, int64_t target) {
    if (ship != -1 && target != -1) {
        const Vec3 ship_pos = world_location(m, obj(m, ship));
        const Vec3 target_pos = world_location(m, obj(m, target));
        const double dx = target_pos[0] - ship_pos[0];
        const double dy = target_pos[1] - ship_pos[1];
        const double dz = target_pos[2] - ship_pos[2];
        const double len = pow_half_length(dx, dy, dz);
        if (len > 1e-6) return {dx / len, dy / len, dz / len};  // weapon_subsystems.py:91
    }
    // Fallback: the ship's body +Y axis rotated into world.
    Vec3 fwd{0.0, 1.0, 0.0};
    if (ship != -1) fwd = mult_matrix_left(xform(m, obj(m, ship)).rot, fwd);
    const double len = pow_half_length(fwd[0], fwd[1], fwd[2]);
    if (len > 1e-6) return {fwd[0] / len, fwd[1] / len, fwd[2] / len};  // weapon_subsystems.py:100
    return {0.0, 1.0, 0.0};
}

// ── weapon_subsystems.py:105 _resolve_bank_aim_world ────────────────────────

Vec3 _resolve_bank_aim_world(Mirror& m, int64_t bank, int64_t target,
                             bool use_memo) {
    if (bank == -1 || target == -1) return _resolve_aim_world(m, -1, target);
    const Vec3 origin = subsystem_world_position(m, bank, -1, use_memo);
    const Vec3 target_pos = world_location(m, obj(m, target));
    const double dx = target_pos[0] - origin[0];
    const double dy = target_pos[1] - origin[1];
    const double dz = target_pos[2] - origin[2];
    const double len = pow_half_length(dx, dy, dz);
    if (len > 1e-6) return {dx / len, dy / len, dz / len};  // weapon_subsystems.py:130
    // Degenerate: the bank coincides with the target; ship-forward.
    const int64_t ship = climb_to_ship(m, sub(m, bank));
    return _resolve_aim_world(m, ship, -1);
}

// weapon_subsystems.py:105 _resolve_bank_aim_world, the target a world point
// (the lines after `target_pos = target.GetWorldLocation()`).
Vec3 _resolve_bank_aim_world_at(Mirror& m, int64_t bank, const Vec3& target_pos,
                                bool use_memo) {
    const Vec3 origin = subsystem_world_position(m, bank, -1, use_memo);
    const double dx = target_pos[0] - origin[0];
    const double dy = target_pos[1] - origin[1];
    const double dz = target_pos[2] - origin[2];
    const double len = pow_half_length(dx, dy, dz);
    if (len > 1e-6) return {dx / len, dy / len, dz / len};  // weapon_subsystems.py:130
    const int64_t ship = climb_to_ship(m, sub(m, bank));
    return _resolve_aim_world(m, ship, -1);
}

// ── weapon_subsystems.py:167 _emitter_in_arc (K1M F9) ───────────────────────

bool _emitter_in_arc(const Mirror& m, int64_t emitter, int64_t ship,
                     const Vec3& aim) {
    const SubsystemRow& e = sub(m, emitter);
    const double* rot = nullptr;
    if (ship != -1) rot = xform(m, obj(m, ship)).rot;

    // _emitter_world_direction
    Vec3 world_dir = e._direction;
    if (rot) world_dir = mult_matrix_left(rot, world_dir);

    if (!e._arc_set) return dot(world_dir, aim) > 0.0;

    Vec3 world_up = e._up;
    if (rot) world_up = mult_matrix_left(rot, world_up);

    // Right = world_forward x world_up (the rotated vectors).
    const Vec3 world_right{
        world_dir[1] * world_up[2] - world_dir[2] * world_up[1],
        world_dir[2] * world_up[0] - world_dir[0] * world_up[2],
        world_dir[0] * world_up[1] - world_dir[1] * world_up[0]};

    const double fwd_dot = dot(world_dir, aim);
    const double right_dot = dot(world_right, aim);
    const double up_dot = dot(world_up, aim);

    const double yaw = std::atan2(right_dot, fwd_dot);
    // max(-1.0, min(1.0, up_dot)): NaN becomes 1.0.
    const double pitch = std::asin(py_max(-1.0, py_min(1.0, up_dot)));

    // sorted(arc): swap only if b < a.
    const double a = e._arc_width_lo, b = e._arc_width_hi;
    const double yaw_lo = (b < a) ? b : a, yaw_hi = (b < a) ? a : b;
    const double c = e._arc_height_lo, d = e._arc_height_hi;
    const double pitch_lo = (d < c) ? d : c, pitch_hi = (d < c) ? c : d;
    return (yaw_lo <= yaw && yaw <= yaw_hi) &&
           (pitch_lo <= pitch && pitch <= pitch_hi);
}

// ── weapon_subsystems.py:483 _emitter_forward_world (skew=False) ────────────

Vec3 _emitter_forward_world(const Mirror& m, int64_t emitter, int64_t ship) {
    Vec3 local = sub(m, emitter)._direction;
    if (ship != -1) local = mult_matrix_left(xform(m, obj(m, ship)).rot, local);
    return local;
}

// ── subsystems.py target_offset_world (K1M F11; native-only fire M5) ──────

Vec3 target_offset_world(const Mirror& m, int64_t target, const Vec3& offset,
                         int64_t mount_sub) {
    const ObjectRow& t = obj(m, target);
    // An invalid transform falls back before any slot is read.
    xform(m, t);
    // Only an offset that IS its mount's own point is carried by the
    // mount's part (part_transform_point BEFORE the scale, MAP P4), and
    // only on a posed target (unposed: the point itself, no slot read). No
    // mount, or an offset merely within 1e-5 of one (C `==` per axis: -0.0
    // matches 0.0, a NaN never matches; M8.5), is a plain body point:
    // Python's _is_own_mount. CHANGE BOTH.
    Vec3 p = offset;
    if (t.has_posed_parts && mount_sub != kNoMount) {
        if (mount_sub == kRefUnrepresentable)
            fall_back("mount subsystem is unnamed");
        const SubsystemRow& ms = sub(m, mount_sub);
        const Vec3& k = ms._position;
        if (offset[0] == k[0] && offset[1] == k[1] && offset[2] == k[2]) {
            check_slot_owner(m, ms, target);
            const PartPose* pose = nullptr;
            const SlotState st = slot_pose(m, t, ms, &pose);
            if (st == SlotState::stale) fall_back_as<PartStale>("part_stale");
            // The pose carries the OFFSET (Python's `point`), not
            // `_position`: -0.0 == 0.0 matched above.
            if (st == SlotState::ok) p = apply_part_pose(*pose, offset);
        }
    }
    return body_point_world(m, target, p);
}

// ── subsystems.py body_point_world (P4's tail) ──────────────────────────────

Vec3 body_point_world(const Mirror& m, int64_t target, const Vec3& p) {
    const ObjectRow& t = obj(m, target);
    const auto& tr = xform(m, t);
    const double scale = t._scale;
    const Vec3 o0{p[0] * scale, p[1] * scale, p[2] * scale};
    const Vec3 o = mult_matrix_left(tr.rot, o0);
    return {tr.pos[0] + o[0], tr.pos[1] + o[1], tr.pos[2] + o[2]};
}

// ── weapon_subsystems.py:3017 _resolve_torpedo_aim_point ────────────────────

std::optional<Vec3> _resolve_torpedo_aim_point(const Mirror& m, int64_t tube,
                                               int64_t target) {
    if (target == -1) return std::nullopt;
    const ObjectRow& t = obj(m, target);
    // IsDead on a class without one is a stub that records telemetry.
    if (!t.has_real_is_dead) fall_back("target has no real IsDead");
    if (t._dead) return std::nullopt;
    const SubsystemRow& tb = sub(m, tube);
    if (!tb.target_offset_set) return world_location(m, t);
    // target_offset_world(target, offset): mount_sub=_RESOLVE, i.e.
    // part_severance.authored_mount_subsystem(target, offset). Only a POSED
    // target reads the mount (an unposed one is the offset whatever it is),
    // so only there is it looked up: the first mount at the offset in
    // _iter_subsystems order (posed-parts spec §4.4). The mirror cannot
    // tell -> Python's; none -> a plain body point (M5).
    int64_t mount = kNoMount;
    if (t.has_posed_parts) {
        mount = authored_mount_subsystem(m, t, tb._target_offset);
        if (mount == kMountUnknown)
            fall_back_as<MountUnknown>("target offset mount unknown");
    }
    return target_offset_world(m, target, tb._target_offset, mount);
}

// ── weapon_subsystems.py:3033 _in_torpedo_cone (K1M F12) ────────────────────

bool _in_torpedo_cone(Mirror& m, int64_t tube, int64_t ship, const Vec3& aim,
                      bool use_memo) {
    const Vec3 mount = subsystem_world_position(m, tube, -1, use_memo);
    const Vec3 to_aim = minus(aim, mount);
    if (length(to_aim) < 1e-6) return false;  // weapon_subsystems.py:3040
    const SubsystemRow& tb = sub(m, tube);
    const Vec3 d = tb._direction;
    const Vec3 r = tb._right;
    // up = dir x right, crossed in the LOCAL frame and rotated after.
    const Vec3 u{d[1] * r[2] - d[2] * r[1], d[2] * r[0] - d[0] * r[2],
                 d[0] * r[1] - d[1] * r[0]};
    Vec3 b0 = d, b1 = r, b2 = u;
    if (ship != -1) {
        const double* rot = xform(m, obj(m, ship)).rot;
        b0 = mult_matrix_left(rot, b0);
        b1 = mult_matrix_left(rot, b1);
        b2 = mult_matrix_left(rot, b2);
    }
    const double fwd = dot(b0, to_aim);
    if (fwd <= 0.0) return false;
    const double yaw = std::atan2(std::fabs(dot(b1, to_aim)), fwd);
    const double pitch = std::atan2(std::fabs(dot(b2, to_aim)), fwd);
    const double cone = m.globals().TORPEDO_CONE_HALF_ANGLE;
    return yaw <= cone && pitch <= cone;
}

// ── weapon_subsystems.py:509 _solve_pulse_launch_direction (K1M F13) ────────

std::optional<Vec3> _solve_pulse_launch_direction(Mirror& m, int64_t cannon,
                                                  int64_t ship, int64_t target,
                                                  bool use_memo) {
    const SubsystemRow& c = sub(m, cannon);
    if (!c.module_ok) fall_back("pulse projectile module did not resolve");
    const std::optional<Vec3> aim_opt =
        _resolve_torpedo_aim_point(m, cannon, target);
    if (!aim_opt) return std::nullopt;
    const Vec3 aim = *aim_opt;
    const Vec3 muzzle = subsystem_world_position(m, cannon, -1, use_memo);
    const Vec3 to_aim = minus(aim, muzzle);
    const double dist = length(to_aim);
    if (dist < 1e-6) return std::nullopt;  // weapon_subsystems.py:540
    const Vec3 u{to_aim[0] / dist, to_aim[1] / dist, to_aim[2] / dist};

    // _vec: GetVelocityTG of a present object; (0, 0, 0) for none.
    const Vec3 zero{0.0, 0.0, 0.0};
    const Vec3 ship_vel = ship == -1 ? zero : obj(m, ship)._velocity;
    const Vec3 tgt_vel = obj(m, target)._velocity;
    const Vec3 tgt_acc = zero;  // ObjectClass.GetAccelerationTG (objects.py:649)

    const double launch_speed = c.launch_speed;
    const double v_eff = launch_speed + dot(minus(ship_vel, tgt_vel), u);
    if (v_eff <= 0.0) return std::nullopt;
    const double t = dist / v_eff;
    if (t <= 0.0) return std::nullopt;
    const double lifetime = c.lifetime;
    if (t > lifetime) return std::nullopt;
    // aim + tv*t + 0.5*ta*t*t - sv*t, left-associative.
    Vec3 pred;
    for (int i = 0; i < 3; ++i)
        pred[i] = aim[i] + tgt_vel[i] * t + 0.5 * tgt_acc[i] * t * t -
                  ship_vel[i] * t;
    const Vec3 launch = minus(pred, muzzle);
    const double n = length(launch);
    if (n < 1e-6 ||  // weapon_subsystems.py:570
        n > m.globals().PULSE_RANGE_GATE_SECONDS * v_eff)
        return std::nullopt;
    return Vec3{launch[0] / n, launch[1] / n, launch[2] / n};
}

// ── weapon_subsystems.py:2232 _target_within_range_gu (K1M F2) ──────────────

bool _target_within_range_gu(const Mirror& m, int64_t ship, int64_t target,
                             double max_range_gu) {
    if (ship == -1 || target == -1) return false;
    const ObjectRow& s = obj(m, ship);
    const ObjectRow& t = obj(m, target);
    // _same_set (weapon_subsystems.py:2223): identity of the containing sets.
    const int64_t set_a = containing_set(m, s);
    if (set_a == -1 || set_a != containing_set(m, t)) return false;
    const Vec3 sp = world_location(m, s);
    const Vec3 tp = world_location(m, t);
    const double dx = tp[0] - sp[0], dy = tp[1] - sp[1], dz = tp[2] - sp[2];
    const double dist_sq = dx * dx + dy * dy + dz * dz;
    return dist_sq <= max_range_gu * max_range_gu;
}

}  // namespace dauntless::combat
