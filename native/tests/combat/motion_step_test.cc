// Kernel M (motion_step.h) on hand-built mirror rows. The native-vs-Python
// differential, one test per branch, is tests/unit/test_native_motion_kernel.py.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include <gtest/gtest.h>

#include <array>
#include <cmath>
#include <cstdint>
#include <vector>

#include "dauntless/combat/mirror.h"
#include "dauntless/combat/motion_step.h"
#include "dauntless/transform_store.h"

using namespace dauntless::combat;
using dauntless::TransformStore;

namespace {

constexpr double kDt = 1.0 / 60.0;

struct World {
    TransformStore store;
    Mirror m{store};
    std::vector<std::pair<uint32_t, uint32_t>> xf;

    // A stock ship at `pos` with the identity rotation, no IES, no
    // setpoints, a TGPoint3 _current_angular_velocity and _angular_velocity
    // (both zero), as ShipClass.__init__ leaves them.
    int64_t ship(double x = 0.0) {
        auto [xi, xg] = store.alloc();
        store.set_position(xi, xg, x, 0.0, 0.0);
        xf.emplace_back(xi, xg);
        const int64_t h = m.register_row(Kind::Object, xi, xg,
                                         static_cast<int64_t>(xf.size()));
        m.set_i(h, Field::motion_stock, 1);
        m.set_i(h, Field::is_ship_class, 1);
        m.set_fv(h, Field::_current_angular_velocity, {0.0, 0.0, 0.0});
        m.set_fv(h, Field::_angular_velocity, {0.0, 0.0, 0.0});
        m.set_fv(h, Field::_velocity, {0.0, 0.0, 0.0});
        return h;
    }
    // _speed_setpoint = (speed, (0, 1, 0), MODEL) and a zero angular one.
    void setpoints(int64_t h, double speed) {
        m.set_floats(h, Field::_speed_setpoint, {speed, 0.0, 1.0, 0.0, 0.0});
        m.set_fv(h, Field::_target_angular_velocity_setpoint,
                 {0.0, 0.0, 0.0});
    }
    std::array<double, 3> pos(size_t i) const {
        return store.position(xf[i].first, xf[i].second);
    }
    std::array<double, 9> rot(size_t i) const {
        return store.rotation(xf[i].first, xf[i].second);
    }
    MotionResult step(const std::vector<int64_t>& rows, int64_t player = -1,
                      int64_t begin = 0, bool resume = false) {
        return motion_step(m, store, rows, player, kDt, begin, resume);
    }
};

}  // namespace

TEST(MotionStep, BranchOrder) {
    World w;
    // Immobile beats a warp and an arrival: passed over, nothing written
    // but its zero acceleration (the mirror's is None: it differs).
    const int64_t a = w.ship();
    w.setpoints(a, 5.0);
    w.m.set_i(a, Field::_static, 1);
    w.m.set_i(a, Field::_insystem_warp_transit, 1);
    w.m.set_i(a, Field::arriving, 1);
    MotionResult r = w.step({a});
    EXPECT_EQ(r.stop, MotionStop::Done);
    EXPECT_EQ(r.at, 1);
    ASSERT_EQ(r.writes.size(), 1u);
    EXPECT_EQ(r.writes[0].what, kAccel);
    EXPECT_EQ(r.writes[0].accel, (Vec3{0.0, 0.0, 0.0}));
    // ... but the stock check comes first of all.
    w.m.set_i(a, Field::motion_stock, 0);
    r = w.step({a});
    EXPECT_EQ(r.stop, MotionStop::PythonRow);
    EXPECT_EQ(r.reason, MotionReason::NotStock);
    // A warp beats an arrival.
    const int64_t b = w.ship();
    w.setpoints(b, 5.0);
    w.m.set_i(b, Field::_insystem_warp_transit, 1);
    w.m.set_i(b, Field::arriving, 1);
    r = w.step({b});
    EXPECT_EQ(r.stop, MotionStop::WarpRow);
    EXPECT_EQ(r.at, 0);
    EXPECT_EQ(r.reason, MotionReason::None);
    // An arrival beats the setpoint-less drift.
    const int64_t c = w.ship();
    w.m.set_fv(c, Field::_velocity, {1.0, 0.0, 0.0});
    w.m.set_i(c, Field::arriving, 1);
    r = w.step({c});
    EXPECT_EQ(r.stop, MotionStop::Done);
    EXPECT_EQ(w.pos(2)[0], 0.0);
    // Setpoint-less: the player is left alone, anyone else drifts.
    w.m.set_i(c, Field::arriving, 0);
    r = w.step({c}, c);
    EXPECT_EQ(w.pos(2)[0], 0.0);
    r = w.step({c});
    EXPECT_EQ(w.pos(2)[0], 1.0 * kDt);
    // No row, a dead row, a bad transform.
    r = w.step({-1});
    EXPECT_EQ(r.reason, MotionReason::NoRow);
    const int64_t d = w.ship();
    w.store.free(w.xf[3].first, w.xf[3].second);
    r = w.step({d});
    EXPECT_EQ(r.stop, MotionStop::PythonRow);
    EXPECT_EQ(r.reason, MotionReason::BadTransform);
}

