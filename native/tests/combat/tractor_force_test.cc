// The tractor force step (tractor_force.h) on hand-built mirror rows. Every
// expected float is the REAL Python's: engine/appc/tractor.py's _apply_mode
// as it stood before the port (HEAD 23b3845d5), run on the same inputs and
// written as Python's float.hex().
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include <gtest/gtest.h>

#include <array>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>
#include <utility>
#include <string>
#include <vector>

#include "dauntless/combat/mirror.h"
#include "dauntless/combat/tractor_force.h"
#include "dauntless/transform_store.h"

using namespace dauntless::combat;
using dauntless::TransformStore;

namespace {

double hx(const char* s) { return std::strtod(s, nullptr); }

// Python's float.hex() (normal numbers and zero are all these tests use).
std::string py_hex(double v) {
    uint64_t bits;
    std::memcpy(&bits, &v, sizeof bits);
    const bool neg = bits >> 63;
    const int e = static_cast<int>((bits >> 52) & 0x7ff);
    const unsigned long long mant = bits & ((1ULL << 52) - 1);
    char buf[64];
    if (e == 0 && mant == 0)
        std::snprintf(buf, sizeof buf, "%s0x0.0p+0", neg ? "-" : "");
    else
        std::snprintf(buf, sizeof buf, "%s0x1.%013llxp%+d", neg ? "-" : "",
                      mant, e - 1023);
    return buf;
}

std::string hexes(const std::array<double, 3>& p) {
    return "{" + py_hex(p[0]) + ", " + py_hex(p[1]) + ", " + py_hex(p[2]) + "}";
}

constexpr double kDt = 1.0 / 60.0;

// TGMatrix3.MakeZRotation(0.3), Python's, row-major.
const std::array<double, 9> kRot = {
    hx("0x1.e921dd42f09bap-1"), hx("-0x1.2e9cd95baba33p-2"), 0.0,
    hx("0x1.2e9cd95baba33p-2"), hx("0x1.e921dd42f09bap-1"), 0.0,
    0.0, 0.0, 1.0};

struct World {
    TransformStore store;
    Mirror m{store};

    World() {
        // engine/appc/tractor.py and weapon_subsystems.TRACTOR_MAX_RANGE_GU.
        m.set_global_f(Global::TRACTOR_REFERENCE_MASS, 100.0);
        m.set_global_f(Global::TRACTOR_REFERENCE_SPEED_GUPS, 5.0);
        m.set_global_f(Global::TRACTOR_MAX_SPEED_GUPS, 20.0);
        m.set_global_f(Global::TRACTOR_FALLBACK_MASS, 1.0e4);
        m.set_global_f(Global::TRACTOR_TOW_DRAG_FRACTION, 0.25);
        m.set_global_f(Global::TRACTOR_DOCK_GENTLE_FRACTION, 0.4);
        m.set_global_f(Global::TRACTOR_STANDOFF_MARGIN_GU, 3.0);
        m.set_global_f(Global::TRACTOR_EPS, 1e-6);
        m.set_global_f(Global::TRACTOR_MAX_RANGE_GU, 120.0);
    }

    // A placed object: a ShipClass unless `ship` is false.
    int64_t object(const std::array<double, 3>& at, double mass, double radius,
                   bool ship = true,
                   const std::array<double, 9>& rot = {1, 0, 0, 0, 1, 0, 0, 0,
                                                       1}) {
        const auto [xi, xg] = store.alloc();
        store.set_position(xi, xg, at[0], at[1], at[2]);
        store.set_rotation(xi, xg, rot);
        const int64_t h = m.register_row(Kind::Object, xi, xg);
        m.set_i(h, Field::is_ship_class, ship ? 1 : 0);
        m.set_i(h, Field::has_real_is_dead, 1);
        m.set_f(h, Field::_mass, mass);
        m.set_f(h, Field::o_radius, radius);
        return h;
    }

