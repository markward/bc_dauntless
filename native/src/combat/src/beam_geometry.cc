// The native beam geometry -- see beam_geometry.h. Each function ports the
// Python function named in its comment (file:line), statement by statement:
// keep them in step. K2M = docs/reference/engine/native-combat/
// k2-beams-map.md. Inline literals are Python's, with the source line.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "dauntless/combat/beam_geometry.h"

#include <cmath>
#include <cstdint>

#include "dauntless/combat/part_pose.h"
#include "dauntless/combat/py_math.h"
#include "dauntless/combat/weapon_geometry.h"
#include "geometry_internal.h"

namespace dauntless::combat {

namespace {

using detail::dot;
using detail::fall_back;
using detail::mult_matrix_left;
using detail::obj;
using detail::sub;
using detail::world_location;
using detail::xform;

// ShipSubsystem.IsDisabled (subsystems.py:1201), reading _max_condition.
bool shield_is_disabled(const SubsystemRow& s) {
    if (s._max_condition <= 0.0) return false;
    const double threshold = s._disabled_percentage * s._max_condition;
    return s._condition <= threshold;
}

// ShipSubsystem.IsDestroyed (subsystems.py:1228).
bool shield_is_destroyed(const SubsystemRow& s) {
    if (s._destroyed) return true;
    if (s._max_condition > 0.0 && s._condition <= 0.0) return true;
    return false;
}

// CloakingSubsystem.CLOAK_CLOAKING / CLOAK_DECLOAKING (subsystems.py:3033).
constexpr int64_t kCloaking = 1, kDecloaking = 3;

}  // namespace

// ── host_loop.py:1046 _phaser_aim_point (K2M 1.2) ───────────────────────────

AimPoint phaser_aim_point(Mirror& m, int64_t ship, int64_t target,
                          bool use_memo) {
    const ObjectRow& s = obj(m, ship);
    // `getattr(type(ship), "is_using_target_offset")` is ShipClass's only.
    if (!s.is_ship_class) fall_back("firer is not a ShipClass");
    // ShipClass.is_using_target_offset (ships.py:1790).
    if (s._use_target_offset != 0 && s.manual_offset_set) {
        // GetTargetOffsetTG copies the manual offset (ships.py:1765), and
        // target_offset_world resolves its mount (`_RESOLVE`). Only a POSED
        // target reads it: a mount at the pick is posed, anything else is
        // a plain body point (fire control native only, M5).
        const ObjectRow& t = obj(m, target);
        const Vec3& off = s._manual_target_offset;
        int64_t mount = kNoMount;
        if (t.has_posed_parts) {
            mount = authored_mount_subsystem(m, t, off);
            if (mount == kMountUnknown)
                detail::fall_back_as<MountUnknown>(
                    "target offset mount unknown");
        }
        return {target_offset_world(m, target, off, mount), -1};
    }
    // ship.GetTargetSubsystem(): the lock is ship-wide (K2M 1.2).
    const int64_t lock = s._target_subsystem;
    if (lock != -1) {
        if (lock == kRefUnrepresentable || !m.subsystem(lock))
            fall_back("_target_subsystem");
        // ShipSubsystem.GetWorldLocation (subsystems.py:935): the lock's OWN
        // ship, with that ship's pose flag (mount_position checks it).
        const int64_t lock_ship = climb_to_ship_of(m, lock);
        if (lock_ship != -1)
            return {subsystem_world_position(m, lock, lock_ship, use_memo),
                    lock};
        return {sub(m, lock)._position, lock};  // GetPositionTG()
    }
    return {world_location(m, obj(m, target)), -1};
}

// ── subsystems.py:978 PhaserBank._strip_emit_position (K2M 1.3) ─────────────

Vec3 strip_emit_position(Mirror& m, int64_t bank, const Vec3& target_world,
                         bool use_memo) {
    // center = self._emitter_world_position() -> memo key (bank, None)
    const Vec3 center = subsystem_world_position(m, bank, -1, use_memo);
    const SubsystemRow& b = sub(m, bank);
    const double length = b._length;
    if (length <= 0.0) return center;  // a NaN length continues
    const int64_t ship = climb_to_ship_of(m, bank);
    if (ship == -1) return center;
    const double* rot = xform(m, obj(m, ship)).rot;

    // Body-frame basis rotated into world space (fields, not the part pose).
    const Vec3 f = mult_matrix_left(rot, b._direction);
    const Vec3 u = mult_matrix_left(rot, b._up);
    // F5: right = forward x up.
    const Vec3 r{f[1] * u[2] - f[2] * u[1], f[2] * u[0] - f[0] * u[2],
                 f[0] * u[1] - f[1] * u[0]};

    // F6
    const double dx = target_world[0] - center[0];
    const double dy = target_world[1] - center[1];
    const double dz = target_world[2] - center[2];
    const double fwd_proj = dx * f[0] + dy * f[1] + dz * f[2];
    const double right_proj = dx * r[0] + dy * r[1] + dz * r[2];

    // F7: the explicit zero test fixes signed zeros; NaN skips it.
    double yaw = (fwd_proj == 0.0 && right_proj == 0.0)
                     ? 0.0
                     : std::atan2(right_proj, fwd_proj);
    // F8: AUTHORED order, not sorted: max(lo, min(hi, yaw)).
    yaw = py_max(b._arc_width_lo, py_min(b._arc_width_hi, yaw));

    // F9
    const double c = py_cos(yaw), s = py_sin(yaw);
    const Vec3 e{f[0] * c + r[0] * s, f[1] * c + r[1] * s,
                 f[2] * c + r[2] * s};
    // F10
    return {center[0] + e[0] * length, center[1] + e[1] * length,
            center[2] + e[2] * length};
}

// ── weapon_subsystems.py:917 accumulate_dwell / take_dwell (K2M F13) ────────

DwellResult accumulate_dwell(const Mirror& m, int64_t bank, double dt) {
    const SubsystemRow& b = sub(m, bank);
    // IsBeamOn: `self._firing and self._beam_on_countdown <= 0.0`
    if (!(b._firing != 0 && b._beam_on_countdown <= 0.0))
        return {0.0, b._dwell, false};
    if (b._dwell > m.globals().BEAM_DWELL_FLUSH_S)
        return {b._dwell + dt, 0.0};  // the flush frame counts
    return {0.0, b._dwell + dt};
}

DwellResult take_dwell(const Mirror& m, int64_t bank) {
    return {sub(m, bank)._dwell, 0.0};
}

// ── combat.py:23 ray_sphere_entry (K2M F18) ─────────────────────────────────

SphereEntry ray_sphere_entry(const Vec3& origin, const Vec3& dir,
                             double max_dist, const Vec3& center,
                             double radius) {
    if (radius <= 0.0) return {};
    const double ox = origin[0] - center[0];
    const double oy = origin[1] - center[1];
    const double oz = origin[2] - center[2];
    const double b = ox * dir[0] + oy * dir[1] + oz * dir[2];
    const double c = ox * ox + oy * oy + oz * oz - radius * radius;
    if (c <= 0.0) return {SphereEntry::Kind::Origin, origin};
    if (b >= 0.0) return {};
    const double disc = b * b - c;
    if (disc < 0.0) return {};
    const double t_enter = -b - py_pow(disc, 0.5);
    if (t_enter < 0.0 || t_enter > max_dist) return {};
    return {SphereEntry::Kind::Point,
            {origin[0] + dir[0] * t_enter, origin[1] + dir[1] * t_enter,
             origin[2] + dir[2] * t_enter}};
}

// ── collisions.py:117 world_radius ──────────────────────────────────────────

double world_radius(const Mirror& m, int64_t object) {
    const ObjectRow& o = obj(m, object);
    const double r = o._radius;
    const double s = o._scale;
    return (s > 0.0 && std::isfinite(s)) ? r * s : r;
}

// ── combat.py:343 shields_block (K2M 1.5) ───────────────────────────────────

bool shields_block(const Mirror& m, int64_t target, bool npc_shields_off,
                   int64_t player) {
    const ObjectRow& t = obj(m, target);
    // Anything else goes through TGObject.__getattr__ stubs.
    if (!t.is_ship_class || !t.has_real_get_shields)
        fall_back("target is not a ShipClass with a real GetShields");
    const int64_t sref = t._shield_subsystem;  // ship.GetShields()
    if (sref == -1) return false;
    if (sref == kRefUnrepresentable || !m.subsystem(sref))
        fall_back("_shield_subsystem");
    const SubsystemRow& shields = sub(m, sref);
    if (!shields.has_shields) return false;   // HasShields
    if (!shields._is_on) return false;        // IsOn
    if (shield_is_disabled(shields)) return false;
    if (shield_is_destroyed(shields)) return false;
    // cloak_shields_suspended (combat.py:580)
    if (!t.has_cloak_getter) fall_back("target has no real GetCloakingSubsystem");
    const int64_t cref = t._cloaking_subsystem;
    if (cref != -1) {
        if (cref == kRefUnrepresentable || !m.subsystem(cref))
            fall_back("_cloaking_subsystem");
        const int64_t st = sub(m, cref)._cloak_state;
        if (st == kCloaking || st == kDecloaking) return false;
    }
    if (npc_shields_off) {
        if (player == -1 || target != player) return false;
    }
    return true;
}

// ── combat.py:403 shield_bubble_entry (K2M F15-F16) ─────────────────────────

std::optional<Vec3> shield_bubble_entry(const Mirror& m, int64_t target,
                                        const Vec3& origin, const Vec3& dir,
                                        double max_dist) {
    const ObjectRow& t = obj(m, target);
    // _hull_box_for (combat.py:308): no box, or a degenerate raw extent.
    if (!t.hull_box_set) return std::nullopt;
    const Vec3& hc = t._shield_hull_box_center;
    const Vec3& hh = t._shield_hull_box_half;
    if (hh[0] <= 0.0 || hh[1] <= 0.0 || hh[2] <= 0.0) return std::nullopt;
    double scale = t._scale;
    if (scale <= 0.0) scale = 1.0;  // NaN passes
    const double cx = hc[0] * scale, cy = hc[1] * scale, cz = hc[2] * scale;
    const double hx = hh[0] * scale, hy = hh[1] * scale, hz = hh[2] * scale;
    const double k = m.globals().SHIELD_ELLIPSOID_AXIS_SCALE;
    const double ax = hx * k, ay = hy * k, az = hz * k;
    // Python's float division raises ZeroDivisionError on a zero axis.
    if (ax == 0.0 || ay == 0.0 || az == 0.0)
        fall_back("zero bubble semi-axis (Python raises)");

    // _body_frame_delta (F15)
    const auto& tr = xform(m, t);
    const double* R = tr.rot;
    const double dxw = origin[0] - tr.pos[0];
    const double dyw = origin[1] - tr.pos[1];
    const double dzw = origin[2] - tr.pos[2];
    const double bx = dxw * R[0] + dyw * R[3] + dzw * R[6];
    const double by = dxw * R[1] + dyw * R[4] + dzw * R[7];
    const double bz = dxw * R[2] + dyw * R[5] + dzw * R[8];
    const double o0 = (bx - cx) / ax, o1 = (by - cy) / ay, o2 = (bz - cz) / az;

    // The direction, into the body frame and onto the unit sphere.
    const double db0 = dir[0] * R[0] + dir[1] * R[3] + dir[2] * R[6];
    const double db1 = dir[0] * R[1] + dir[1] * R[4] + dir[2] * R[7];
    const double db2 = dir[0] * R[2] + dir[1] * R[5] + dir[2] * R[8];
    double d0 = db0 / ax, d1 = db1 / ay, d2 = db2 / az;
    const double d_len = py_pow(d0 * d0 + d1 * d1 + d2 * d2, 0.5);
    if (d_len < 1e-12) return std::nullopt;  // combat.py:453 (NaN passes)
    d0 = d0 / d_len;
    d1 = d1 / d_len;
    d2 = d2 / d_len;

    const double b = o0 * d0 + o1 * d1 + o2 * d2;
    const double c = o0 * o0 + o1 * o1 + o2 * o2 - 1.0;  // combat.py:459
    if (c <= 0.0) return std::nullopt;  // origin inside the bubble
    if (b >= 0.0) return std::nullopt;  // pointing away
    const double disc = b * b - c;
    if (disc < 0.0) return std::nullopt;  // misses
    const double tt = -b - py_pow(disc, 0.5);
    if (tt < 0.0 || tt > max_dist * d_len) return std::nullopt;

    // Back out: unit sphere -> ellipsoid -> body -> world.
    const Vec3 p0{(o0 + d0 * tt) * ax + cx, (o1 + d1 * tt) * ay + cy,
                  (o2 + d2 * tt) * az + cz};
    const Vec3 p = mult_matrix_left(R, p0);
    return Vec3{p[0] + tr.pos[0], p[1] + tr.pos[1], p[2] + tr.pos[2]};
}

}  // namespace dauntless::combat