TEST(MotionStep, StopsBeforeWritingTheRow) {
    World w;
    const int64_t a = w.ship(), b = w.ship(100.0), c = w.ship(200.0);
    for (int64_t h : {a, b, c}) w.setpoints(h, 5.0);
    w.m.set_fv(b, Field::_current_angular_velocity, {0.0, 0.0, 0.0, 0.0});
    const MotionResult r = w.step({a, b, c});
    EXPECT_EQ(r.stop, MotionStop::PythonRow);
    EXPECT_EQ(r.at, 1);
    EXPECT_EQ(r.reason, MotionReason::Unrepresentable);
    ASSERT_EQ(r.writes.size(), 1u);
    EXPECT_EQ(r.writes[0].row, 0u);
    EXPECT_EQ(w.m.object(a)->_current_speed, 5.0);   // the snap, committed
    EXPECT_NE(w.pos(0)[1], 0.0);
    // Nothing of row 1, nor of row 2, was written.
    EXPECT_EQ(w.m.object(b)->_current_speed, 0.0);
    EXPECT_EQ(w.pos(1)[1], 0.0);
    EXPECT_EQ(w.m.object(c)->_current_speed, 0.0);
    EXPECT_EQ(w.pos(2)[1], 0.0);
    // A throw inside the row stops it the same way, as FallBack: here
    // impulse_fractions meets an impulse engine whose parent subsystem the
    // mirror cannot name.
    const int64_t ies = w.m.register_row(Kind::Subsystem);
    w.m.set_i(ies, Field::motion_ies_stock, 1);
    w.m.set_ref(ies, Field::_parent_subsystem, kRefUnrepresentable);
    w.m.set_ref(c, Field::_impulse_engine_subsystem, ies);
    const MotionResult r2 = w.step({c});
    EXPECT_EQ(r2.stop, MotionStop::PythonRow);
    EXPECT_EQ(r2.at, 0);
    EXPECT_EQ(r2.reason, MotionReason::FallBack);
    EXPECT_TRUE(r2.writes.empty());
    EXPECT_EQ(w.m.object(c)->_current_speed, 0.0);
    // An impulse-engine ref the mirror cannot name is Unrepresentable.
    w.m.set_ref(c, Field::_impulse_engine_subsystem, kRefUnrepresentable);
    EXPECT_EQ(w.step({c}).reason, MotionReason::Unrepresentable);
}

TEST(MotionStep, ResumePastWarpOnlyForBegin) {
    World w;
    const int64_t a = w.ship(), b = w.ship(100.0);
    for (int64_t h : {a, b}) {
        w.setpoints(h, 5.0);
        w.m.set_i(h, Field::_insystem_warp_transit, 1);
    }
    MotionResult r = w.step({a, b}, -1, 0, true);
    EXPECT_EQ(r.stop, MotionStop::WarpRow);
    EXPECT_EQ(r.at, 1);
    ASSERT_EQ(r.writes.size(), 1u);
    EXPECT_EQ(r.writes[0].row, 0u);
    // Resumed at row 1, it is row 1 that runs past its warp.
    r = w.step({a, b}, -1, 1, true);
    EXPECT_EQ(r.stop, MotionStop::Done);
    EXPECT_EQ(r.at, 2);
    ASSERT_EQ(r.writes.size(), 1u);
    EXPECT_EQ(r.writes[0].row, 1u);
    // Not resumed: row 1 stops at its warp.
    r = w.step({a, b}, -1, 1, false);
    EXPECT_EQ(r.stop, MotionStop::WarpRow);
    EXPECT_EQ(r.at, 1);
    EXPECT_TRUE(r.writes.empty());
}