    // `source`'s tractor system in `mode`, one projector firing at `target`.
    int64_t tractor(int64_t source, int64_t target, TractorMode mode) {
        const int64_t s = m.register_row(Kind::Subsystem);
        m.set_i(s, Field::weapon_kind, 3);
        m.set_i(s, Field::_mode, static_cast<int64_t>(mode));
        m.set_ref(source, Field::_tractor_beam_system, s);
        const int64_t b = m.register_row(Kind::Subsystem);
        m.set_i(b, Field::weapon_kind, 7);
        m.set_ref(b, Field::_parent_subsystem, s);
        m.set_i(b, Field::_firing, 1);
        m.set_ref(b, Field::_target, target);
        m.set_ids(s, Field::_children, {b});
        return s;
    }

    std::string at(int64_t h) const {
        const ObjectRow* o = m.object(h);
        return hexes(store.position(static_cast<uint32_t>(o->xform_index),
                                    static_cast<uint32_t>(o->xform_gen)));
    }
    void move(int64_t h, const std::array<double, 3>& p) {
        const ObjectRow* o = m.object(h);
        store.set_position(static_cast<uint32_t>(o->xform_index),
                           static_cast<uint32_t>(o->xform_gen), p[0], p[1],
                           p[2]);
    }
};

const std::array<double, 3> kSource = {1.5, -2.25, 0.75};
const std::array<double, 3> kTarget = {10.25, 30.5, -3.125};
const char* const kSourceAt =
    "{0x1.8000000000000p+0, -0x1.2000000000000p+1, 0x1.8000000000000p-1}";
const char* const kTargetAt =
    "{0x1.4800000000000p+3, 0x1.e800000000000p+4, -0x1.9000000000000p+1}";

struct Case {
    const char* name;
    TractorMode mode;
    double source_mass;
    double target_mass;
    bool target_is_ship;
    const char* source_after;
    const char* target_after;
};

// One tick of each mode from the same geometry (a Galaxy-weight source
// rotated 0.3 rad about Z, a lighter target 33 GU away).
const Case kCases[] = {
    {"hold", TractorMode::Hold, 120.0, 37.5, true, kSourceAt, kTargetAt},
    {"tow", TractorMode::Tow, 120.0, 37.5, true,
     "{0x1.8123c8eda4852p+0, -0x1.1dddf208c1242p+1, 0x1.7efd8fdd0f325p-1}",
     kTargetAt},
    {"pull", TractorMode::Pull, 120.0, 37.5, true,
     "{0x1.848f23b692149p+0, -0x1.1777c82304906p+1, 0x1.7bf63f743cc93p-1}",
     "{0x1.462d24ea2bf7cp+3, 0x1.e496500e01d36p+4, -0x1.8cc4ff9030a10p+1}"},
    {"push", TractorMode::Push, 120.0, 37.5, true,
     "{0x1.7b70dc496deb7p+0, -0x1.288837dcfb6fap+1, 0x1.8409c08bc336dp-1}",
     "{0x1.49d2db15d4084p+3, 0x1.eb69aff1fe2cap+4, -0x1.933b006fcf5f0p+1}"},
    {"dock1", TractorMode::DockStage1, 120.0, 37.5, true, kSourceAt,
     "{0x1.474541f744c98p+3, 0x1.e6a2866c00bafp+4, -0x1.8eb5330679da0p+1}"},
    {"dock2", TractorMode::DockStage2, 120.0, 37.5, true, kSourceAt,
     "{0x1.474541f744c98p+3, 0x1.e6a2866c00bafp+4, -0x1.8eb5330679da0p+1}"},
    // A massless source reads the fallback mass (0.05 GU/s); a 10-mass
    // target's 50 GU/s is capped at 20.
    {"pull_light_capped", TractorMode::Pull, 0.0, 10.0, true,
     "{0x1.800e0173dad75p+0, -0x1.1fe5ca14e6747p+1, 0x1.7ff398503e2b6p-1}",
     "{0x1.4543b75f41f3bp+3, 0x1.e2e1781502bd0p+4, -0x1.8b277f5848f17p+1}"},
    // Not a ShipClass: immovable (the source still moves).
    {"pull_notship", TractorMode::Pull, 120.0, 37.5, false,
     "{0x1.848f23b692149p+0, -0x1.1777c82304906p+1, 0x1.7bf63f743cc93p-1}",
     kTargetAt},
};

}  // namespace

