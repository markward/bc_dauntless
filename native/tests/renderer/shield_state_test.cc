#include <gtest/gtest.h>
#include <cmath>
#include "renderer/shield_state.h"
#include "scenegraph/instance.h"

using namespace renderer;

namespace {
ShieldState make_state(float decay = 1.0f) {
    ShieldState s;
    s.mode = ShieldMode::Ellipsoid;
    s.decay_seconds = decay;
    s.default_color = glm::vec4(0.2f, 0.4f, 1.0f, 1.0f);
    s.aabb_center = glm::vec3(0.0f);
    s.aabb_half_extents = glm::vec3(10.0f);
    return s;
}
}

TEST(ShieldState, PushHitStoresColorAndPoint) {
    auto s = make_state();
    s.push_hit({1.0f, 2.0f, 3.0f}, {0.5f, 0.6f, 0.7f, 1.0f}, 1.0f, 0.0, 2);
    EXPECT_EQ(s.active_count(), 1u);
    // Find the populated slot (push_hit may pick any empty slot).
    int found = -1;
    for (std::size_t i = 0; i < ShieldState::MaxHits; ++i) {
        if (s.slot(i).current_intensity > 0.0f) { found = static_cast<int>(i); break; }
    }
    ASSERT_NE(found, -1);
    EXPECT_EQ(s.slot(found).point_world, glm::vec3(1.0f, 2.0f, 3.0f));
    EXPECT_FLOAT_EQ(s.slot(found).color_rgba.r, 0.5f);
    EXPECT_EQ(s.slot(found).texture_index, 2);
}

TEST(ShieldState, ZeroRgbaSubstitutesDefaultColor) {
    auto s = make_state();
    s.push_hit({0,0,0}, {0,0,0,0}, 1.0f, 0.0, 0);
    int found = -1;
    for (std::size_t i = 0; i < ShieldState::MaxHits; ++i) {
        if (s.slot(i).current_intensity > 0.0f) { found = static_cast<int>(i); break; }
    }
    ASSERT_NE(found, -1);
    EXPECT_EQ(s.slot(found).color_rgba, s.default_color);
}

TEST(ShieldState, IntensityDecaysExponentiallyWithDecaySeconds) {
    auto s = make_state(/*decay=*/2.0f);
    s.push_hit({0,0,0}, {1,1,1,1}, 1.0f, 0.0, 0);
    s.tick(/*now=*/2.0);  // one decay period
    int found = -1;
    for (std::size_t i = 0; i < ShieldState::MaxHits; ++i) {
        if (s.slot(i).current_intensity > 0.0f) { found = static_cast<int>(i); break; }
    }
    ASSERT_NE(found, -1);
    EXPECT_NEAR(s.slot(found).current_intensity, std::exp(-1.0f), 1e-5);
}

TEST(ShieldState, ExpiredSlotsBecomeEmpty) {
    auto s = make_state(/*decay=*/0.1f);
    s.push_hit({0,0,0}, {1,1,1,1}, 1.0f, 0.0, 0);
    s.tick(/*now=*/10.0);  // far past decay
    EXPECT_EQ(s.active_count(), 0u);
}

TEST(ShieldState, FullBufferEvictsDimmestHit) {
    auto s = make_state(/*decay=*/100.0f);
    // Fill all 8 slots with hits at t=0..7 seconds (slot 0 is dimmest at t=8).
    for (int i = 0; i < 8; ++i) {
        s.push_hit({float(i), 0, 0}, {1, 1, 1, 1}, 1.0f, double(i), 0);
    }
    s.tick(/*now=*/8.0);
    // 9th hit — the dimmest is the one pushed at t=0 (longest decayed).
    s.push_hit({99, 0, 0}, {1, 1, 1, 1}, 1.0f, 8.0, 0);
    EXPECT_EQ(s.active_count(), 8u);
    // Verify the x=0 hit is gone, x=99 is present.
    bool found_zero = false, found_99 = false;
    for (std::size_t i = 0; i < ShieldState::MaxHits; ++i) {
        if (s.slot(i).current_intensity < 0.01f) continue;
        if (s.slot(i).point_world.x == 0.0f)  found_zero = true;
        if (s.slot(i).point_world.x == 99.0f) found_99 = true;
    }
    EXPECT_FALSE(found_zero);
    EXPECT_TRUE(found_99);
}

