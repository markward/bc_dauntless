#pragma once

// Helpers shared by the combat geometry sources (weapon_geometry.cc,
// beam_geometry.cc, beam_trace.cc, projectile_geometry.cc, k3_projectiles.cc):
// row access that falls back, the transform slot, and the
// TGPoint3 operations the Python geometry uses. Internal to the combat
// library; included only AFTER the including source's
// `#pragma clang fp contract(off)`.

#include <cmath>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <string>

#include "dauntless/combat/mirror.h"
#include "dauntless/combat/published_poses.h"

namespace dauntless::combat::detail {

[[noreturn]] inline void fall_back(const char* why) {
    throw std::invalid_argument(std::string("combat geometry: ") + why +
                                " -- answer in Python");
}

// fall_back with a reason a kernel counts (part_pose.h): `Why` is
// PartStale or MountUnknown. The message keeps fall_back's shape.
template <class Why>
[[noreturn]] inline void fall_back_as(const char* why) {
    throw Why(std::string("combat geometry: ") + why + " -- answer in Python");
}

// ── Row access: a stale or unnamed handle falls back ────────────────────────

inline const ObjectRow& obj(const Mirror& m, int64_t h) {
    if (h < 0) fall_back("object handle is none or unrepresentable");
    const ObjectRow* r = m.object(h);
    if (!r) fall_back("object handle is stale, freed or not an Object");
    return *r;
}

inline const SubsystemRow& sub(const Mirror& m, int64_t h) {
    if (h < 0) fall_back("subsystem handle is none or unrepresentable");
    const SubsystemRow* r = m.subsystem(h);
    if (!r) fall_back("subsystem handle is stale, freed or not a Subsystem");
    return *r;
}

// The ObjectClass transform slot (GetWorldLocation / GetWorldRotation):
// inside the published-pose read window, the pose the tick's motion stage
// published for the slot; else (window closed, or the slot not published)
// the live store slot (published_poses.h, THE READ WINDOW; read_pose, which
// reads the process-wide published_poses() whatever Mirror is given).
inline const TransformStore::Transform& xform(const Mirror& m,
                                              const ObjectRow& o) {
    if (o.xform_index < 0 || o.xform_gen < 0 ||
        o.xform_index > std::numeric_limits<uint32_t>::max() ||
        o.xform_gen > std::numeric_limits<uint32_t>::max())
        fall_back("object has no transform");
    const auto xi = static_cast<uint32_t>(o.xform_index);
    const auto xg = static_cast<uint32_t>(o.xform_gen);
    if (!m.store().valid(xi, xg)) fall_back("object transform is invalid");
    return read_pose(m.store(), xi, xg);
}

inline Vec3 world_location(const Mirror& m, const ObjectRow& o) {
    const auto& t = xform(m, o);
    return {t.pos[0], t.pos[1], t.pos[2]};
}

// TGPoint3.MultMatrixLeft (engine/appc/math.py:86), r row-major m00..m22:
// v = M . v, each component m_i0*x + m_i1*y + m_i2*z, left-associative.
inline Vec3 mult_matrix_left(const double* r, const Vec3& v) {
    const double x = r[0] * v[0] + r[1] * v[1] + r[2] * v[2];
    const double y = r[3] * v[0] + r[4] * v[1] + r[5] * v[2];
    const double z = r[6] * v[0] + r[7] * v[1] + r[8] * v[2];
    return {x, y, z};
}

// TGPoint3.Length (math.py:41): libm sqrt, correctly rounded.
inline double length(const Vec3& v) {
    return std::sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
}

// TGPoint3.Dot (math.py:47).
inline double dot(const Vec3& a, const Vec3& b) {
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

// `off == _ZERO_OFFSET` (frames.py:174, projectiles.py): a tuple ==, element
// ==, so -0.0 counts as zero and a NaN never does.
inline bool is_zero_offset(const Vec3& off) {
    return off[0] == 0.0 && off[1] == 0.0 && off[2] == 0.0;
}

// frames.shifted(p, off, sign) (frames.py:166-177) for an offset that is not
// None: `p` itself when `off` is zero, else p + sign * off per axis (sign
// 1.0 or -1.0, so `sign * off` is exact).
inline Vec3 shifted(const Vec3& p, const Vec3& off, double sign = 1.0) {
    if (is_zero_offset(off)) return p;
    return {p[0] + sign * off[0], p[1] + sign * off[1], p[2] + sign * off[2]};
}

}  // namespace dauntless::combat::detail
