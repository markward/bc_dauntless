// native/tests/renderer/torpedo_anim_test.cc
#include <gtest/gtest.h>
#include <glm/glm.hpp>

#include <cmath>
#include <cstdint>
#include <set>

#include "renderer/torpedo_anim.h"
#include "renderer/frame.h"

namespace {
constexpr float kPi = 3.14159265358979323846f;
}  // namespace

// ─────────────────────────────────────────────────────────────────────────
// Mapping lock-test — THIS is the provisional pin (weapon-firing-mechanics.md
// §5.5). If a future RE Q&A re-pins the table, update map_torpedo_params AND
// this test together.
// ─────────────────────────────────────────────────────────────────────────
// Args 13/14 pinned on the exe by changing one at a time and filming
// (stbc-oracle bible §14.2): 13 is the flare LENGTH (0.7 -> 2.5 took the
// streaks from 291 to 514 px), 14 the flare LIFESPAN (0.4 -> 100 s made
// them persist and pile up). The earlier provisional mapping had them the
// other way round, and drew the streaks at a quarter of their length.
TEST(TorpedoAnimMapping, PhotonDescriptorMatchesTheVerifiedArgumentRoles) {
    renderer::TorpedoDescriptor d;
    d.core_size_a   = 0.2f;
    d.core_size_b   = 1.2f;
    d.glow_size_a   = 3.0f;
    d.glow_size_b   = 0.3f;
    d.glow_size_c   = 0.6f;
    d.num_flares    = 8;
    d.flares_size_a = 0.7f;
    d.flares_size_b = 0.4f;

    const renderer::TorpedoAnimParams p = renderer::map_torpedo_params(d);
    EXPECT_FLOAT_EQ(p.core_half_size, 0.2f);
    EXPECT_FLOAT_EQ(p.spin_rate, 1.2f);
    EXPECT_FLOAT_EQ(p.pulse_rate, 3.0f);
    EXPECT_FLOAT_EQ(p.scale_lo, 0.3f);
    EXPECT_FLOAT_EQ(p.scale_hi, 0.6f);
    EXPECT_FLOAT_EQ(p.clone_scale, 0.6f);
    EXPECT_FLOAT_EQ(p.flare_period, 0.4f);      // arg 14: lifespan, seconds
    EXPECT_FLOAT_EQ(p.flare_half_size, 0.7f);   // arg 13: length, GU
}

TEST(TorpedoAnimMapping, FlareStreakIsTwoToOneAlongItsAxis) {
    // TorpedoFlares.tga is a 32 x 64 vertical streak; the quad keeps that
    // aspect: full length along the streak, half as wide across it.
    EXPECT_FLOAT_EQ(renderer::torpedo_anim_detail::kFlareAspect, 0.5f);
}

// ─────────────────────────────────────────────────────────────────────────
// glow_pulse_scale
// ─────────────────────────────────────────────────────────────────────────
TEST(TorpedoAnimPulse, AgeZeroReturnsLo) {
    EXPECT_NEAR(renderer::glow_pulse_scale(0.0f, 1.2f, 0.3f, 0.6f), 0.3f, 1e-5f);
}

TEST(TorpedoAnimPulse, NegativeAgeClampsToZeroAndReturnsLo) {
    EXPECT_NEAR(renderer::glow_pulse_scale(-5.0f, 1.2f, 0.3f, 0.6f), 0.3f, 1e-5f);
}

TEST(TorpedoAnimPulse, StaysWithinLoHiRangeOverManySamples) {
    const float lo = 0.3f, hi = 0.6f, rate = 1.2f;
    for (int i = 0; i < 500; ++i) {
        const float age = static_cast<float>(i) * 0.017f;
        const float v = renderer::glow_pulse_scale(age, rate, lo, hi);
        EXPECT_GE(v, lo - 1e-4f) << "age=" << age;
        EXPECT_LE(v, hi + 1e-4f) << "age=" << age;
    }
}