TEST(MotionStep, DriftWritesOnlyPose) {
    World w;
    const int64_t a = w.ship();
    w.m.set_fv(a, Field::_velocity, {1.0, 2.0, 3.0});
    w.m.set_fv(a, Field::_angular_velocity, {0.0, 0.0, 0.5});
    w.m.set_f(a, Field::_current_speed, 0.25);
    const MotionResult r = w.step({a});
    EXPECT_EQ(r.stop, MotionStop::Done);
    // drift.step sets no attribute: the row logs only its zero
    // acceleration (_no_thrust), and only because the mirror's is None.
    ASSERT_EQ(r.writes.size(), 1u);
    EXPECT_EQ(r.writes[0].what, kAccel);
    EXPECT_EQ(r.writes[0].accel, (Vec3{0.0, 0.0, 0.0}));
    EXPECT_EQ(w.pos(0)[0], 0.0 + 1.0 * kDt);
    EXPECT_EQ(w.pos(0)[1], 0.0 + 2.0 * kDt);
    EXPECT_EQ(w.pos(0)[2], 0.0 + 3.0 * kDt);
    EXPECT_NE(w.rot(0)[0], 1.0);         // spun about world Z
    const ObjectRow* o = w.m.object(a);
    EXPECT_EQ(o->_current_speed, 0.25);
    EXPECT_EQ(o->_velocity, (Vec3{1.0, 2.0, 3.0}));
    EXPECT_EQ(o->_drift_velocity_state, 0);
    // Its zeros now held, the next drift step logs nothing at all.
    EXPECT_TRUE(w.step({a}).writes.empty());
    // A `_velocity` that is not a TGPoint3 (state 2) is Python's: drift.step
    // reads v.x there and raises.
    w.m.set_i(a, Field::_velocity_state, 2);
    const MotionResult rv = w.step({a});
    EXPECT_EQ(rv.stop, MotionStop::PythonRow);
    EXPECT_EQ(rv.reason, MotionReason::Unrepresentable);
    w.m.set_fv(a, Field::_velocity, {1.0, 2.0, 3.0});
    // A spin whose rate underflows to zero is Python's ZeroDivisionError.
    w.m.set_fv(a, Field::_angular_velocity, {1e-200, 0.0, 0.0});
    const MotionResult r2 = w.step({a});
    EXPECT_EQ(r2.stop, MotionStop::PythonRow);
    EXPECT_EQ(r2.reason, MotionReason::FallBack);
}

TEST(MotionStep, UnrepresentableAngularSpace) {
    // _angular_space is pushed as Python's own test, `value == 0` (0 model,
    // 1 world), for an int or a bool; anything else (0.5, "0") is 2, and a
    // spinning drifter with it is Python's (Task 5, Review Focus 4).
    World w;
    const int64_t a = w.ship();
    w.m.set_fv(a, Field::_angular_velocity, {0.0, 0.0, 0.5});
    w.m.set_i(a, Field::_angular_space, 2);
    const MotionResult r = w.step({a});
    EXPECT_EQ(r.stop, MotionStop::PythonRow);
    EXPECT_EQ(r.reason, MotionReason::Unrepresentable);
    EXPECT_EQ(w.rot(0)[0], 1.0);         // nothing written
    // Not spinning: the frame is never read, so the row is ours.
    w.m.set_fv(a, Field::_angular_velocity, {0.0, 0.0, 0.0});
    EXPECT_EQ(w.step({a}).stop, MotionStop::Done);
}