TEST(ShieldRegistry, RegisterCreatesStateForInstance) {
    ShieldRegistry reg;
    scenegraph::InstanceId id{42, 1};
    reg.register_instance(id, ShieldMode::Skin, 2.0f,
                          glm::vec4(0.1f, 0.2f, 0.3f, 1.0f),
                          glm::vec3(0.0f), glm::vec3(5.0f));
    auto* s = reg.find(id);
    ASSERT_NE(s, nullptr);
    EXPECT_EQ(s->mode, ShieldMode::Skin);
    EXPECT_FLOAT_EQ(s->decay_seconds, 2.0f);
}

TEST(ShieldRegistry, FindReturnsNullForUnknownInstance) {
    ShieldRegistry reg;
    EXPECT_EQ(reg.find(scenegraph::InstanceId{999, 0}), nullptr);
}

TEST(ShieldRegistry, PushHitDropsSilentlyForUnknownInstance) {
    ShieldRegistry reg;
    // Must not crash, must not throw.
    reg.push_hit(scenegraph::InstanceId{999, 0}, {0, 0, 0}, {1, 1, 1, 1}, 1.0f, 0.0);
    SUCCEED();
}

TEST(ShieldRegistry, PushHitRoutesToCorrectInstance) {
    ShieldRegistry reg;
    scenegraph::InstanceId a{1, 0}, b{2, 0};
    reg.register_instance(a, ShieldMode::Ellipsoid, 1.0f, glm::vec4(1, 0, 0, 1), {}, glm::vec3(1));
    reg.register_instance(b, ShieldMode::Ellipsoid, 1.0f, glm::vec4(0, 1, 0, 1), {}, glm::vec3(1));
    reg.push_hit(a, {1, 1, 1}, {0, 0, 0, 0}, 1.0f, 0.0);  // 0-rgba → default for A = red
    // A should have an active hit colored red.
    int found_a = -1;
    for (std::size_t i = 0; i < ShieldState::MaxHits; ++i) {
        if (reg.find(a)->slot(i).current_intensity > 0.0f) { found_a = static_cast<int>(i); break; }
    }
    ASSERT_NE(found_a, -1);
    EXPECT_EQ(reg.find(a)->slot(found_a).color_rgba, glm::vec4(1, 0, 0, 1));
    EXPECT_EQ(reg.find(b)->active_count(), 0u);
}

TEST(ShieldRegistry, UnregisterRemovesState) {
    ShieldRegistry reg;
    scenegraph::InstanceId id{7, 3};
    reg.register_instance(id, ShieldMode::Ellipsoid, 1.0f, glm::vec4(1), {}, glm::vec3(1));
    reg.unregister_instance(id);
    EXPECT_EQ(reg.find(id), nullptr);
}

TEST(ShieldState, TextureIndexStableAcrossTicks) {
    auto s = make_state();
    s.push_hit({0,0,0}, {1,1,1,1}, 1.0f, 0.0, 3);
    int idx_before = -1;
    for (std::size_t i = 0; i < ShieldState::MaxHits; ++i) {
        if (s.slot(i).current_intensity > 0.0f) { idx_before = s.slot(i).texture_index; break; }
    }
    s.tick(/*now=*/0.5);
    int idx_after = -1;
    for (std::size_t i = 0; i < ShieldState::MaxHits; ++i) {
        if (s.slot(i).current_intensity > 0.0f) { idx_after = s.slot(i).texture_index; break; }
    }
    EXPECT_EQ(idx_before, 3);
    EXPECT_EQ(idx_after, 3);
}