TEST(TorpedoAnimPulse, SweepsLoToHiToLoWithinOnePeriod) {
    // One pi-wrapped period is pi / rate seconds.
    const float lo = 0.3f, hi = 0.6f, rate = 1.2f;
    const float period = kPi / rate;
    const float mid = period * 0.5f;  // phase == pi/2 -> sin == 1 -> hi
    EXPECT_NEAR(renderer::glow_pulse_scale(0.0f, rate, lo, hi), lo, 1e-4f);
    EXPECT_NEAR(renderer::glow_pulse_scale(mid, rate, lo, hi), hi, 1e-3f);
    EXPECT_NEAR(renderer::glow_pulse_scale(period, rate, lo, hi), lo, 1e-3f);
    // Monotone rise on the first quarter, monotone fall on the last quarter.
    const float a0 = renderer::glow_pulse_scale(0.0f, rate, lo, hi);
    const float a1 = renderer::glow_pulse_scale(mid * 0.5f, rate, lo, hi);
    const float a2 = renderer::glow_pulse_scale(mid, rate, lo, hi);
    EXPECT_LT(a0, a1);
    EXPECT_LT(a1, a2);
    const float b0 = renderer::glow_pulse_scale(mid, rate, lo, hi);
    const float b1 = renderer::glow_pulse_scale(mid + mid * 0.5f, rate, lo, hi);
    const float b2 = renderer::glow_pulse_scale(period, rate, lo, hi);
    EXPECT_GT(b0, b1);
    EXPECT_GT(b1, b2);
}

TEST(TorpedoAnimPulse, NeverNegativeEvenWithLoGreaterThanHi) {
    // fabs guard (BC's winding-order guard) must keep the result non-negative
    // even when the caller passes lo > hi.
    for (int i = 0; i < 200; ++i) {
        const float age = static_cast<float>(i) * 0.031f;
        const float v = renderer::glow_pulse_scale(age, 1.2f, 0.9f, 0.1f);
        EXPECT_GE(v, 0.0f) << "age=" << age;
    }
}

// ─────────────────────────────────────────────────────────────────────────
// flare_trapezoid
// ─────────────────────────────────────────────────────────────────────────
TEST(TorpedoAnimTrapezoid, RisingEdgeAtU015) {
    EXPECT_NEAR(renderer::flare_trapezoid(0.15f), 0.5f, 1e-4f);
}

TEST(TorpedoAnimTrapezoid, PlateauAtU05) {
    EXPECT_NEAR(renderer::flare_trapezoid(0.5f), 1.0f, 1e-4f);
}

TEST(TorpedoAnimTrapezoid, FallingEdgeAtU085) {
    EXPECT_NEAR(renderer::flare_trapezoid(0.85f), 0.5f, 1e-4f);
}

TEST(TorpedoAnimTrapezoid, ZeroAtU0) {
    EXPECT_NEAR(renderer::flare_trapezoid(0.0f), 0.0f, 1e-6f);
}

TEST(TorpedoAnimTrapezoid, NearlyZeroApproachingU1) {
    const float v = renderer::flare_trapezoid(0.9999f);
    EXPECT_GT(v, 0.0f);
    EXPECT_LT(v, 0.001f);
}

TEST(TorpedoAnimTrapezoid, ZeroAtU1IfPassed) {
    EXPECT_NEAR(renderer::flare_trapezoid(1.0f), 0.0f, 1e-6f);
}

TEST(TorpedoAnimTrapezoid, ContinuousAtBoundary03) {
    const float left  = renderer::flare_trapezoid(0.3f - 1e-4f);
    const float right = renderer::flare_trapezoid(0.3f);
    EXPECT_NEAR(left, right, 1e-3f);
}

TEST(TorpedoAnimTrapezoid, ContinuousAtBoundary07) {
    const float left  = renderer::flare_trapezoid(0.7f - 1e-4f);
    const float right = renderer::flare_trapezoid(0.7f);
    EXPECT_NEAR(left, right, 1e-3f);
}