TEST(MotionStep, SignedZeroRotation) {
    World w;
    const int64_t a = w.ship();
    // An all -0.0 rate is falsy (`x or y or z`): no rotation, and the
    // ramp keeps the -0.0 bits.
    w.setpoints(a, 0.0);
    w.m.set_fv(a, Field::_current_angular_velocity, {-0.0, -0.0, -0.0});
    w.m.set_fv(a, Field::_target_angular_velocity_setpoint,
               {-0.0, -0.0, -0.0});
    const auto r0 = w.rot(0);
    MotionResult r = w.step({a});
    ASSERT_EQ(r.writes.size(), 1u);
    EXPECT_TRUE(r.writes[0].what & kAngVel);
    for (double v : r.writes[0].cav) {
        EXPECT_EQ(v, 0.0);
        EXPECT_TRUE(std::signbit(v));
    }
    EXPECT_EQ(w.rot(0), r0);
    // TGMatrix3.MultMatrix's leading `0.0 +`: a row of -0.0 times any
    // column is +0.0, never the bare sum's -0.0.
    w.store.set_rotation(w.xf[0].first, w.xf[0].second,
                         {-0.0, -0.0, -0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0});
    w.m.set_fv(a, Field::_current_angular_velocity, {0.5, -0.0, -0.0});
    w.m.set_fv(a, Field::_target_angular_velocity_setpoint,
               {0.5, -0.0, -0.0});
    r = w.step({a});
    ASSERT_EQ(r.writes.size(), 1u);
    const auto r1 = w.rot(0);
    for (int j = 0; j < 3; ++j) {
        EXPECT_EQ(r1[j], 0.0);
        EXPECT_FALSE(std::signbit(r1[j])) << j;
    }
    EXPECT_NE(r1[4], 1.0);               // it did pitch
}

TEST(MotionStep, FallbackAccelOnZeroLimits) {
    World w;
    const int64_t a = w.ship();
    const int64_t ies = w.m.register_row(Kind::Subsystem);
    w.m.set_i(ies, Field::motion_ies_stock, 1);
    w.m.set_i(ies, Field::_is_on, 1);
    w.m.set_f(ies, Field::_power_percentage_wanted, 1.0);
    w.m.set_f(ies, Field::_max_speed, 6.3);
    w.m.set_f(ies, Field::_max_accel, 0.0);
    w.m.set_f(ies, Field::_max_angular_velocity, 0.3);
    w.m.set_f(ies, Field::_max_angular_accel, 0.0);
    w.m.set_ref(a, Field::_impulse_engine_subsystem, ies);
    w.setpoints(a, 5.0);
    w.m.set_fv(a, Field::_target_angular_velocity_setpoint, {0.5, 0.0, 0.0});
    const MotionResult r = w.step({a});
    ASSERT_EQ(r.writes.size(), 1u);
    // Linear: min(1e9, |5 - 0| / 1.0) * dt; angular: the 1e9 * dt step
    // snaps onto the 0.3 cap.
    EXPECT_EQ(r.writes[0].speed, 5.0 * kDt);
    EXPECT_EQ(r.writes[0].cav[0], 0.3);
    EXPECT_EQ(w.m.object(a)->_current_speed, 5.0 * kDt);
}

