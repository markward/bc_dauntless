// The native projectile geometry -- see projectile_geometry.h. Each function
// ports the Python function named in its comment (file:line), statement by
// statement: keep them in step. K3M = docs/reference/engine/native-combat/
// k3-k4-map.md. Inline literals are Python's, with the source line.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "dauntless/combat/projectile_geometry.h"

#include <cmath>
#include <cstdint>
#include <iterator>
#include <limits>
#include <stdexcept>

#include "dauntless/combat/beam_geometry.h"
#include "dauntless/combat/part_pose.h"
#include "dauntless/combat/py_math.h"
#include "dauntless/combat/sensor_detect.h"
#include "dauntless/combat/weapon_geometry.h"
#include "geometry_internal.h"

namespace dauntless::combat {

namespace {

using detail::dot;
using detail::fall_back;
using detail::length;
using detail::obj;
using detail::shifted;
using detail::world_location;

using St = GuideResult::Status;

constexpr uint32_t bit(TorpField f) { return 1u << static_cast<int>(f); }

// Every torpedo field _guide reads (all but _ttl, which only update_all's
// TTL test reads). An unrepresentable one is Python's whole _guide.
constexpr uint32_t kGuideReads =
    bit(TorpField::_age) | bit(TorpField::_guidance_lifetime) |
    bit(TorpField::_guidance_initial) | bit(TorpField::_max_angular_accel) |
    bit(TorpField::_velocity) | bit(TorpField::_target_offset) |
    bit(TorpField::_last_seen_target_pos) | bit(TorpField::_last_target_vel) |
    bit(TorpField::_target_ship) | bit(TorpField::_source_ship) |
    bit(TorpField::_containing_set) | bit(TorpField::_mount_key);

GuideResult need_guide(const char* why) {
    GuideResult r;
    r.status = St::need_guide;
    r.why = why;
    return r;
}

GuideResult need_frame(int64_t set) {
    GuideResult r;
    r.status = St::need_frame;
    r.frame_set = set;
    return r;
}

void write(GuideResult& r, GuideField f, const Vec3& v) {
    r.writes[static_cast<size_t>(r.n_writes++)] = {f, v};
}

// torpedo.GetTranslate(): the torpedo's own TransformStore slot. False for
// a slot that is not live (Python would read whatever the store holds).
bool torp_translate(const Mirror& m, const TorpedoRow& row, Vec3& out) {
    if (row.xform_index < 0 || row.xform_gen < 0 ||
        row.xform_index > std::numeric_limits<uint32_t>::max() ||
        row.xform_gen > std::numeric_limits<uint32_t>::max())
        return false;
    const auto xi = static_cast<uint32_t>(row.xform_index);
    const auto xg = static_cast<uint32_t>(row.xform_gen);
    if (!m.store().valid(xi, xg)) return false;
    const auto& t = m.store().at(xi);
    out = {t.pos[0], t.pos[1], t.pos[2]};
    return true;
}

// The OffsetStatus `missing` names no set: the first of the two without a
// frame-table entry is the one to ask for (offset_between looks up `a`
// first).
int64_t missing_set(const StepScan& frames, int64_t a, int64_t b) {
    return frames.frame(a) == nullptr ? a : b;
}

// projectiles.py:1154-1176, from `to_aim = aim - torp_pos` to the
// `_velocity` write: shared by the visible and the last-seen branch.
void turn(const TorpedoRow& row, double dt, double speed, const Vec3& torp_pos,
          const Vec3& aim, GuideResult& r) {
    // G5
    const Vec3 to_aim{aim[0] - torp_pos[0], aim[1] - torp_pos[1],
                      aim[2] - torp_pos[2]};
    const double dist = length(to_aim);
    if (dist < 1e-6) return;  // projectiles.py:1156 (NaN continues)
    // G6
    const Vec3 desired{to_aim[0] / dist, to_aim[1] / dist, to_aim[2] / dist};
    const Vec3& v = row.vel;
    const Vec3 current{v[0] / speed, v[1] / speed, v[2] / speed};
    // G7 (projectiles.py:1162-1164): max(0.0, ...) -> 0.0 for NaN; a NaN
    // initial reads 1.0 (`> 1e-9` is False).
    const double remaining =
        py_max(0.0, row.guidance_lifetime - row.age);
    const double initial =
        row.guidance_initial > 1e-9 ? row.guidance_initial : 1.0;
    const double max_step =
        ((remaining / initial) * row.max_angular_accel) * dt;
    // G8 (projectiles.py:1165): a NaN dot clamps to 1.0 (min(1.0, NaN) is
    // 1.0).
    const double cos_theta = py_max(-1.0, py_min(1.0, dot(current, desired)));
    const double theta = std::acos(cos_theta);
    Vec3 new_dir;
    if (theta <= max_step || theta < 1e-6) {  // projectiles.py:1167
        new_dir = desired;
    } else {
        // G9: three libm sin calls, each alone (py_math.h).
        const double sin_theta = py_sin(theta);
        const double a = py_sin(theta - max_step) / sin_theta;
        const double b = py_sin(max_step) / sin_theta;
        new_dir = {current[0] * a + desired[0] * b,
                   current[1] * a + desired[1] * b,
                   current[2] * a + desired[2] * b};
    }
    write(r, GuideField::velocity,
          {new_dir[0] * speed, new_dir[1] * speed, new_dir[2] * speed});
}

}  // namespace

// ── combat.py:916 bubble_bound_radius (K3M B1) ──────────────────────────────

double bubble_bound_radius(const Mirror& m, int64_t ship) {
    const ObjectRow& o = obj(m, ship);
    // world_radius's DebrisChunk rule and a stub GetScale are not mirrored:
    // only a ShipClass row (what the step scan admits) is answered.
    if (!o.is_ship_class) fall_back("bound of an object that is not a ShipClass");
    // try: radius = world_radius(ship) (= GetRadius(), base x guarded scale)
    // -- a row exists only while the base radius and scale read as numbers,
    // so the `except` (inf) is never taken.
    const double radius = world_radius(m, ship);
    const double k = m.globals().SHIELD_ELLIPSOID_AXIS_SCALE;

    // _hull_box_for (combat.py:308): no box, or a degenerate raw extent.
    const Vec3& hh = o._shield_hull_box_half;
    if (!o.hull_box_set || hh[0] <= 0.0 || hh[1] <= 0.0 || hh[2] <= 0.0)
        return radius * (1.0 + k);
    double scale = o._scale;
    if (scale <= 0.0) scale = 1.0;  // NaN passes
    const Vec3& hc = o._shield_hull_box_center;
    const double cx = hc[0] * scale, cy = hc[1] * scale, cz = hc[2] * scale;
    const double hx = hh[0] * scale, hy = hh[1] * scale, hz = hh[2] * scale;

    const double centre_len = py_pow(cx * cx + cy * cy + cz * cz, 0.5);
    // max(a, b, c) is a left fold of Python's max.
    const double max_semi =
        py_max(py_max(std::fabs(hx), std::fabs(hy)), std::fabs(hz)) * k;
    return py_max(radius, centre_len + max_semi);
}

// ── combat.py:14 sphere_hit (K3M A8) ────────────────────────────────────────

bool sphere_hit(const Vec3& p, const Vec3& c, double r) {
    const double dx = p[0] - c[0];
    const double dy = p[1] - c[1];
    const double dz = p[2] - c[2];
    return (dx * dx + dy * dy + dz * dz) <= r * r;
}

// ── projectiles.py:912-930 update_all's advance (K3M A1-A6) ─────────────────

Advance advance_torpedo(const Vec3& prev, const Vec3& vel, double dt,
                        double age, double ttl) {
    Advance a;
    // A1/A2: `prev_pos + t._velocity * dt` builds the product first.
    a.cur = {prev[0] + vel[0] * dt, prev[1] + vel[1] * dt,
             prev[2] + vel[2] * dt};
    // A6
    a.age = age + dt;
    a.expired = a.age >= ttl;  // NaN age or ttl: never
    if (a.expired) return a;
    // A3: cur - prev, NOT v * dt (they round differently).
    a.seg = {a.cur[0] - prev[0], a.cur[1] - prev[1], a.cur[2] - prev[2]};
    a.seg_len = length(a.seg);  // A4
    // A5: projectiles.py:930 (NaN: no aim).
    if (a.seg_len > 1e-9)
        a.aim_unit = Vec3{a.seg[0] / a.seg_len, a.seg[1] / a.seg_len,
                          a.seg[2] / a.seg_len};
    return a;
}

// ── projectiles.py:1065 _steer_point (K3M G11/G12) ──────────────────────────

Vec3 steer_point_native(const Mirror& m, int64_t target,
                        const std::optional<Vec3>& offset, int64_t mount_sub,
                        const Vec3& off) {
    const ObjectRow& t = obj(m, target);
    if (!offset) {
        // G12: TGPoint3(pos) then _shifted(..., off).
        return shifted(world_location(m, t), off);
    }
    // G11: target_offset_world(target, offset, key[4]). At an unposed
    // target part_transform_point returns the point whatever the mount, but
    // a mount the mirror cannot name is Python's. At a posed one the mount's
    // part slot carries the offset (target_offset_world: only when the
    // offset is the mount's own point and the slot is current); a picked
    // spot (no mount) or an offset off its mount is a plain body point for
    // the whole flight (fire control native only, M5, M8.5).
    if (mount_sub == kRefUnrepresentable) fall_back("mount subsystem is unnamed");
    if (mount_sub >= 0 && !m.subsystem(mount_sub))
        fall_back("mount subsystem is stale");
    return shifted(target_offset_world(m, target, *offset, mount_sub), off);
}

const char* steer_why_name(SteerWhy w) {
    static constexpr const char* kNames[] = {
        "unattributed", "mount_unrepresentable", "posed_target",
        "mount_stale",  "part_stale",            "geometry"};
    static_assert(std::size(kNames) == static_cast<size_t>(SteerWhy::kCount));
    const auto i = static_cast<size_t>(w);
    return i < std::size(kNames) ? kNames[i] : "?";
}

// A need_steer_point with its reason.
static GuideResult steer_ask(GuideResult ask, SteerWhy why) {
    ask.steer_why = why;
    return ask;
}

// ── projectiles.py:1103 _guide (K3M A1.2, G1-G10) ───────────────────────────

GuideResult guide_torpedo(Mirror& m, const TorpedoRow& row, double dt,
                          const StepScan& frames, bool use_memo,
                          const GuideClocks& clocks) {
    // target = torpedo._target_ship; if target is None: return
    const int64_t target = m.torpedo_ref(row, TorpField::_target_ship);
    if (target == -1) return {};
    if (row.unrepresentable & kGuideReads)
        return need_guide("unrepresentable torpedo field");
    if (target < 0) return need_guide("_target_ship");
    const ObjectRow& tr = *m.object(target);  // torpedo_ref: live

    // off = offset_between(containing_set(torpedo), containing_set(target))
    const int64_t tset = m.torpedo_ref(row, TorpField::_containing_set);
    const int64_t gset = tr._containing_set;
    Vec3 off{0.0, 0.0, 0.0};
    switch (offset_between(m, frames, tset, gset, off)) {
        case OffsetStatus::ok: break;
        case OffsetStatus::none: return {};  // ballistic, BEFORE IsDead
        case OffsetStatus::missing:
            return need_frame(missing_set(frames, tset, gset));
        case OffsetStatus::unrepresentable:
            return need_guide("torpedo or target set");
    }

    // if hasattr(target, "IsDead") and target.IsDead(): return
    if (!tr.has_real_is_dead) return need_guide("target has no real IsDead");
    if (tr._dead) return {};

    // G1
    const double speed = length(row.vel);
    if (speed < 1e-6) return {};  // projectiles.py:1122 (NaN continues)
    Vec3 torp_pos;
    if (!torp_translate(m, row, torp_pos))
        return need_guide("torpedo transform");

    // _target_visible (projectiles.py:1031): can_detect from the FIRING
    // ship. Its `except Exception: return True` is not reproduced: whatever
    // the mirror cannot vouch for is Python's whole _guide instead.
    bool visible = true;
    const int64_t src = m.torpedo_ref(row, TorpField::_source_ship);
    if (src != -1) {
        if (src < 0) return need_guide("_source_ship");
        const int64_t sset = m.object(src)->_containing_set;
        Vec3 soff{0.0, 0.0, 0.0};
        const OffsetStatus os = offset_between(m, frames, sset, gset, soff);
        // A missing frame is the whole _guide, not a frame ASK: Python's
        // offset_between raise here is swallowed into True
        // (projectiles.py:1052-1062), so Python must decide it.
        if (os == OffsetStatus::missing)
            return need_guide("source or target frame");
        if (os == OffsetStatus::unrepresentable)
            return need_guide("source or target set");
        try {
            if (os == OffsetStatus::none || detail::is_zero_offset(soff)) {
                // memo-eligible (no optional argument); off None still asks
                visible = can_detect(m, src, target, clocks.drift_now,
                                     use_memo, std::nullopt, true,
                                     std::nullopt, clocks.occ_now);
            } else {
                // G10: in the SOURCE's frame; never memoised. use_memo is
                // false, as sensor_detection.can_detect's delegation passes
                // it whenever dist_sq_gu is given (sensor_detection.py:527).
                const Vec3 o = world_location(m, obj(m, src));
                const Vec3 p = shifted(world_location(m, tr), soff);
                const double dx = p[0] - o[0], dy = p[1] - o[1],
                             dz = p[2] - o[2];
                visible = can_detect(m, src, target, clocks.drift_now,
                                     false, dx * dx + dy * dy + dz * dz,
                                     true, std::nullopt, clocks.occ_now);
            }
        } catch (const std::invalid_argument&) {
            return need_guide("can_detect");
        }
    }

    if (!visible) {
        // aim = torpedo._last_seen_target_pos; if aim is None: return
        GuideResult r;
        if (!row.last_seen_set) return r;
        turn(row, dt, speed, torp_pos, row.last_seen, r);
        return r;
    }

    // pos = _steer_point(torpedo, target, off). can_detect HAS run: from
    // here on a question is a steer-point ASK, never a restart.
    GuideResult ask;
    ask.status = St::need_steer_point;
    ask.resume = {target, speed, torp_pos};
    std::optional<Vec3> offset;
    int64_t mount_sub = -1;
    bool attributed = false;
    if (row.target_offset_set) {
        // key is None or key[0] is not target or key[1:4] != offset: Python
        // attributes the mount, `_mount_key = (target, x, y, z,
        // authored_mount_subsystem(target, (x, y, z)))`. A NaN never
        // matches. The mirror attributes it too (round trips, Task 4),
        // unless it cannot tell (kMountUnknown: an entry it cannot name
        // before a match, or a target that is not a ShipClass).
        const Vec3& o = row.target_offset;
        const Vec3& k = row.mount_offset;
        if (!row.mount_attributed || !(k[0] == o[0]) || !(k[1] == o[1]) ||
            !(k[2] == o[2])) {
            mount_sub = authored_mount_subsystem(m, tr, o);
            if (mount_sub == kMountUnknown)
                return steer_ask(ask, SteerWhy::unattributed);
            attributed = true;
        } else {
            mount_sub = m.torpedo_ref(row, TorpField::_mount_key);
        }
        if (mount_sub == kRefUnrepresentable)
            return steer_ask(ask, SteerWhy::mount_unrepresentable);
        // A posed target's attributed mount whose row is gone: Python's.
        // Whether the offset is the mount's own point (posed) or not (a
        // plain body point, M8.5) is target_offset_world's.
        if (tr.has_posed_parts && mount_sub != kNoMount &&
            !m.subsystem(mount_sub))
            return steer_ask(ask, SteerWhy::mount_stale);
        offset = o;
    }
    Vec3 pos;
    try {
        pos = steer_point_native(m, target, offset, mount_sub, off);
    } catch (const PartStale&) {
        return steer_ask(ask, SteerWhy::part_stale);
    } catch (const std::invalid_argument&) {
        return steer_ask(ask, SteerWhy::geometry);
    }
    GuideResult r = guide_torpedo_resume(m, row, dt, ask.resume, pos);
    r.posed_steer = offset.has_value() && tr.has_posed_parts;
    // Only a steer decided here logs the key: any ASK above runs Python's
    // _steer_point, which attributes (and writes `_mount_key`) itself.
    r.attributed = attributed;
    r.mount = attributed ? mount_sub : -1;
    return r;
}

// projectiles.py:1129-1150: the visible branch from `_steer_point`'s answer.

GuideResult guide_torpedo_resume(const Mirror& m, const TorpedoRow& row,
                                 double dt, const GuideResume& resume,
                                 const Vec3& steer_point) {
    GuideResult r;
    const Vec3& pos = steer_point;
    write(r, GuideField::last_seen, pos);
    // vel = target.GetVelocityTG(): ObjectClass's fresh copy of _velocity.
    // The target row was live at the ASK; a row lost since throws (no
    // restart: can_detect has run).
    const Vec3 vel = obj(m, resume.target)._velocity;
    const Vec3& torp_pos = resume.torp_pos;
    // G2
    const Vec3 to_t{pos[0] - torp_pos[0], pos[1] - torp_pos[1],
                    pos[2] - torp_pos[2]};
    const double t_go = length(to_t) / resume.speed;
    // G3: prev_vel is the value cached at the last VISIBLE tick.
    Vec3 acc{0.0, 0.0, 0.0};
    if (row.last_tvel_set && dt > 1e-9) {  // projectiles.py:1138
        const Vec3& pv = row.last_tvel;
        acc = {(vel[0] - pv[0]) / dt, (vel[1] - pv[1]) / dt,
               (vel[2] - pv[2]) / dt};
    }
    write(r, GuideField::last_tvel, vel);
    // G4: (pos + vel * t_go) + ((K * acc) * t_go) * t_go per axis.
    const double kk = m.globals().LEAD_ACCEL_K;
    const Vec3 aim{
        pos[0] + vel[0] * t_go + kk * acc[0] * t_go * t_go,
        pos[1] + vel[1] * t_go + kk * acc[1] * t_go * t_go,
        pos[2] + vel[2] * t_go + kk * acc[2] * t_go * t_go,
    };
    turn(row, dt, resume.speed, torp_pos, aim, r);
    return r;
}

}  // namespace dauntless::combat