// ─────────────────────────────────────────────────────────────────────────
// hash01
// ─────────────────────────────────────────────────────────────────────────
TEST(TorpedoAnimHash, DeterministicAcrossCalls) {
    const float a = renderer::hash01(42u, 3u, 7u);
    const float b = renderer::hash01(42u, 3u, 7u);
    EXPECT_FLOAT_EQ(a, b);
}

TEST(TorpedoAnimHash, DiffersAcrossIndex) {
    const float a = renderer::hash01(42u, 0u, 7u);
    const float b = renderer::hash01(42u, 1u, 7u);
    EXPECT_NE(a, b);
}

TEST(TorpedoAnimHash, DiffersAcrossId) {
    const float a = renderer::hash01(1u, 0u, 7u);
    const float b = renderer::hash01(2u, 0u, 7u);
    EXPECT_NE(a, b);
}

TEST(TorpedoAnimHash, WorstCaseFinalizerOutputStaysBelowOne) {
    // id = 0x876C6E7A with index = 0, salt = 0 drives the finalized integer
    // hash to exactly 0xFFFFFFFF (computed by inverting the finalizer mix).
    // The naive `static_cast<float>(h) / 4294967296.0f` conversion rounds
    // float32(0xFFFFFFFF) UP to 4294967296.0f (24-bit mantissa; ulp = 256 at
    // that magnitude) and returns exactly 1.0f, violating the [0, 1) contract.
    // The top-24-bit conversion `(h >> 8) * (1/2^24)` is exact and < 1.
    const float v = renderer::hash01(0x876C6E7Au, 0u, 0u);
    EXPECT_GE(v, 0.0f);
    EXPECT_LT(v, 1.0f);
    // The conversion expression itself, at the absolute worst case: every one
    // of the top 24 bits set is still strictly below 1.
    const float worst = static_cast<float>(0xFFFFFFFFu >> 8) * (1.0f / 16777216.0f);
    EXPECT_LT(worst, 1.0f);
}

