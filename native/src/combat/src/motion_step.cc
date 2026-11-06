// Kernel M -- see motion_step.h. A port of engine/appc/ship_motion.py
// _step_ship_motion and engine/appc/drift.py step, each step naming the
// Python line it stands for. Every float is computed as CPython computes it:
// double, left-associative, no fused multiply-add (this source is in
// DAUNTLESS_COMBAT_SOURCES: -ffp-contract=off, plus the pragma), py_min /
// py_max for min / max, py_pow for `** 0.5`, py_sin / py_cos for math.sin /
// math.cos, std::sqrt for math.sqrt.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "dauntless/combat/motion_step.h"

#include <array>
#include <cmath>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <string>

#include "dauntless/combat/impulse.h"
#include "dauntless/combat/py_math.h"
#include "geometry_internal.h"

namespace dauntless::combat {

namespace {

using Mat3 = std::array<double, 9>;  // row-major, TGMatrix3's m00..m22

// PhysicsObjectClass.DIRECTION_MODEL_SPACE
constexpr double kModelSpace = 0.0;
constexpr int64_t kModelSpaceI = 0;

// The row is Python's: stop PythonRow at it with `reason`.
struct ToPython {
    MotionReason reason;
};

[[noreturn]] void to_python(MotionReason r) { throw ToPython{r}; }

// `x or y or z` on floats: a component is truthy when != 0.0 (NaN is).
bool truthy(const Vec3& v) {
    return v[0] != 0.0 || v[1] != 0.0 || v[2] != 0.0;
}

// TGMatrix3.MakeRotation (math.py): the full Rodrigues form. math.cos /
// math.sin raise ValueError on an infinity, so Python's row raises there:
// the kernel hands it back.
Mat3 make_rotation(double angle, const Vec3& axis) {
    if (std::isinf(angle)) to_python(MotionReason::FallBack);
    const double c = py_cos(angle);
    const double s = py_sin(angle);
    const double t = 1.0 - c;
    const double x = axis[0], y = axis[1], z = axis[2];
    return {t * x * x + c,     t * x * y - s * z, t * x * z + s * y,
            t * x * y + s * z, t * y * y + c,     t * y * z - s * x,
            t * x * z - s * y, t * y * z + s * x, t * z * z + c};
}

// TGMatrix3.MultMatrix (math.py): a . b, each element 0.0 + p0 + p1 + p2,
// k ascending. The leading 0.0 is load-bearing (a sum of three -0.0
// products is +0.0 there); tests/unit/test_matrix_multiply_exact.py.
Mat3 mult(const Mat3& a, const Mat3& b) {
    Mat3 r;
    for (int i = 0; i < 3; ++i)
        for (int j = 0; j < 3; ++j)
            r[3 * i + j] = 0.0 + a[3 * i] * b[j] + a[3 * i + 1] * b[3 + j] +
                           a[3 * i + 2] * b[6 + j];
    return r;
}

// ship_motion._cap_keep
double cap_keep(double commanded, double current, double cap) {
    const double a = std::fabs(current);
    const double limit = cap > a ? cap : a;
    if (commanded > limit) return limit;
    if (commanded < -limit) return -limit;
    return commanded;
}

// ship_motion._ramp_toward
double ramp_toward(double current, double target, double step) {
    const double delta = target - current;
    if (std::fabs(delta) <= step) return target;
    return current + (delta > 0 ? step : -step);
}

// ship_motion.law_step_vector: move `cur` toward `target` by
// min(accel, |gap| / tau) * dt along the gap; accel >= FALLBACK_MAX_ACCEL
// snaps (`accel * dt`).
Vec3 law_step_vector(const Vec3& cur, const Vec3& target, double accel,
                     double dt) {
    const double ex = target[0] - cur[0], ey = target[1] - cur[1],
                 ez = target[2] - cur[2];
    const double e = std::sqrt(ex * ex + ey * ey + ez * ez);
    const double step = accel >= kFallbackMaxAccel
                            ? accel * dt
                            : py_min(accel, e / kBcImpulseTau) * dt;
    if (e <= step || e == 0.0) return target;
    const double k = step / e;
    return {cur[0] + ex * k, cur[1] + ey * k, cur[2] + ez * k};
}

// ── The stored turn goal: ShipClass._steer_turn_goal and its helpers ────
// (engine/appc/ships.py: _frame_rotation, _to_body, _turn_goal_vectors,
// _turn_rotation, _steer_turn_goal), operation for operation.

// TGPoint3.Cross (math.py:50).
Vec3 cross(const Vec3& a, const Vec3& b) {
    return {a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0]};
}

// TGPoint3.Unitize (math.py:98): in place, the length before; a length of
// 1e-12 or less leaves the vector as it is.
double unitize(Vec3& v) {
    const double n = detail::length(v);
    if (n > 1e-12) {
        v[0] /= n;
        v[1] /= n;
        v[2] /= n;
    }
    return n;
}

// TGMatrix3.GetCol(i) (math.py:269), R row-major m00..m22.
Vec3 col(const Mat3& R, int i) { return {R[i], R[3 + i], R[6 + i]}; }

// ships._to_body: R^T . v, each component c.x * v.x + c.y * v.y + c.z * v.z
// for the column c.
Vec3 to_body(const Mat3& R, const Vec3& v) {
    const Vec3 c0 = col(R, 0), c1 = col(R, 1), c2 = col(R, 2);
    return {c0[0] * v[0] + c0[1] * v[1] + c0[2] * v[2],
            c1[0] * v[0] + c1[1] * v[1] + c1[2] * v[2],
            c2[0] * v[0] + c2[1] * v[1] + c2[2] * v[2]};
}

// `if c > 1.0: c = 1.0 elif c < -1.0: c = -1.0; math.acos(c)` (a NaN passes
// both compares and acos returns it).
double clamped_acos(double c) {
    if (c > 1.0)
        c = 1.0;
    else if (c < -1.0)
        c = -1.0;
    return std::acos(c);
}

// Python `a / b` on floats: ZeroDivisionError when b == 0.0 (-0.0 too,
// whatever a is), which is Python's row to raise.
double py_div(double a, double b) {
    if (b == 0.0) to_python(MotionReason::FallBack);
    return a / b;
}

// Python `x ** 2` on a float (CPython 3.11 float_pow): a NaN is returned
// as it is, an infinity as its magnitude, a zero as 0.0, a magnitude of 1
// as 1.0; otherwise libm pow(|x|, 2.0) (the even exponent drops the sign),
// and a finite x whose square overflows raises OverflowError: Python's
// row.
double py_square(double x) {
    if (std::isnan(x)) return x;
    if (std::isinf(x)) return std::fabs(x);
    if (x == 0.0) return 0.0;
    const double a = std::fabs(x);
    if (a == 1.0) return 1.0;
    const double r = py_pow(a, 2.0);
    if (std::isinf(r)) to_python(MotionReason::FallBack);
    return r;
}

// ships._frame_rotation: the world rotation vector taking the frame
// (f0, u0) onto (f1, u1). Each m[i][j] is `sum(...)` from the int 0:
// 0.0 + p0 + p1 + p2, k ascending (a -0.0 first product becomes 0.0).
Vec3 frame_rotation(const Vec3& f0, const Vec3& u0, const Vec3& f1,
                    const Vec3& u1) {
    const Vec3 r0 = cross(f0, u0), r1 = cross(f1, u1);
    const Vec3* const a0[3] = {&r0, &f0, &u0};
    const Vec3* const a1[3] = {&r1, &f1, &u1};
    double m[3][3];
    for (int i = 0; i < 3; ++i)
        for (int j = 0; j < 3; ++j)
            m[i][j] = 0.0 + (*a1[0])[i] * (*a0[0])[j] +
                      (*a1[1])[i] * (*a0[1])[j] + (*a1[2])[i] * (*a0[2])[j];
    const double angle =
        clamped_acos((m[0][0] + m[1][1] + m[2][2] - 1.0) * 0.5);
    if (angle < 1e-9) return {0.0, 0.0, 0.0};
    double x = m[2][1] - m[1][2], y = m[0][2] - m[2][0],
           z = m[1][0] - m[0][1];
    double n = std::sqrt(x * x + y * y + z * z);
    if (n < 1e-6) {
        // angle ~ pi: the axis from the symmetric part, signs from the
        // largest diagonal. `d.index(max(d))`: the first strict maximum.
        double d[3];
        for (int i = 0; i < 3; ++i) d[i] = py_max(0.0, (m[i][i] + 1.0) * 0.5);
        int i = 0;
        for (int j = 1; j < 3; ++j)
            if (d[j] > d[i]) i = j;
        double ax[3] = {0.0, 0.0, 0.0};
        ax[i] = std::sqrt(d[i]);
        for (int j = 0; j < 3; ++j)
            if (j != i) ax[j] = py_div((m[i][j] + m[j][i]) * 0.25, ax[i]);
        x = ax[0];
        y = ax[1];
        z = ax[2];
        n = std::sqrt(x * x + y * y + z * z);
    }
    const double k = py_div(angle, n);
    return {x * k, y * k, z * k};
}

// ShipClass._turn_rotation's world axis-angle vector (av_x, av_y, av_z);
// its primary and roll angles are not read by the motion step. `R` is the
// rotation before this tick's spin (GetWorldRotation, for an about-face).
Vec3 turn_rotation(const Vec3& primary_from, const Vec3& primary_to,
                   bool has_secondary, const Vec3& secondary_from,
                   const Vec3& secondary_to, const Mat3& R) {
    Vec3 pf = primary_from;
    unitize(pf);
    Vec3 pt = primary_to;
    unitize(pt);
    // 1. Primary alignment.
    const double primary_angle = clamped_acos(detail::dot(pf, pt));
    Vec3 axis = cross(pf, pt);
    const double axis_len = detail::length(axis);
    if (axis_len < 1e-9) {
        if (primary_angle < 1e-6) {
            axis = {0.0, 0.0, 0.0};
        } else {
            // About the ship's own up projected off pf, else the world
            // axes.
            const Vec3 cu = col(R, 2);
            const double k = detail::dot(cu, pf);
            Vec3 candidate{cu[0] - pf[0] * k, cu[1] - pf[1] * k,
                           cu[2] - pf[2] * k};
            if (detail::length(candidate) < 1e-6)
                candidate = cross(pf, {0.0, 0.0, 1.0});
            if (detail::length(candidate) < 1e-6)
                candidate = cross(pf, {1.0, 0.0, 0.0});
            unitize(candidate);
            axis = candidate;
        }
    } else {
        // axis.Scale(1.0 / axis_len)
        const double factor = 1.0 / axis_len;
        axis[0] *= factor;
        axis[1] *= factor;
        axis[2] *= factor;
    }
    Vec3 av{axis[0] * primary_angle, axis[1] * primary_angle,
            axis[2] * primary_angle};
    // 2. Secondary constraint.
    double sf_len = 0.0, st_len = 0.0;
    if (has_secondary) {
        const Vec3& a = secondary_from;
        const Vec3& b = secondary_to;
        sf_len = py_pow(py_square(a[0]) + py_square(a[1]) + py_square(a[2]),
                        0.5);
        st_len = py_pow(py_square(b[0]) + py_square(b[1]) + py_square(b[2]),
                        0.5);
    }
    if (sf_len > 1e-9 && st_len > 1e-9) {
        const Vec3& sf = secondary_from;
        const Vec3& st = secondary_to;
        const double sk = detail::dot(sf, pt), tk = detail::dot(st, pt);
        Vec3 sf_proj{sf[0] - pt[0] * sk, sf[1] - pt[1] * sk,
                     sf[2] - pt[2] * sk};
        Vec3 st_proj{st[0] - pt[0] * tk, st[1] - pt[1] * tk,
                     st[2] - pt[2] * tk};
        const double sf_proj_len = unitize(sf_proj);
        const double st_proj_len = unitize(st_proj);
        if (sf_proj_len > 1e-9 && st_proj_len > 1e-9) {
            double roll_angle = clamped_acos(detail::dot(sf_proj, st_proj));
            if (detail::dot(cross(sf_proj, st_proj), pt) < 0.0)
                roll_angle = -roll_angle;
            const double k0 = detail::dot(sf, pf);
            Vec3 u0{sf[0] - pf[0] * k0, sf[1] - pf[1] * k0,
                    sf[2] - pf[2] * k0};
            if (unitize(u0) > 1e-9) {
                av = frame_rotation(pf, u0, pt, st_proj);
            } else {
                av[0] += pt[0] * roll_angle;
                av[1] += pt[1] * roll_angle;
                av[2] += pt[2] * roll_angle;
            }
        }
    }
    return av;
}

// The row's goal spec (native_combat.TurnGoalField) is one the kernel
// steers: [1, p(3)], [2, pf(3), pt(3), 0] or [2, pf(3), pt(3), 1, sf(3),
// st(3)].
bool goal_representable(const std::vector<double>& g) {
    if (g.size() == 4) return g[0] == 1.0;
    if (g.size() == 8) return g[0] == 2.0 && g[7] == 0.0;
    if (g.size() == 14) return g[0] == 2.0 && g[7] == 1.0;
    return false;
}

// ShipClass._steer_turn_goal(dt, max_aa) for the goal spec `g`: the new
// angular setpoint (body frame) in `out`, or false when the goal has no
// vectors left (a "loc" point the ship sits on: Python writes nothing).
// `here` is GetWorldLocation as Python's step reads it there: after this
// tick's translate. `R` is the rotation before this tick's spin, `cav` the
// body rate before this tick's angular law.
bool steer_turn_goal(const std::vector<double>& g, const Vec3& here,
                     const Mat3& R, const Vec3& cav, double dt, double max_aa,
                     Vec3& out) {
    // _turn_goal_vectors(spec)
    Vec3 pf, pt, sf{0.0, 0.0, 0.0}, st{0.0, 0.0, 0.0};
    bool has_secondary = false;
    if (g[0] == 1.0) {
        Vec3 d{g[1] - here[0], g[2] - here[1], g[3] - here[2]};
        if (detail::length(d) < 1e-9) return false;
        unitize(d);
        pf = col(R, 1);
        pt = d;
    } else {
        pf = detail::mult_matrix_left(R.data(), {g[1], g[2], g[3]});
        pt = {g[4], g[5], g[6]};
        if (g[7] == 1.0) {
            has_secondary = true;
            sf = detail::mult_matrix_left(R.data(), {g[8], g[9], g[10]});
            st = {g[11], g[12], g[13]};
        }
    }
    const Vec3 av = turn_rotation(pf, pt, has_secondary, sf, st, R);
    // w = R . cav, world
    const Vec3 w = detail::mult_matrix_left(R.data(), cav);
    const double theta =
        py_pow(av[0] * av[0] + av[1] * av[1] + av[2] * av[2], 0.5);
    double ax, ay, az;
    if (max_aa == 0.0 || max_aa <= 0.0) {
        // `not max_aa or max_aa <= 0.0`: the remaining angle per second.
        ax = av[0] - w[0];
        ay = av[1] - w[1];
        az = av[2] - w[2];
    } else {
        double ux = 0.0, uy = 0.0, uz = 0.0;
        if (theta > 1e-9) {
            ux = av[0] / theta;
            uy = av[1] / theta;
            uz = av[2] / theta;
        }
        const double w_along = w[0] * ux + w[1] * uy + w[2] * uz;
        const double tau =
            (std::sqrt(py_max(0.0, w_along * w_along + 6.0 * max_aa * theta)) -
             w_along) /
            max_aa;
        if (theta < 1e-6 || tau <= dt) {
            // land: shed what is left
            ax = py_div(-w[0], dt);
            ay = py_div(-w[1], dt);
            az = py_div(-w[2], dt);
        } else {
            const double k = py_div(6.0 * theta, tau * tau);
            ax = k * ux - py_div(4.0 * w[0], tau);
            ay = k * uy - py_div(4.0 * w[1], tau);
            az = k * uz - py_div(4.0 * w[2], tau);
        }
        const double a = py_pow(ax * ax + ay * ay + az * az, 0.5);
        if (a > max_aa) {
            ax = ax * max_aa / a;
            ay = ay * max_aa / a;
            az = az * max_aa / a;
        }
    }
    out = to_body(R, {w[0] + ax * kBcImpulseTau, w[1] + ay * kBcImpulseTau,
                      w[2] + az * kBcImpulseTau});
    return true;
}

// One row, computed into locals (commit() writes them).
struct Plan {
    bool commit = false;  // false: passed over, nothing to write
    bool warp = false;    // stop WarpRow
    bool pos_set = false, rot_set = false;
    Vec3 pos{0, 0, 0};
    Mat3 rot{};
    MotionWrite w{};
};

constexpr Vec3 kNoThrust{0.0, 0.0, 0.0};

// `ship._acceleration = a` (step_vector_velocity, _no_thrust): logged
// (kAccel) only when `a` differs BITWISE from the mirror's (-0.0 is not
// 0.0) or the mirror's is None; equal bits leave Python's value as it is,
// which is what Python's write would store. A value the mirror cannot
// represent (4 zeros) is Python's.
void record_accel(const ObjectRow& o, const Vec3& a, MotionWrite& w) {
    const std::vector<double>& held = o._acceleration;
    if (!(held.empty() || held.size() == 3))
        to_python(MotionReason::Unrepresentable);
    if (held.size() == 3 &&
        std::memcmp(held.data(), a.data(), sizeof(double) * 3) == 0)
        return;
    w.accel = a;
    w.what |= kAccel;
}

// ship_motion._integrate_rotation: R . (R_pitch . R_yaw . R_roll), the
// body-frame delta post-multiplied, pitch (X) -> yaw (Z) -> roll (Y).
void integrate_rotation(const Vec3& cav, double dt, const Mat3& R, Plan& p) {
    if (!truthy(cav)) return;
    const Mat3 r_pitch = make_rotation(cav[0] * dt, {1.0, 0.0, 0.0});
    const Mat3 r_yaw = make_rotation(cav[2] * dt, {0.0, 0.0, 1.0});
    const Mat3 r_roll = make_rotation(cav[1] * dt, {0.0, 1.0, 0.0});
    const Mat3 delta = mult(mult(r_pitch, r_yaw), r_roll);
    p.rot = mult(R, delta);
    p.rot_set = true;
}

// drift.step (drift.py), past its isinstance and IsImmobile gates (a stock
// ShipClass row, already known mobile). Writes only the pose.
void drift_step(const ObjectRow& o, const Vec3& pos, const Mat3& R, double dt,
                Plan& p) {
    // `v = obj._velocity`: a value that is not a TGPoint3 (a tuple) is
    // Python's, which raises reading v.x.
    if (o._velocity_state != 1) to_python(MotionReason::Unrepresentable);
    const Vec3& v = o._velocity;
    if (truthy(v)) {
        p.pos = {pos[0] + v[0] * dt, pos[1] + v[1] * dt, pos[2] + v[2] * dt};
        p.pos_set = true;
    }
    // `w = obj._angular_velocity`: None or a non-TGPoint3 is Python's (it
    // raises reading w.x there, or reads an object the mirror cannot).
    if (o._angular_velocity_state != 1) to_python(MotionReason::Unrepresentable);
    const Vec3& w = o._angular_velocity;
    if (!truthy(w)) return;
    const double rate = py_pow(w[0] * w[0] + w[1] * w[1] + w[2] * w[2], 0.5);
    // `w.x / rate`: Python raises ZeroDivisionError when the squares
    // underflow to a zero rate.
    if (rate == 0.0) to_python(MotionReason::FallBack);
    const Vec3 axis{w[0] / rate, w[1] / rate, w[2] / rate};
    const Mat3 D = make_rotation(rate * dt, axis);
    // `getattr(obj, "_angular_space", WORLD) == MODEL_SPACE`: the row holds
    // that test's answer for an int or a bool (0 model, 1 world); any other
    // value (0.5, "0") is 2, Python's to compare (native_combat
    // AngularSpaceField).
    if (o._angular_space != 0 && o._angular_space != 1)
        to_python(MotionReason::Unrepresentable);
    p.rot = o._angular_space == kModelSpaceI ? mult(R, D) : mult(D, R);
    p.rot_set = true;
}

// The row's subsystem refs the walk reads, checked before it reads them:
// the IES is ImpulseEngineSubsystem's own surface, and so is every pod.
const SubsystemRow* stock_ies(const Mirror& m, const ObjectRow& o) {
    const int64_t ref = o._impulse_engine_subsystem;
    if (ref == -1) return nullptr;
    if (ref == kRefUnrepresentable) to_python(MotionReason::Unrepresentable);
    const SubsystemRow* ies = m.subsystem(ref);
    if (!ies) to_python(MotionReason::Unrepresentable);
    if (!ies->motion_ies_stock) to_python(MotionReason::NotStock);
    for (const int64_t c : ies->_children) {
        if (c == kRefUnrepresentable) to_python(MotionReason::Unrepresentable);
        const SubsystemRow* pod = m.subsystem(c);
        if (!pod) to_python(MotionReason::Unrepresentable);
        if (!pod->motion_pod_stock) to_python(MotionReason::NotStock);
    }
    return ies;
}

Plan plan_step(const Mirror& m, const TransformStore& store, int64_t h,
               int64_t player, double dt, bool past_warp) {
    Plan p;
    const ObjectRow* row = h < 0 ? nullptr : m.object(h);
    if (!row) to_python(MotionReason::NoRow);
    const ObjectRow& o = *row;
    if (!o.motion_stock) to_python(MotionReason::NotStock);
    if (o.xform_index < 0 || o.xform_gen < 0 ||
        o.xform_index > std::numeric_limits<uint32_t>::max() ||
        o.xform_gen > std::numeric_limits<uint32_t>::max() ||
        !store.valid(static_cast<uint32_t>(o.xform_index),
                     static_cast<uint32_t>(o.xform_gen)))
        to_python(MotionReason::BadTransform);
    const TransformStore::Transform& t =
        store.at(static_cast<uint32_t>(o.xform_index));
    const Vec3 pos{t.pos[0], t.pos[1], t.pos[2]};
    Mat3 R;
    for (int i = 0; i < 9; ++i) R[i] = t.rot[i];

    // `if implements(ship, "IsImmobile") and ship.IsImmobile():
    //     _no_thrust(ship); return`
    if (o._static || o._stationary) {
        record_accel(o, kNoThrust, p.w);
        p.commit = p.w.what != 0;
        return p;
    }
    // `if getattr(ship, "_insystem_warp_transit", None) is not None:`
    if (o._insystem_warp_transit && !past_warp) {
        p.warp = true;
        return p;
    }
    // `if warp_state.is_arriving(ship): _no_thrust(ship); return`
    if (o.arriving) {
        record_accel(o, kNoThrust, p.w);
        p.commit = p.w.what != 0;
        return p;
    }

    const std::vector<double>& sp = o._speed_setpoint;
    if (!(sp.empty() || sp.size() == 5))
        to_python(MotionReason::Unrepresentable);
    const bool sp_none = sp.empty();
    const int64_t av_state = o._target_angular_velocity_setpoint_state;
    if (sp_none && av_state == 0) {
        // `if ship is not App.Game_GetCurrentPlayer(): drift.step(ship,
        // dt); _no_thrust(ship)` -- the player's helm owns its acceleration.
        if (h != player) {
            drift_step(o, pos, R, dt, p);
            record_accel(o, kNoThrust, p.w);
        }
        p.commit = p.pos_set || p.rot_set || p.w.what != 0;
        return p;
    }
    if (av_state == 2) to_python(MotionReason::Unrepresentable);

    // -- Commanded speed + world-space direction --
    double commanded;
    Vec3 wd;
    if (sp_none) {
        commanded = 0.0;
        wd = {0.0, 1.0, 0.0};
    } else {
        commanded = sp[0];
        const Vec3 d{sp[1], sp[2], sp[3]};
        // The rotation before this tick's spin.
        wd = sp[4] == kModelSpace ? detail::mult_matrix_left(R.data(), d) : d;
        // TGPoint3.Unitize
        const double n = std::sqrt(wd[0] * wd[0] + wd[1] * wd[1] + wd[2] * wd[2]);
        if (n > 1e-12) {
            wd[0] /= n;
            wd[1] /= n;
            wd[2] /= n;
        }
    }

    const SubsystemRow* ies = stock_ies(m, o);
    const ImpulseFractions fr =
        impulse_fractions(m, ies ? o._impulse_engine_subsystem : -1);
    const double f = fr.online;

    // Both branches below read _current_angular_velocity (cav.x ...) and
    // may read _drift_velocity.
    if (o._current_angular_velocity_state != 1)
        to_python(MotionReason::Unrepresentable);
    if (o._drift_velocity_state == 2) to_python(MotionReason::Unrepresentable);
    double speed = o._current_speed;
    MotionWrite& w = p.w;

    // -- Total loss -> inertial drift --
    if (f <= 0.0) {
        Vec3 dv;
        if (o._drift_velocity_state == 0) {
            dv = {wd[0] * speed, wd[1] * speed, wd[2] * speed};
            w.drift = dv;
            w.what |= kDriftSet;
        } else {
            dv = o._drift_velocity;
        }
        p.pos = {pos[0] + dv[0] * dt, pos[1] + dv[1] * dt, pos[2] + dv[2] * dt};
        p.pos_set = true;
        w.velocity = dv;
        w.what |= kVelocity;
        integrate_rotation(o._current_angular_velocity, dt, R, p);
        record_accel(o, kNoThrust, w);  // _no_thrust(ship)
        p.commit = true;
        return p;
    }

    // -- Powered flight: clear any drift snapshot, re-seed speed --
    if (o._drift_velocity_state == 1) {
        speed = detail::length(o._drift_velocity);
        w.what |= kDriftClear;
    }

    // _effective_motion(ship, ies=ies, imp_f=_imp_out_f)
    bool has_lin = false, has_ang = false;
    double max_speed = 0.0, max_accel = 0.0, max_ang_vel = 0.0,
           max_ang_accel = 0.0;
    if (ies) {
        const double out_f = fr.output;
        has_lin = ies->_max_speed > 0.0;
        has_ang = ies->_max_angular_velocity > 0.0;
        if (has_lin) {
            max_speed = ies->_max_speed * out_f;
            max_accel = ies->_max_accel * out_f;
        }
        if (has_ang) {
            max_ang_vel = ies->_max_angular_velocity * out_f;
            max_ang_accel = ies->_max_angular_accel * out_f;
        }
    }

    // -- Linear: BC's law on the velocity vector (course lags the nose) --
    double target, accel;
    if (has_lin) {
        target = cap_keep(commanded, speed, max_speed);
        accel = max_accel > 0.0 ? max_accel : kFallbackMaxAccel;
    } else {
        target = commanded;
        accel = kFallbackMaxAccel;
    }
    // step_vector_velocity(ship, world_dir, speed, target, accel, dt).
    // The re-seed contract: the vector is trusted only while `speed`
    // (_current_speed) is bit-identical to _motion_vel[3], the speed this
    // step last returned; any writer that sets _current_speed directly
    // (warp exit, drift re-seed, tests) makes them differ and the vector is
    // re-seeded along the nose; a writer that must keep the vector (none
    // today) must write both.
    const std::vector<double>& mv = o._motion_vel;
    if (!(mv.empty() || mv.size() == 4))
        to_python(MotionReason::Unrepresentable);
    Vec3 vel;
    if (mv.empty() || speed != mv[3])
        vel = {wd[0] * speed, wd[1] * speed, wd[2] * speed};
    else
        vel = {mv[0], mv[1], mv[2]};
    const Vec3 start = vel;  // `sx, sy, sz = vel`
    const Vec3 tv{wd[0] * target, wd[1] * target, wd[2] * target};
    const double ex = tv[0] - vel[0], ey = tv[1] - vel[1], ez = tv[2] - vel[2];
    const double e = std::sqrt(ex * ex + ey * ey + ez * ez);
    // snap=not em.has_linear: the whole gap in one step.
    const double step =
        !has_lin ? accel * dt : py_min(accel, e / kBcImpulseTau) * dt;
    if (e <= step || e == 0.0) {
        vel = tv;
        speed = target;
    } else {
        const double k = step / e;
        vel = {vel[0] + ex * k, vel[1] + ey * k, vel[2] + ez * k};
        speed =
            std::sqrt(vel[0] * vel[0] + vel[1] * vel[1] + vel[2] * vel[2]);
        if (vel[0] * wd[0] + vel[1] * wd[1] + vel[2] * wd[2] < 0.0)
            speed = -speed;
    }
    w.motion_vel = {vel[0], vel[1], vel[2], speed};
    w.what |= kMotionVel;
    // `_acceleration = ((vx - sx) / dt, ...)`, zeros when dt <= 0: the
    // law's own step, never dv/dt.
    if (dt <= 0.0)
        record_accel(o, kNoThrust, w);
    else
        record_accel(o,
                     {(vel[0] - start[0]) / dt, (vel[1] - start[1]) / dt,
                      (vel[2] - start[2]) / dt},
                     w);
    w.speed = speed;
    w.what |= kSpeed;

    // `if vx or vy or vz:` guards only the translate.
    if (truthy(vel)) {
        p.pos = {pos[0] + vel[0] * dt, pos[1] + vel[1] * dt,
                 pos[2] + vel[2] * dt};
        p.pos_set = true;
    }
    w.velocity = vel;
    w.what |= kVelocity;

    // -- Angular: the law on the rate vector --
    // `steering = goal is not None and av is not None and goal[1] is av`.
    // The mirror holds the goal's spec, not whose setpoint goal[1] is: a
    // stored goal with a setpoint steers, which agrees with Python because
    // every other writer that rebinds the setpoint to an object clears the
    // goal (native_combat.TurnGoalField). The steering runs after the
    // translate (a "loc" goal reads the moved position) and before the
    // spin, and its setpoint is not capped at MaxAngularVelocity.
    const std::vector<double>& goal = o._turn_goal;
    const bool steering = !goal.empty() && av_state == 1;
    Vec3 av = o._target_angular_velocity_setpoint;
    int64_t frac_state = o._target_angular_velocity_fraction_state;
    if (steering) {
        if (!goal_representable(goal)) to_python(MotionReason::TurnGoal);
        Vec3 sp;
        if (steer_turn_goal(goal, p.pos_set ? p.pos : pos, R,
                            o._current_angular_velocity, dt, max_ang_accel,
                            sp)) {
            // `_target_angular_velocity_setpoint = target`, the fraction
            // None, `goal[1] = target`.
            av = sp;
            frac_state = 0;
            w.setpoint = sp;
            w.what |= kSteer;
        }
    }
    if (frac_state == 2) to_python(MotionReason::Unrepresentable);
    Vec3 tg{0.0, 0.0, 0.0};
    if (frac_state == 1 && has_ang) {
        const Vec3& fr3 = o._target_angular_velocity_fraction;
        tg = {fr3[0] * max_ang_vel, fr3[1] * max_ang_vel, fr3[2] * max_ang_vel};
    } else if (av_state == 1) {
        tg = av;
    }
    Vec3 cav = o._current_angular_velocity;
    if (has_ang) {
        if (!steering) {
            tg[0] = cap_keep(tg[0], cav[0], max_ang_vel);
            tg[1] = cap_keep(tg[1], cav[1], max_ang_vel);
            tg[2] = cap_keep(tg[2], cav[2], max_ang_vel);
        }
        const double aa =
            max_ang_accel > 0.0 ? max_ang_accel : kFallbackMaxAccel;
        cav = law_step_vector(cav, tg, aa, dt);
    } else {
        const double ang_step = kFallbackMaxAccel * dt;
        cav[0] = ramp_toward(cav[0], tg[0], ang_step);
        cav[1] = ramp_toward(cav[1], tg[1], ang_step);
        cav[2] = ramp_toward(cav[2], tg[2], ang_step);
    }
    w.cav = cav;
    w.what |= kAngVel;

    integrate_rotation(cav, dt, R, p);
    p.commit = true;
    return p;
}

// Write a computed row: the store pose, the mirror's motion fields, and
// its log entry.
void commit(Mirror& m, TransformStore& store, int64_t h, uint32_t row,
            const Plan& p, std::vector<MotionWrite>& writes) {
    const ObjectRow& o = *m.object(h);
    const auto xi = static_cast<uint32_t>(o.xform_index);
    const auto xg = static_cast<uint32_t>(o.xform_gen);
    if (p.pos_set) store.set_position(xi, xg, p.pos[0], p.pos[1], p.pos[2]);
    if (p.rot_set) store.set_rotation(xi, xg, p.rot);
    const MotionWrite& w = p.w;
    if (w.what == 0) return;
    if (w.what & kSpeed) m.set_f(h, Field::_current_speed, w.speed);
    if (w.what & kAngVel)
        m.set_fv(h, Field::_current_angular_velocity,
                 {w.cav[0], w.cav[1], w.cav[2]});
    if (w.what & kVelocity)
        m.set_fv(h, Field::_velocity,
                 {w.velocity[0], w.velocity[1], w.velocity[2]});
    if (w.what & kDriftSet)
        m.set_fv(h, Field::_drift_velocity,
                 {w.drift[0], w.drift[1], w.drift[2]});
    if (w.what & kDriftClear) m.set_fv(h, Field::_drift_velocity, {});
    if (w.what & kMotionVel)
        m.set_floats(h, Field::_motion_vel,
                     {w.motion_vel[0], w.motion_vel[1], w.motion_vel[2],
                      w.motion_vel[3]});
    if (w.what & kAccel)
        m.set_floats(h, Field::_acceleration,
                     {w.accel[0], w.accel[1], w.accel[2]});
    if (w.what & kSteer) {
        m.set_fv(h, Field::_target_angular_velocity_setpoint,
                 {w.setpoint[0], w.setpoint[1], w.setpoint[2]});
        m.set_fv(h, Field::_target_angular_velocity_fraction, {});
    }
    writes.push_back(w);
    writes.back().row = row;
}

}  // namespace