TEST(TractorForce, EachModeOneTickIsPythonsLaw) {
    for (const Case& c : kCases) {
        SCOPED_TRACE(c.name);
        World w;
        const int64_t s = w.object(kSource, c.source_mass, 4.0, true, kRot);
        const int64_t t = w.object(kTarget, c.target_mass, 2.5,
                                   c.target_is_ship);
        const int64_t sys = w.tractor(s, t, c.mode);
        const TractorForceResult r = tractor_force_step(w.m, w.store, {s, t},
                                                        kDt);
        EXPECT_EQ(r.applied, 1);
        EXPECT_EQ(r.skipped, 0);
        EXPECT_EQ(w.at(s), c.source_after);
        EXPECT_EQ(w.at(t), c.target_after);
        // HOLD alone damps the target's velocity.
        EXPECT_EQ(r.zero_velocity,
                  (c.mode == TractorMode::Hold ? std::vector<int64_t>{t}
                                               : std::vector<int64_t>{}));
        // HOLD and TOW capture their geometry on the first step.
        if (c.mode == TractorMode::Hold || c.mode == TractorMode::Tow) {
            ASSERT_EQ(r.captures.size(), 1u);
            EXPECT_EQ(r.captures[0].system, sys);
            EXPECT_EQ(r.captures[0].kind, c.mode == TractorMode::Hold
                                              ? kEngageHold
                                              : kEngageTow);
            EXPECT_EQ(hexes(r.captures[0].point),
                      c.mode == TractorMode::Hold
                          ? kTargetAt
                          : "{0x1.209985ba369f1p+4, 0x1.cb3936baf9c7fp+4, "
                            "-0x1.f000000000000p+1}");
            EXPECT_EQ(w.m.get_i(sys, Field::engage_kind), r.captures[0].kind);
        } else {
            EXPECT_TRUE(r.captures.empty());
            EXPECT_EQ(w.m.get_i(sys, Field::engage_kind), kEngageNone);
        }
    }
}

// The second step reads the captured point (HOLD) / body offset (TOW), not
// where the target is now.
TEST(TractorForce, HoldAndTowFollowTheirCapturedGeometry) {
    struct Second {
        TractorMode mode;
        const char* source_after;
        const char* target_after;
    };
    const Second kSecond[] = {
        {TractorMode::Hold,
         "{0x1.0000000000000p+1, -0x1.0000000000000p+0, 0x1.0000000000000p-1}",
         "{0x1.7b25e0a5ec5f4p+3, 0x1.d2145694518e1p+4, -0x1.0c7a0779e9544p+1}"},
        {TractorMode::Tow,
         "{0x1.00b356c23cd49p+1, -0x1.f797eee526090p-1, 0x1.fe99527b8656dp-2}",
         "{0x1.7d5261866b5f5p+3, 0x1.d2f22e5289e3fp+4, -0x1.0bc8b94a278fdp+1}"},
    };
    for (const Second& c : kSecond) {
        World w;
        const int64_t s = w.object(kSource, 120.0, 4.0, true, kRot);
        const int64_t t = w.object(kTarget, 37.5, 2.5);
        w.tractor(s, t, c.mode);
        tractor_force_step(w.m, w.store, {s, t}, kDt);
        w.move(s, {2.0, -1.0, 0.5});
        w.move(t, {12.0, 29.0, -2.0});
        const TractorForceResult r = tractor_force_step(w.m, w.store, {s, t},
                                                        kDt);
        EXPECT_TRUE(r.captures.empty());
        EXPECT_EQ(w.at(s), c.source_after);
        EXPECT_EQ(w.at(t), c.target_after);
    }
}