// The motion law: the velocity vector moves toward forward x target by
// min(accel, |gap| / tau) * dt, its speed is the vector's length, and the
// step / dt is logged as the acceleration.
TEST(MotionStep, VelocityVectorLaw) {
    World w;
    const int64_t a = w.ship();
    // A bare ship's limits are the snap; give it a real engine.
    const int64_t ies = w.m.register_row(Kind::Subsystem);
    w.m.set_i(ies, Field::motion_ies_stock, 1);
    w.m.set_i(ies, Field::_is_on, 1);
    w.m.set_f(ies, Field::_power_percentage_wanted, 1.0);
    w.m.set_f(ies, Field::_max_condition, 100.0);
    w.m.set_f(ies, Field::_condition, 100.0);
    w.m.set_f(ies, Field::_max_speed, 6.0);
    w.m.set_f(ies, Field::_max_accel, 1.5);
    w.m.set_ref(a, Field::_impulse_engine_subsystem, ies);
    w.setpoints(a, 6.0);
    // Moving sideways at 2 GU/s, nose along +y: the vector bends toward
    // the nose, it does not snap round.
    w.m.set_f(a, Field::_current_speed, 2.0);
    w.m.set_floats(a, Field::_motion_vel, {2.0, 0.0, 0.0, 2.0});
    w.m.set_fv(a, Field::_velocity, {2.0, 0.0, 0.0});
    const MotionResult r = w.step({a});
    ASSERT_EQ(r.stop, MotionStop::Done);
    ASSERT_EQ(r.writes.size(), 1u);
    const MotionWrite& x = r.writes[0];
    EXPECT_TRUE(x.what & kMotionVel);
    EXPECT_TRUE(x.what & kAccel);
    const double ex = 0.0 - 2.0, ey = 6.0 - 0.0;
    const double e = std::sqrt(ex * ex + ey * ey);
    const double k = 1.5 * kDt / e;       // min(1.5, e / 1) = 1.5
    EXPECT_EQ(x.velocity, (Vec3{2.0 + ex * k, 0.0 + ey * k, 0.0}));
    EXPECT_EQ(x.motion_vel[3], x.speed);
    EXPECT_EQ(x.accel[0], (x.velocity[0] - 2.0) / kDt);
    const std::vector<double> mv = w.m.get_floats(a, Field::_motion_vel);
    ASSERT_EQ(mv.size(), 4u);
    EXPECT_EQ(mv[0], x.velocity[0]);
    // A turn goal the mirror cannot represent is Python's, nothing written.
    w.m.set_floats(a, Field::_turn_goal, {0.0});
    const MotionResult g = w.step({a});
    EXPECT_EQ(g.stop, MotionStop::PythonRow);
    EXPECT_EQ(g.reason, MotionReason::TurnGoal);
    EXPECT_TRUE(g.writes.empty());
}

// A stored TurnTowardLocation goal is steered natively (ShipClass.
// _steer_turn_goal): a Galaxy-like row (MaxAngularAccel 0.12) at rest at the
// origin, nose +y, the point 90 degrees to starboard. The committed setpoint
// is Python's for the same inputs, produced by (one-off, 2026-11-06):
//   ship = ShipClass(); ship.SetTranslateXYZ(0, 0, 0)
//   ies = ImpulseEngineSubsystem("IES"); ies.SetMaxSpeed(6.3)
//   ies.SetMaxAccel(1.5); ies.SetMaxAngularVelocity(0.28)
//   ies.SetMaxAngularAccel(0.12); ship.SetImpulseEngineSubsystem(ies)
//   ship._speed_setpoint = (0.0, TGPoint3(0, 1, 0), 0)
//   ship.TurnTowardLocation(TGPoint3(100, 0, 0))
//   ship_motion._step_ship_motion(ship, 1 / 60)
//   [v.hex() for v in (sp.x, sp.y, sp.z)]   # sp: the setpoint after
// -> 0x0.0p+0 0x0.0p+0 -0x1.eb851eb851eb6p-4 (a yaw to starboard: w + a *
// BC_IMPULSE_TAU with the planned acceleration held at MaxAngularAccel).
TEST(MotionStep, SteersLocGoalFromRest) {
    World w;
    const int64_t a = w.ship();
    const int64_t ies = w.m.register_row(Kind::Subsystem);
    w.m.set_i(ies, Field::motion_ies_stock, 1);
    w.m.set_i(ies, Field::_is_on, 1);
    w.m.set_f(ies, Field::_power_percentage_wanted, 1.0);
    w.m.set_f(ies, Field::_max_condition, 100.0);
    w.m.set_f(ies, Field::_condition, 100.0);
    w.m.set_f(ies, Field::_max_speed, 6.3);
    w.m.set_f(ies, Field::_max_accel, 1.5);
    w.m.set_f(ies, Field::_max_angular_velocity, 0.28);
    w.m.set_f(ies, Field::_max_angular_accel, 0.12);
    w.m.set_ref(a, Field::_impulse_engine_subsystem, ies);
    w.setpoints(a, 0.0);
    w.m.set_floats(a, Field::_turn_goal, {1.0, 100.0, 0.0, 0.0});
    const MotionResult r = w.step({a});
    ASSERT_EQ(r.stop, MotionStop::Done);
    ASSERT_EQ(r.writes.size(), 1u);
    const MotionWrite& x = r.writes[0];
    EXPECT_TRUE(x.what & kSteer);
    const Vec3 want{0.0, 0.0, -0x1.eb851eb851eb6p-4};
    EXPECT_EQ(x.setpoint, want);
    const ObjectRow& o = *w.m.object(a);
    EXPECT_EQ(o._target_angular_velocity_setpoint, want);
    EXPECT_EQ(o._target_angular_velocity_setpoint_state, 1);
    EXPECT_EQ(o._target_angular_velocity_fraction_state, 0);
    // The angular law steps toward it uncapped: -0.12 * dt this tick.
    EXPECT_EQ(x.cav[2], -0x1.0624dd2f1a9fbp-9);
    // The goal itself is unchanged (it is the spec, not its setpoint).
    EXPECT_EQ(w.m.get_floats(a, Field::_turn_goal),
              (std::vector<double>{1.0, 100.0, 0.0, 0.0}));
}