MotionResult motion_step(Mirror& m, dauntless::TransformStore& store,
                         const std::vector<int64_t>& rows, int64_t player,
                         double dt, int64_t begin, bool resume_past_warp) {
    const auto n = static_cast<int64_t>(rows.size());
    if (begin < 0 || begin > n)
        throw std::invalid_argument("combat motion: begin " +
                                    std::to_string(begin) + " outside the " +
                                    std::to_string(n) + " rows");
    MotionResult r{MotionStop::Done, n, MotionReason::None, {}};
    // At most one write per row: reserved up front, so commit's append
    // never allocates (and never throws) after a row's store and mirror
    // writes.
    r.writes.reserve(static_cast<size_t>(n - begin));
    for (int64_t i = begin; i < n; ++i) {
        Plan p;
        try {
            p = plan_step(m, store, rows[static_cast<size_t>(i)], player, dt,
                         resume_past_warp && i == begin);
        } catch (const ToPython& e) {
            r.stop = MotionStop::PythonRow;
            r.at = i;
            r.reason = e.reason;
            return r;
        } catch (const std::invalid_argument&) {
            // A helper's "answer in Python" (impulse_fractions).
            r.stop = MotionStop::PythonRow;
            r.at = i;
            r.reason = MotionReason::FallBack;
            return r;
        }
        if (p.warp) {
            r.stop = MotionStop::WarpRow;
            r.at = i;
            return r;
        }
        if (p.commit)
            commit(m, store, rows[static_cast<size_t>(i)],
                   static_cast<uint32_t>(i), p, r.writes);
    }
    return r;
}

}  // namespace dauntless::combat