// Within one step of its destination the target snaps onto it; coincident
// centres move nothing.
TEST(TractorForce, SnapsWithinOneStepAndSkipsCoincidentCentres) {
    World w;
    const int64_t s = w.object(kSource, 120.0, 4.0, true, kRot);
    const int64_t t = w.object({1.5, 7.35, 0.75}, 10.0, 2.5);
    w.tractor(s, t, TractorMode::Pull);
    tractor_force_step(w.m, w.store, {s}, kDt);
    EXPECT_EQ(w.at(t),
              "{0x1.8000000000000p+0, 0x1.d000000000000p+2, "
              "0x1.8000000000000p-1}");
    EXPECT_EQ(w.at(s),
              "{0x1.8000000000000p+0, -0x1.171c71c71c71cp+1, "
              "0x1.8000000000000p-1}");

    World c;
    const int64_t cs = c.object(kSource, 120.0, 4.0, true, kRot);
    const int64_t ct = c.object(kSource, 10.0, 2.5);
    c.tractor(cs, ct, TractorMode::Push);
    const TractorForceResult r = tractor_force_step(c.m, c.store, {cs}, kDt);
    EXPECT_EQ(r.applied, 1);
    EXPECT_TRUE(r.poses.empty());
    EXPECT_EQ(c.at(cs), kSourceAt);
    EXPECT_EQ(c.at(ct), kSourceAt);
}

// Nothing moves without a firing projector, a live target or a positive dt;
// the pose writes are listed in order (target, then source).
TEST(TractorForce, GatesAndThePoseLog) {
    World w;
    const int64_t s = w.object(kSource, 120.0, 4.0, true, kRot);
    const int64_t t = w.object(kTarget, 37.5, 2.5);
    const int64_t sys = w.tractor(s, t, TractorMode::Push);
    const int64_t beam = w.m.get_ids(sys, Field::_children)[0];

    EXPECT_EQ(tractor_force_step(w.m, w.store, {s}, 0.0).applied, 0);
    w.m.set_i(beam, Field::_firing, 0);
    EXPECT_EQ(tractor_force_step(w.m, w.store, {s}, kDt).applied, 0);
    w.m.set_i(beam, Field::_firing, 1);
    w.m.set_i(t, Field::_dead, 1);
    EXPECT_EQ(tractor_force_step(w.m, w.store, {s}, kDt).applied, 0);
    EXPECT_EQ(w.at(s), kSourceAt);
    EXPECT_EQ(w.at(t), kTargetAt);

    w.m.set_i(t, Field::_dead, 0);
    const TractorForceResult r = tractor_force_step(w.m, w.store, {s}, kDt);
    ASSERT_EQ(r.poses.size(), 2u);
    EXPECT_EQ(r.poses[0].object, t);
    EXPECT_EQ(hexes(r.poses[0].position),
              "{0x1.49d2db15d4084p+3, 0x1.eb69aff1fe2cap+4, "
              "-0x1.933b006fcf5f0p+1}");
    EXPECT_EQ(r.poses[1].object, s);
    EXPECT_EQ(w.at(s),
              "{0x1.7b70dc496deb7p+0, -0x1.288837dcfb6fap+1, "
              "0x1.8409c08bc336dp-1}");
}