// The acceleration is the law's own step / dt, written back only when it
// differs (bitwise) from the mirror's: a ship cruising at its target steps
// by zero, so its first commit writes the zeros (the mirror's is empty,
// None) and its second appends no kAccel.
TEST(MotionStep, AccelIsLawStepAndSkipsWhenUnchanged) {
    World w;
    const int64_t a = w.ship();
    const int64_t ies = w.m.register_row(Kind::Subsystem);
    w.m.set_i(ies, Field::motion_ies_stock, 1);
    w.m.set_i(ies, Field::_is_on, 1);
    w.m.set_f(ies, Field::_power_percentage_wanted, 1.0);
    w.m.set_f(ies, Field::_max_condition, 100.0);
    w.m.set_f(ies, Field::_condition, 100.0);
    w.m.set_f(ies, Field::_max_speed, 6.0);
    w.m.set_f(ies, Field::_max_accel, 1.5);
    w.m.set_ref(a, Field::_impulse_engine_subsystem, ies);
    w.setpoints(a, 5.0);
    w.m.set_f(a, Field::_current_speed, 5.0);
    w.m.set_floats(a, Field::_motion_vel, {0.0, 5.0, 0.0, 5.0});
    w.m.set_fv(a, Field::_velocity, {0.0, 5.0, 0.0});
    MotionResult r = w.step({a});
    ASSERT_EQ(r.stop, MotionStop::Done);
    ASSERT_EQ(r.writes.size(), 1u);
    EXPECT_TRUE(r.writes[0].what & kAccel);
    EXPECT_EQ(r.writes[0].accel, (Vec3{0.0, 0.0, 0.0}));
    EXPECT_EQ(w.m.get_floats(a, Field::_acceleration),
              (std::vector<double>{0.0, 0.0, 0.0}));
    r = w.step({a});
    ASSERT_EQ(r.stop, MotionStop::Done);
    ASSERT_EQ(r.writes.size(), 1u);
    EXPECT_TRUE(r.writes[0].what & kMotionVel);
    EXPECT_FALSE(r.writes[0].what & kAccel);
    // Bitwise: a held -0.0 is not the step's +0.0, so it is written.
    w.m.set_floats(a, Field::_acceleration, {-0.0, 0.0, 0.0});
    r = w.step({a});
    ASSERT_EQ(r.writes.size(), 1u);
    EXPECT_TRUE(r.writes[0].what & kAccel);
    EXPECT_FALSE(std::signbit(w.m.get_floats(a, Field::_acceleration)[0]));
    // Off its target the step is the law's: from rest, min(1.5, 5 / 1) * dt
    // along +y, over dt.
    w.m.set_f(a, Field::_current_speed, 0.0);
    r = w.step({a});
    ASSERT_EQ(r.writes.size(), 1u);
    EXPECT_TRUE(r.writes[0].what & kAccel);
    EXPECT_EQ(r.writes[0].accel[0], 0.0);
    EXPECT_EQ(r.writes[0].accel[1], r.writes[0].velocity[1] / kDt);
    EXPECT_EQ(r.writes[0].accel[2], 0.0);
    // A held acceleration the mirror cannot represent is Python's.
    w.m.set_floats(a, Field::_acceleration, {0.0, 0.0, 0.0, 0.0});
    r = w.step({a});
    EXPECT_EQ(r.stop, MotionStop::PythonRow);
    EXPECT_EQ(r.reason, MotionReason::Unrepresentable);
    EXPECT_TRUE(r.writes.empty());
}
