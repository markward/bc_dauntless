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
TEST(TorpedoAnimMapping, PhotonDescriptorLocksProvisionalFieldAssignment) {
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
    EXPECT_FLOAT_EQ(p.flare_period, 0.7f);
    EXPECT_FLOAT_EQ(p.flare_half_size, 0.16f);  // 0.4 * 0.4
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
// build_bolt_mesh
// ─────────────────────────────────────────────────────────────────────────
TEST(TorpedoAnimBoltMesh, DefaultVertexCountIs48) {
    const renderer::BoltMesh mesh = renderer::build_bolt_mesh();
    EXPECT_EQ(mesh.vertices.size(), 48u);  // 12 segments * 4 rings
}

TEST(TorpedoAnimBoltMesh, RingYValuesMatchSpec) {
    const int segments = 12;
    const renderer::BoltMesh mesh = renderer::build_bolt_mesh(segments);
    const float expected_y[4] = {-0.5f, -1.0f / 6.0f, 1.0f / 6.0f, 0.5f};
    for (int ring = 0; ring < 4; ++ring) {
        for (int s = 0; s < segments; ++s) {
            const glm::vec3& v = mesh.vertices[ring * segments + s];
            EXPECT_NEAR(v.y, expected_y[ring], 1e-4f) << "ring=" << ring << " s=" << s;
        }
    }
}

TEST(TorpedoAnimBoltMesh, RingRadiiMatchAuditedProfile) {
    const int segments = 12;
    const renderer::BoltMesh mesh = renderer::build_bolt_mesh(segments);
    const float expected_radius[4] = {0.9927f, 0.9727f, 0.9273f, 0.7273f};
    for (int ring = 0; ring < 4; ++ring) {
        float max_xz = 0.0f;
        for (int s = 0; s < segments; ++s) {
            const glm::vec3& v = mesh.vertices[ring * segments + s];
            max_xz = std::max(max_xz, std::sqrt(v.x * v.x + v.z * v.z));
        }
        EXPECT_NEAR(max_xz, expected_radius[ring], 1e-3f) << "ring=" << ring;
    }
}

TEST(TorpedoAnimBoltMesh, NarrowRingIsAtForwardPlusY) {
    const int segments = 12;
    const renderer::BoltMesh mesh = renderer::build_bolt_mesh(segments);
    // Ring 3 is y = +0.5, radius 0.7273 (narrow end forward).
    const glm::vec3& v = mesh.vertices[3 * segments + 0];
    EXPECT_NEAR(v.y, 0.5f, 1e-4f);
    EXPECT_NEAR(std::sqrt(v.x * v.x + v.z * v.z), 0.7273f, 1e-3f);
}

TEST(TorpedoAnimBoltMesh, IndexCountMatchesThreeBandsTimesSegmentsTimesSix) {
    const int segments = 12;
    const renderer::BoltMesh mesh = renderer::build_bolt_mesh(segments);
    EXPECT_EQ(mesh.indices.size(), static_cast<size_t>(3 * segments * 6));
}

TEST(TorpedoAnimBoltMesh, AllIndicesInBounds) {
    const renderer::BoltMesh mesh = renderer::build_bolt_mesh();
    for (uint32_t idx : mesh.indices) {
        EXPECT_LT(idx, mesh.vertices.size());
    }
}