// A tractor whose rows the mirror cannot name does nothing and is counted;
// the step goes on to the next ship.
TEST(TractorForce, AnUnnamedTargetIsSkippedAndCounted) {
    World w;
    const int64_t s = w.object(kSource, 120.0, 4.0, true, kRot);
    const int64_t t = w.object(kTarget, 37.5, 2.5);
    const int64_t sys = w.tractor(s, t, TractorMode::Push);
    w.m.set_ref(w.m.get_ids(sys, Field::_children)[0], Field::_target,
                kRefUnrepresentable);
    const int64_t s2 = w.object({50.0, 0.0, 0.0}, 120.0, 4.0);
    const int64_t t2 = w.object({50.0, 20.0, 0.0}, 120.0, 4.0);
    w.tractor(s2, t2, TractorMode::Push);
    const TractorForceResult r = tractor_force_step(w.m, w.store, {s, s2},
                                                    kDt);
    EXPECT_EQ(r.skipped, 1);
    EXPECT_EQ(r.applied, 1);
    EXPECT_EQ(w.at(s), kSourceAt);
    EXPECT_NE(w.at(t2), hexes({50.0, 20.0, 0.0}));
}

// One firing projector's target the mirror cannot read (a stub IsDead, no
// transform) is skipped and counted alone; the ship's other tractored
// target is still moved (Python's per-emitter `continue`).
TEST(TractorForce, OneBadTargetSkipsOnlyItself) {
    for (const bool stub : {true, false}) {
        World w;
        const int64_t s = w.object(kSource, 120.0, 4.0, true, kRot);
        const int64_t bad = w.object({0.0, 40.0, 0.0}, 37.5, 2.5);
        const int64_t t = w.object(kTarget, 37.5, 2.5);
        const int64_t sys = w.tractor(s, bad, TractorMode::Push);
        const int64_t b2 = w.m.register_row(Kind::Subsystem);
        w.m.set_i(b2, Field::weapon_kind, 7);
        w.m.set_ref(b2, Field::_parent_subsystem, sys);
        w.m.set_i(b2, Field::_firing, 1);
        w.m.set_ref(b2, Field::_target, t);
        w.m.set_ids(sys, Field::_children,
                    {w.m.get_ids(sys, Field::_children)[0], b2});
        if (stub) {
            w.m.set_i(bad, Field::has_real_is_dead, 0);
        } else {
            const ObjectRow* o = w.m.object(bad);
            w.store.free(static_cast<uint32_t>(o->xform_index),
                         static_cast<uint32_t>(o->xform_gen));
        }
        const TractorForceResult r = tractor_force_step(w.m, w.store, {s},
                                                        kDt);
        EXPECT_EQ(r.skipped, 1) << stub;
        EXPECT_EQ(r.applied, 1) << stub;
        EXPECT_EQ(w.at(t),
                  "{0x1.49d2db15d4084p+3, 0x1.eb69aff1fe2cap+4, "
                  "-0x1.933b006fcf5f0p+1}")
            << stub;
        EXPECT_EQ(w.at(s),
                  "{0x1.7b70dc496deb7p+0, -0x1.288837dcfb6fap+1, "
                  "0x1.8409c08bc336dp-1}")
            << stub;
    }
}

// The stand-off is the SCALED radii (world_radius): a target of base 2.5 at
// scale 2.0 tows exactly like one of base 5.0; a NaN scale is the base.
TEST(TractorForce, StandoffUsesScaledRadius) {
    for (const TractorMode mode : {TractorMode::Pull, TractorMode::DockStage1}) {
        auto run = [&](double base, bool set_scale, double scale) {
            World w;
            const int64_t s = w.object(kSource, 120.0, 4.0, true, kRot);
            const int64_t t = w.object({11.5, -2.25, 0.75}, 37.5, base);
            if (set_scale) w.m.set_f(t, Field::_scale, scale);
            w.tractor(s, t, mode);
            tractor_force_step(w.m, w.store, {s, t}, kDt);
            return std::make_pair(w.at(s), w.at(t));
        };
        const auto a = run(2.5, true, 2.0);
        const auto b = run(5.0, false, 0.0);
        const auto c = run(2.5, true, std::numeric_limits<double>::quiet_NaN());
        const auto d = run(2.5, false, 0.0);
        EXPECT_EQ(a, b);
        EXPECT_EQ(c, d);
    }
}