TEST(TorpedoAnimHash, AllOutputsInZeroOneOverManySamples) {
    for (uint32_t id = 0; id < 20; ++id) {
        for (uint32_t index = 0; index < 20; ++index) {
            const float v = renderer::hash01(id, index, 5u);
            EXPECT_GE(v, 0.0f);
            EXPECT_LT(v, 1.0f);
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────
// flare_rotation
// ─────────────────────────────────────────────────────────────────────────
namespace {
bool is_rotation_matrix(const glm::mat3& r, float eps) {
    const glm::mat3 rt_r = glm::transpose(r) * r;
    const glm::mat3 identity(1.0f);
    for (int c = 0; c < 3; ++c) {
        for (int row = 0; row < 3; ++row) {
            if (std::fabs(rt_r[c][row] - identity[c][row]) > eps) return false;
        }
    }
    const float det = glm::determinant(r);
    return std::fabs(det - 1.0f) <= eps;
}
}  // namespace

TEST(TorpedoAnimFlareRotation, DeterministicPerIdAndIndex) {
    const glm::mat3 a = renderer::flare_rotation(7u, 2u);
    const glm::mat3 b = renderer::flare_rotation(7u, 2u);
    for (int c = 0; c < 3; ++c)
        for (int row = 0; row < 3; ++row)
            EXPECT_FLOAT_EQ(a[c][row], b[c][row]);
}

TEST(TorpedoAnimFlareRotation, IsAValidRotationMatrix) {
    const glm::mat3 r = renderer::flare_rotation(11u, 4u);
    EXPECT_TRUE(is_rotation_matrix(r, 1e-3f));
}

TEST(TorpedoAnimFlareRotation, DiffersAcrossFlareIndices) {
    const glm::mat3 a = renderer::flare_rotation(11u, 0u);
    const glm::mat3 b = renderer::flare_rotation(11u, 1u);
    bool any_diff = false;
    for (int c = 0; c < 3 && !any_diff; ++c)
        for (int row = 0; row < 3 && !any_diff; ++row)
            if (std::fabs(a[c][row] - b[c][row]) > 1e-4f) any_diff = true;
    EXPECT_TRUE(any_diff);
}

// ─────────────────────────────────────────────────────────────────────────
// torpedo_root_frame — the billboard-root basis TorpedoPass draws with.
// Extracted from render() (Task 6 review finding 2) so the axis math is
// testable without a GL context.
// ─────────────────────────────────────────────────────────────────────────
TEST(TorpedoAnimRootFrame, UnspunFrameFacesCameraAndIsOrthonormal) {
    const glm::vec3 cam_pos(0.0f, 0.0f, 100.0f);
    const glm::vec3 world_pos(0.0f, 0.0f, 0.0f);
    const glm::vec3 cam_up(0.0f, 1.0f, 0.0f);
    const glm::mat3 r = renderer::torpedo_root_frame(
        cam_pos, world_pos, cam_up, /*age=*/0.0f, /*spin_rate=*/0.0f);
    // Column 2 (Z_r) points from world_pos toward cam_pos: +Z here.
    EXPECT_NEAR(r[2].x, 0.0f, 1e-5f);
    EXPECT_NEAR(r[2].y, 0.0f, 1e-5f);
    EXPECT_NEAR(r[2].z, 1.0f, 1e-5f);
    EXPECT_TRUE(is_rotation_matrix(r, 1e-4f));  // orthonormal, det +1
}

TEST(TorpedoAnimRootFrame, QuarterTurnSpinRotatesXIntoPlusY) {
    // LOCKS the composition order/sign: with the right-handed basis
    // (Y_r0 = cross(Z_r, X_r0)) and glm::rotate's counterclockwise-about-
    // axis convention, age*spin_rate = +pi/2 about Z_r carries X_r0 onto
    // +Y_r0 (and Y_r0 onto -X_r0).
    const glm::vec3 cam_pos(0.0f, 0.0f, 100.0f);
    const glm::vec3 world_pos(0.0f, 0.0f, 0.0f);
    const glm::vec3 cam_up(0.0f, 1.0f, 0.0f);
    const glm::mat3 unspun = renderer::torpedo_root_frame(
        cam_pos, world_pos, cam_up, 0.0f, 0.0f);
    const float rate = 1.0f;
    const float age = kPi / 2.0f;  // age * rate == pi/2
    const glm::mat3 spun = renderer::torpedo_root_frame(
        cam_pos, world_pos, cam_up, age, rate);
    for (int row = 0; row < 3; ++row) {
        EXPECT_NEAR(spun[0][row],  unspun[1][row], 1e-4f) << "row=" << row;
        EXPECT_NEAR(spun[1][row], -unspun[0][row], 1e-4f) << "row=" << row;
        EXPECT_NEAR(spun[2][row],  unspun[2][row], 1e-4f) << "row=" << row;
    }
    EXPECT_TRUE(is_rotation_matrix(spun, 1e-4f));
}

TEST(TorpedoAnimRootFrame, DegenerateCameraAtTorpedoReturnsIdentityNoNaN) {
    const glm::vec3 pos(5.0f, -3.0f, 12.0f);
    const glm::mat3 r = renderer::torpedo_root_frame(
        pos, pos, glm::vec3(0.0f, 1.0f, 0.0f), 2.0f, 1.2f);
    const glm::mat3 identity(1.0f);
    for (int c = 0; c < 3; ++c) {
        for (int row = 0; row < 3; ++row) {
            EXPECT_FALSE(std::isnan(r[c][row])) << "c=" << c << " row=" << row;
            EXPECT_NEAR(r[c][row], identity[c][row], 1e-6f);
        }
    }
}

TEST(TorpedoAnimRootFrame, CamUpParallelToViewAxisStillOrthonormalNoNaN) {
    // Camera straight above the torpedo with cam_up parallel to the view
    // axis: cross(cam_up, Z_r) degenerates; the fallback up axis must keep
    // the frame orthonormal and NaN-free.
    const glm::vec3 cam_pos(0.0f, 0.0f, 50.0f);
    const glm::vec3 world_pos(0.0f, 0.0f, 0.0f);
    const glm::vec3 cam_up(0.0f, 0.0f, 1.0f);  // parallel to Z_r
    const glm::mat3 r = renderer::torpedo_root_frame(
        cam_pos, world_pos, cam_up, 0.7f, 1.2f);
    for (int c = 0; c < 3; ++c)
        for (int row = 0; row < 3; ++row)
            EXPECT_FALSE(std::isnan(r[c][row])) << "c=" << c << " row=" << row;
    EXPECT_TRUE(is_rotation_matrix(r, 1e-4f));
    // View axis unchanged by the fallback.
    EXPECT_NEAR(r[2].z, 1.0f, 1e-5f);
}

// ─────────────────────────────────────────────────────────────────────────
// flare_basis — per-flare quad basis: root frame composed with the fixed
// random per-flare rotation.
// ─────────────────────────────────────────────────────────────────────────
TEST(TorpedoAnimFlareBasis, EqualsRootTimesFlareRotation) {
    const glm::mat3 root = renderer::torpedo_root_frame(
        glm::vec3(10.0f, 20.0f, 30.0f), glm::vec3(0.0f),
        glm::vec3(0.0f, 1.0f, 0.0f), 0.4f, 1.2f);
    const glm::mat3 expected = root * renderer::flare_rotation(42u, 3u);
    const glm::mat3 actual = renderer::flare_basis(root, 42u, 3u);
    for (int c = 0; c < 3; ++c)
        for (int row = 0; row < 3; ++row)
            EXPECT_FLOAT_EQ(actual[c][row], expected[c][row]);
}

TEST(TorpedoAnimFlareBasis, IsOrthonormal) {
    const glm::mat3 root = renderer::torpedo_root_frame(
        glm::vec3(0.0f, 0.0f, 100.0f), glm::vec3(0.0f),
        glm::vec3(0.0f, 1.0f, 0.0f), 1.3f, 1.2f);
    const glm::mat3 fb = renderer::flare_basis(root, 7u, 5u);
    EXPECT_TRUE(is_rotation_matrix(fb, 1e-3f));
}

TEST(TorpedoAnimFlareBasis, DiffersAcrossFlareIndices) {
    const glm::mat3 root = renderer::torpedo_root_frame(
        glm::vec3(0.0f, 0.0f, 100.0f), glm::vec3(0.0f),
        glm::vec3(0.0f, 1.0f, 0.0f), 0.0f, 0.0f);
    const glm::mat3 a = renderer::flare_basis(root, 11u, 0u);
    const glm::mat3 b = renderer::flare_basis(root, 11u, 1u);
    bool any_diff = false;
    for (int c = 0; c < 3 && !any_diff; ++c)
        for (int row = 0; row < 3 && !any_diff; ++row)
            if (std::fabs(a[c][row] - b[c][row]) > 1e-4f) any_diff = true;
    EXPECT_TRUE(any_diff);
}

// ─────────────────────────────────────────────────────────────────────────
// bolt_align_rotation
// ─────────────────────────────────────────────────────────────────────────
TEST(TorpedoAnimBoltAlign, MapsPlusYToForwardPlusX) {
    const glm::vec3 forward(1.0f, 0.0f, 0.0f);
    const glm::mat3 r = renderer::bolt_align_rotation(forward);
    const glm::vec3 mapped = r * glm::vec3(0.0f, 1.0f, 0.0f);
    EXPECT_NEAR(mapped.x, forward.x, 1e-4f);
    EXPECT_NEAR(mapped.y, forward.y, 1e-4f);
    EXPECT_NEAR(mapped.z, forward.z, 1e-4f);
    EXPECT_TRUE(is_rotation_matrix(r, 1e-3f));
}

TEST(TorpedoAnimBoltAlign, MapsPlusYToForwardMinusZ) {
    const glm::vec3 forward(0.0f, 0.0f, -1.0f);
    const glm::mat3 r = renderer::bolt_align_rotation(forward);
    const glm::vec3 mapped = r * glm::vec3(0.0f, 1.0f, 0.0f);
    EXPECT_NEAR(mapped.x, forward.x, 1e-4f);
    EXPECT_NEAR(mapped.y, forward.y, 1e-4f);
    EXPECT_NEAR(mapped.z, forward.z, 1e-4f);
    EXPECT_TRUE(is_rotation_matrix(r, 1e-3f));
}

TEST(TorpedoAnimBoltAlign, MapsPlusYToNormalizedForward123) {
    const glm::vec3 forward = glm::normalize(glm::vec3(1.0f, 2.0f, 3.0f));
    const glm::mat3 r = renderer::bolt_align_rotation(forward);
    const glm::vec3 mapped = r * glm::vec3(0.0f, 1.0f, 0.0f);
    EXPECT_NEAR(mapped.x, forward.x, 1e-4f);
    EXPECT_NEAR(mapped.y, forward.y, 1e-4f);
    EXPECT_NEAR(mapped.z, forward.z, 1e-4f);
    EXPECT_TRUE(is_rotation_matrix(r, 1e-3f));
}

TEST(TorpedoAnimBoltAlign, DegeneratePlusYIsIdentity) {
    const glm::mat3 r = renderer::bolt_align_rotation(glm::vec3(0.0f, 1.0f, 0.0f));
    const glm::mat3 identity(1.0f);
    for (int c = 0; c < 3; ++c)
        for (int row = 0; row < 3; ++row)
            EXPECT_NEAR(r[c][row], identity[c][row], 1e-4f);
}

TEST(TorpedoAnimBoltAlign, DegenerateMinusYMapsToMinusYAndIsValidRotation) {
    const glm::mat3 r = renderer::bolt_align_rotation(glm::vec3(0.0f, -1.0f, 0.0f));
    const glm::vec3 mapped = r * glm::vec3(0.0f, 1.0f, 0.0f);
    EXPECT_NEAR(mapped.x, 0.0f, 1e-4f);
    EXPECT_NEAR(mapped.y, -1.0f, 1e-4f);
    EXPECT_NEAR(mapped.z, 0.0f, 1e-4f);
    EXPECT_TRUE(is_rotation_matrix(r, 1e-3f));
}

// ─────────────────────────────────────────────────────────────────────────
// build_bolt_mesh — a closed teardrop, not a tube
//
// BC's disruptor bolt is a teardrop: pointed tail, widest near the nose,
// rounded nose (Mark, live; the oracle's stock frames). Its full width is the
// CreateDisruptorModel `width` argument — the stock 1.8 × 0.15 bolt measures
// 12.4:1 (stbc-oracle bible §14.3, 87 × 7 px) — so the unit mesh's maximum
// RADIUS is 0.5. The profile constants (widest-at, tail power) are a
// calibration surface: re-pin them from the frames, not from taste.
// ─────────────────────────────────────────────────────────────────────────
TEST(TorpedoAnimBoltProfile, PointedAtBothEnds) {
    EXPECT_NEAR(renderer::bolt_teardrop_radius(0.0f), 0.0f, 1e-6f);
    EXPECT_NEAR(renderer::bolt_teardrop_radius(1.0f), 0.0f, 1e-6f);
}

TEST(TorpedoAnimBoltProfile, WidestIsHalfAUnitNearTheNose) {
    const float u_w = renderer::torpedo_anim_detail::kBoltWidestAt;
    EXPECT_GT(u_w, 0.5f);                                   // nose end is +y
    EXPECT_NEAR(renderer::bolt_teardrop_radius(u_w), 0.5f, 1e-6f);
    // Monotone up to the widest point, monotone down after it.
    float prev = -1.0f;
    for (int i = 0; i <= 100; ++i) {
        const float u = u_w * static_cast<float>(i) / 100.0f;
        const float r = renderer::bolt_teardrop_radius(u);
        EXPECT_GE(r, prev - 1e-6f) << "u=" << u;
        EXPECT_LE(r, 0.5f + 1e-6f);
        prev = r;
    }
    for (int i = 0; i <= 100; ++i) {
        const float u = u_w + (1.0f - u_w) * static_cast<float>(i) / 100.0f;
        const float r = renderer::bolt_teardrop_radius(u);
        EXPECT_LE(r, prev + 1e-6f) << "u=" << u;
        prev = r;
    }
}

TEST(TorpedoAnimBoltMesh, DefaultVertexCountIsRingsTimesSegments) {
    const renderer::BoltMesh mesh = renderer::build_bolt_mesh();
    EXPECT_EQ(mesh.vertices.size(),
              static_cast<size_t>(renderer::torpedo_anim_detail::kBoltRings) * 12u);
}

TEST(TorpedoAnimBoltMesh, SpansMinusHalfToPlusHalfAlongY) {
    const int segments = 12;
    const renderer::BoltMesh mesh = renderer::build_bolt_mesh(segments);
    float y_min = 1.0f, y_max = -1.0f;
    for (const auto& v : mesh.vertices) { y_min = std::min(y_min, v.y); y_max = std::max(y_max, v.y); }
    EXPECT_NEAR(y_min, -0.5f, 1e-4f);
    EXPECT_NEAR(y_max, 0.5f, 1e-4f);
}

TEST(TorpedoAnimBoltMesh, WidestRingIsForwardOfCentreAndHalfWide) {
    const int segments = 12;
    const renderer::BoltMesh mesh = renderer::build_bolt_mesh(segments);
    float best_r = 0.0f, best_y = 0.0f;
    for (const auto& v : mesh.vertices) {
        const float r = std::sqrt(v.x * v.x + v.z * v.z);
        if (r > best_r) { best_r = r; best_y = v.y; }
    }
    EXPECT_NEAR(best_r, 0.5f, 1e-3f);   // full width == the `width` argument
    EXPECT_GT(best_y, 0.0f);            // the fat end leads (+y = velocity)
}

TEST(TorpedoAnimBoltMesh, TailAndNoseRingsCollapseToPoints) {
    const int segments = 12;
    const renderer::BoltMesh mesh = renderer::build_bolt_mesh(segments);
    const int rings = renderer::torpedo_anim_detail::kBoltRings;
    for (int s = 0; s < segments; ++s) {
        const glm::vec3& tail = mesh.vertices[s];
        const glm::vec3& nose = mesh.vertices[(rings - 1) * segments + s];
        EXPECT_NEAR(std::sqrt(tail.x * tail.x + tail.z * tail.z), 0.0f, 1e-5f);
        EXPECT_NEAR(std::sqrt(nose.x * nose.x + nose.z * nose.z), 0.0f, 1e-5f);
    }
}

TEST(TorpedoAnimBoltMesh, IndexCountMatchesBandsTimesSegmentsTimesSix) {
    const int segments = 12;
    const renderer::BoltMesh mesh = renderer::build_bolt_mesh(segments);
    const int bands = renderer::torpedo_anim_detail::kBoltRings - 1;
    EXPECT_EQ(mesh.indices.size(), static_cast<size_t>(bands * segments * 6));
}

TEST(TorpedoAnimBoltMesh, AllIndicesInBounds) {
    const renderer::BoltMesh mesh = renderer::build_bolt_mesh();
    for (uint32_t idx : mesh.indices) {
        EXPECT_LT(idx, mesh.vertices.size());
    }
}