// BC sizes the shield bubble as ellipsoid semi-axes = AABB half-extents × √3
// (single-precision literal 0x3FDDB3D7 in the decompiled producer at
// 0x005ABAC0). √3 is the minimal factor for which every corner of the
// bounding box lands exactly ON the ellipsoid surface, so the whole hull is
// guaranteed inside the bubble. The old eyeballed 1.32× padding left box
// corners poking out ((1/1.32)²·3 ≈ 1.72 > 1).
TEST(ShieldState, EllipsoidScaleMatchesBcSqrt3) {
    // Exact BC literal, bit-for-bit.
    EXPECT_EQ(kShieldEllipsoidAxisScale, 1.7320508f);
}

TEST(ShieldState, EllipsoidCircumscribesAabbCorners) {
    // Deliberately anisotropic box (saucer-and-nacelles shape).
    const glm::vec3 h(120.0f, 310.0f, 45.0f);
    const glm::vec3 semi = h * kShieldEllipsoidAxisScale;
    for (int sx = -1; sx <= 1; sx += 2)
        for (int sy = -1; sy <= 1; sy += 2)
            for (int sz = -1; sz <= 1; sz += 2) {
                const glm::vec3 corner(sx * h.x, sy * h.y, sz * h.z);
                const glm::vec3 n = corner / semi;
                const float d = glm::dot(n, n);
                // Corners lie ON the unit-sphere surface (inside-or-on, and
                // tight: the ellipsoid is minimal, not padded).
                EXPECT_NEAR(d, 1.0f, 1e-4f);
                EXPECT_LE(d, 1.0f + 1e-4f);
            }
}

// ── impact splash geometry ─────────────────────────────────────────────────
//
// Two defects fixed together (see engine/appc/combat.py for the gameplay half):
//
//  1. splash_sample() in shaders/shield.frag projects the fragment offset onto
//     a basis perpendicular to `impact_dir` with NO near/far hemisphere gate.
//     The point diametrically opposite the hit projects to uv (0.5, 0.5) --
//     the texture's exact CENTRE -- so the bubble grew a second, identically
//     centred splash on the opposite face.
//  2. The falloff radius was keyed to the LARGEST half-extent, which on BC's
//     4-8:1 hulls is 2-4x the entire vertical size of the bubble, so that
//     mirrored splash was never culled by distance either. With depth-test on
//     and the hull between them, the mirror is the one the player can see.
//
// Real Galaxy.nif / Sovereign.nif AABBs (renderer model_aabb, NIF units).
namespace {
constexpr glm::vec3 kGalaxyHalf{232.064f, 322.166f, 70.4982f};
constexpr glm::vec3 kSovereignHalf{115.429f, 349.8808f, 41.3978f};

// Mirror splash_sample() from shaders/shield.frag so the tests can reason about
// which bubble points it paints. Keep in sync with the shader.
glm::vec3 splash_center(glm::vec3 hit, glm::vec3 bubble_centre, glm::vec3 frag) {
    glm::vec3 impact_dir = glm::normalize(hit - bubble_centre);
    return bubble_centre + impact_dir * glm::length(frag - bubble_centre);
}

glm::vec2 splash_uv(glm::vec3 hit, glm::vec3 bubble_centre,
                    glm::vec3 frag, float radius) {
    glm::vec3 impact_dir = glm::normalize(hit - bubble_centre);
    glm::vec3 ref = std::abs(impact_dir.z) < 0.9f ? glm::vec3(0, 0, 1)
                                                   : glm::vec3(0, 1, 0);
    glm::vec3 t1 = glm::normalize(glm::cross(impact_dir, ref));
    glm::vec3 t2 = glm::cross(impact_dir, t1);
    glm::vec3 offset = frag - splash_center(hit, bubble_centre, frag);
    return glm::vec2(glm::dot(offset, t1), glm::dot(offset, t2))
           / (2.0f * radius) + 0.5f;
}
}  // namespace

