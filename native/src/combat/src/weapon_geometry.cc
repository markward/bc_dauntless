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

#include "dauntless/combat/py_math.h"

namespace dauntless::combat {

namespace {

[[noreturn]] void fall_back(const char* why) {
    throw std::invalid_argument(std::string("combat weapon_geometry: ") + why +
                                " -- answer in Python");
}

// ── Row access: a stale or unnamed handle falls back ────────────────────────

const ObjectRow& obj(const Mirror& m, int64_t h) {
    if (h < 0) fall_back("object handle is none or unrepresentable");
    const ObjectRow* r = m.object(h);
    if (!r) fall_back("object handle is stale, freed or not an Object");
    return *r;
}

const SubsystemRow& sub(const Mirror& m, int64_t h) {
    if (h < 0) fall_back("subsystem handle is none or unrepresentable");
    const SubsystemRow* r = m.subsystem(h);
    if (!r) fall_back("subsystem handle is stale, freed or not a Subsystem");
    return *r;
}

// An Object ref field's referent handle (checked), or -1 for None.
int64_t obj_ref(const Mirror& m, int64_t ref, const char* field) {
    if (ref == -1) return -1;
    if (ref == kRefUnrepresentable || !m.object(ref)) fall_back(field);
    return ref;
}

// The ObjectClass transform slot (GetWorldLocation / GetWorldRotation).
const TransformStore::Transform& xform(const Mirror& m, const ObjectRow& o) {
    if (o.xform_index < 0 || o.xform_gen < 0 ||
        o.xform_index > std::numeric_limits<uint32_t>::max() ||
        o.xform_gen > std::numeric_limits<uint32_t>::max())
        fall_back("object has no transform");
    const auto xi = static_cast<uint32_t>(o.xform_index);
    const auto xg = static_cast<uint32_t>(o.xform_gen);
    if (!m.store().valid(xi, xg)) fall_back("object transform is invalid");
    return m.store().at(xi);
}

Vec3 world_location(const Mirror& m, const ObjectRow& o) {
    const auto& t = xform(m, o);
    return {t.pos[0], t.pos[1], t.pos[2]};
}

// TGPoint3.MultMatrixLeft (engine/appc/math.py:86), r row-major m00..m22:
// v = M . v, each component m_i0*x + m_i1*y + m_i2*z, left-associative.
Vec3 mult_matrix_left(const double* r, const Vec3& v) {
    const double x = r[0] * v[0] + r[1] * v[1] + r[2] * v[2];
    const double y = r[3] * v[0] + r[4] * v[1] + r[5] * v[2];
    const double z = r[6] * v[0] + r[7] * v[1] + r[8] * v[2];
    return {x, y, z};
}

// TGPoint3.Length / Dot (math.py:34, :43).
double length(const Vec3& v) {
    return std::sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
}
double dot(const Vec3& a, const Vec3& b) {
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
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

// subsystems._subsystem_world_position (subsystems.py:62).
Vec3 mount_position(const Mirror& m, int64_t sub_h, int64_t ship_arg) {
    const SubsystemRow& s = sub(m, sub_h);
    int64_t ship = ship_arg == -1 ? -1 : (obj(m, ship_arg), ship_arg);
    if (ship == -1) ship = climb_to_ship(m, s);
    if (ship == -1) return {0.0, 0.0, 0.0};
    const ObjectRow& o = obj(m, ship);
    const auto& t = xform(m, o);
    // part_transform_point is the identity for an unrigged hull and for
    // every part at its NIF pose; a part off it is the Python's
    // (articulation.py:714).
    if (o.has_posed_parts) fall_back("ship has posed parts");
    const Vec3 offset = mult_matrix_left(t.rot, s._position);
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

// ── subsystems.py:94 target_offset_world (K1M F11) ──────────────────────────

Vec3 target_offset_world(const Mirror& m, int64_t target, const Vec3& offset) {
    const ObjectRow& t = obj(m, target);
    const auto& tr = xform(m, t);
    // part_transform_point and authored_mount_subsystem only matter on a rig.
    if (t.has_posed_parts) fall_back("target has posed parts");
    const double scale = t._scale;
    const Vec3 o0{offset[0] * scale, offset[1] * scale, offset[2] * scale};
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
    return target_offset_world(m, target, tb._target_offset);
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