TEST(ShieldSplash, HitRadiusStaysInsideTheThinnestBubbleAxis) {
    // The splash must be a localised patch, not a wash over the whole bubble.
    // Bubble semi-axis on axis k is half_k * kShieldEllipsoidAxisScale, so a
    // hit at one pole is 2x that from the opposite pole. Radius must be under
    // that on EVERY axis or the mirrored splash survives the falloff.
    for (glm::vec3 half : {kGalaxyHalf, kSovereignHalf}) {
        const float r = shield_hit_radius(half, /*instance_scale=*/1.0f);
        EXPECT_GT(r, 0.0f);
        for (int k = 0; k < 3; ++k) {
            const float antipodal = 2.0f * kShieldEllipsoidAxisScale * half[k];
            EXPECT_LT(r, antipodal)
                << "axis " << k << ": splash reaches the opposite face";
        }
    }
}

TEST(ShieldSplash, HitRadiusScalesWithTheInstanceMatrix) {
    const float r1 = shield_hit_radius(kGalaxyHalf, 1.0f);
    const float r2 = shield_hit_radius(kGalaxyHalf, 2.0f);
    EXPECT_FLOAT_EQ(r2, 2.0f * r1);
}

TEST(ShieldSplash, AntipodalBubblePointWouldGetTheTextureCentre) {
    // Documents defect 1: without a hemisphere gate the far pole samples uv
    // (0.5, 0.5). This is the geometry the gate below has to reject.
    const glm::vec3 centre(0.0f);
    const float semi_z = kGalaxyHalf.z * kShieldEllipsoidAxisScale;
    const glm::vec3 hit(0.0f, 0.0f, -kGalaxyHalf.z);        // ventral hull hit
    const glm::vec3 far_pole(0.0f, 0.0f, semi_z);           // DORSAL bubble point
    const glm::vec2 uv = splash_uv(hit, centre, far_pole, 100.0f);
    EXPECT_NEAR(uv.x, 0.5f, 1e-4f);
    EXPECT_NEAR(uv.y, 0.5f, 1e-4f);
}

TEST(ShieldSplash, GateRejectsTheFarHemisphereAndKeepsTheNearOne) {
    const glm::vec3 impact_dir(0.0f, 0.0f, -1.0f);   // hit came from below
    EXPECT_FLOAT_EQ(shield_splash_gate(glm::vec3(0, 0, -1), impact_dir), 1.0f);
    EXPECT_FLOAT_EQ(shield_splash_gate(glm::vec3(0, 0, 1), impact_dir), 0.0f);
    // Exactly on the terminator: fully suppressed, and the ramp is smooth, so
    // there is no hard seam across the bubble.
    EXPECT_FLOAT_EQ(shield_splash_gate(glm::vec3(0, 1, 0), impact_dir), 0.0f);
    const float mid = shield_splash_gate(
        glm::normalize(glm::vec3(0.0f, 1.0f, -0.2f)), impact_dir);
    EXPECT_GT(mid, 0.0f);
    EXPECT_LT(mid, 1.0f);
}

TEST(ShieldSplash, SplashLandsOnTheBubbleOnEveryAxis) {
    // The bubble is sqrt(3)x the hull AABB, so a hull hit sits well INSIDE it
    // -- 236 world-units in on a Galaxy's long axis. Measuring falloff from the
    // hit point charges that gap against the splash radius and blanks bow and
    // stern flashes entirely; projecting the impact direction onto the
    // fragment's own radius puts the splash centre ON the bubble instead.
    const glm::vec3 centre(0.0f);
    const float r = shield_hit_radius(kGalaxyHalf, 1.0f);
    for (int k = 0; k < 3; ++k) {
        glm::vec3 hit(0.0f), pole(0.0f);
        hit[k] = kGalaxyHalf[k];                                  // hull surface
        pole[k] = kGalaxyHalf[k] * kShieldEllipsoidAxisScale;     // bubble surface

        // Naive measure: the gap alone exceeds the radius on the long axes,
        // i.e. the splash would be invisible there.
        if (k != 2) EXPECT_GT(glm::length(pole - hit), r) << "axis " << k;

        // Projected measure: the splash is centred exactly on the bubble.
        EXPECT_NEAR(glm::length(pole - splash_center(hit, centre, pole)),
                    0.0f, 1e-3f) << "axis " << k;
    }
}
