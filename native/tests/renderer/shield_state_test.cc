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

// Mirror the UV half of splash_sample() from shaders/shield.frag so the tests
// can reason about which part of the texture a bubble point samples. The
// coverage half lives in production as shield_splash_coverage(). Both work in
// the bubble's unit-sphere space — keep in sync with the shader.
glm::vec2 splash_uv(glm::vec3 hit, glm::vec3 bubble_centre,
                    glm::vec3 frag, glm::vec3 semi_axes) {
    glm::vec3 n_hit = glm::normalize((hit - bubble_centre) / semi_axes);
    glm::vec3 n_frag = glm::normalize((frag - bubble_centre) / semi_axes);
    glm::vec3 ref = std::abs(n_hit.z) < 0.9f ? glm::vec3(0, 0, 1)
                                              : glm::vec3(0, 1, 0);
    glm::vec3 t1 = glm::normalize(glm::cross(n_hit, ref));
    glm::vec3 t2 = glm::cross(n_hit, t1);
    glm::vec3 offset = n_frag - n_hit;
    return glm::vec2(glm::dot(offset, t1), glm::dot(offset, t2))
           / (2.0f * kShieldSplashRadius) + 0.5f;
}
}  // namespace


TEST(ShieldSplash, AntipodalBubblePointWouldGetTheTextureCentre) {
    // Documents defect 1: without a hemisphere gate the far pole samples uv
    // (0.5, 0.5). This is the geometry the gate below has to reject.
    const glm::vec3 centre(0.0f);
    const glm::vec3 semi = kGalaxyHalf * kShieldEllipsoidAxisScale;
    const glm::vec3 hit(0.0f, 0.0f, -kGalaxyHalf.z);        // ventral hull hit
    const glm::vec3 far_pole(0.0f, 0.0f, semi.z);           // DORSAL bubble point
    const glm::vec2 uv = splash_uv(hit, centre, far_pole, semi);
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

// ── splash footprint must not depend on WHERE on the bubble it lands ───────
//
// BC's bubbles are extreme ellipsoids (a Galaxy's semi-axes are 402 x 558 x
// 121). Measuring the falloff as a world-space chord between two points at the
// FRAGMENT's own radius makes the patch boundary the locus
// `r(dir) * sin(theta/2) = radius/2` -- so the patch runs much further, in
// angle, in whatever direction the bubble's radius SHRINKS. A bow or flank hit
// smears into a long ribbon over the dorsal/ventral poles: measured 4.3x and
// 5.7x elongation on a real Galaxy, which renders as an arc across the ship
// rather than a localised impact patch.
//
// The fix measures in the ellipsoid's UNIT-SPHERE space (positions divided
// component-wise by the semi-axes) -- the same space BC's own facing chooser
// uses (ShipClass::TestHit, stbc_reference spec/ShieldFacingDamage.md 2.3
// step 4). There the bubble IS a sphere, so the patch is isotropic by
// construction.
namespace {

/// Angular half-width of the splash, in degrees, walking from the impact
/// direction toward `toward` across the bubble surface. 0 if nothing lit.
float splash_half_width_deg(const glm::vec3& semi, const glm::vec3& impact_dir,
                            const glm::vec3& toward) {
    float last_lit = 0.0f;
    for (int deg = 0; deg <= 180; ++deg) {
        const float th = glm::radians(static_cast<float>(deg));
        const glm::vec3 dir =
            glm::normalize(std::cos(th) * impact_dir + std::sin(th) * toward);
        const glm::vec3 frag = dir * semi;      // that direction, on the bubble
        const glm::vec3 hit = impact_dir * semi;
        if (shield_splash_coverage(frag, hit, glm::vec3(0.0f), semi) > 0.02f)
            last_lit = static_cast<float>(deg);
    }
    return last_lit;
}

}  // namespace

TEST(ShieldSplash, FootprintIsIsotropicAcrossAnAnisotropicBubble) {
    const glm::vec3 semi = kGalaxyHalf * kShieldEllipsoidAxisScale;

    const glm::vec3 axes[3] = {{1, 0, 0}, {0, 1, 0}, {0, 0, 1}};
    for (int hit_axis = 0; hit_axis < 3; ++hit_axis) {
        float lo = 1e9f, hi = 0.0f;
        for (int k = 0; k < 3; ++k) {
            if (k == hit_axis) continue;
            const float w = splash_half_width_deg(semi, axes[hit_axis],
                                                   axes[k]);
            lo = std::min(lo, w);
            hi = std::max(hi, w);
        }
        EXPECT_GT(lo, 0.0f) << "hit axis " << hit_axis << ": splash invisible";
        // A patch is a patch: it may not be several times wider one way than
        // the other purely because of where on the bubble it landed.
        EXPECT_LT(hi / lo, 1.25f)
            << "hit axis " << hit_axis << ": splash smeared into a ribbon ("
            << lo << "deg vs " << hi << "deg)";
    }
}

TEST(ShieldSplash, FootprintIsTheSameSizeWhereverItLands) {
    // Stronger than isotropy per-hit: the patch must also be the same size
    // between a bow hit and a dorsal hit.
    const glm::vec3 semi = kGalaxyHalf * kShieldEllipsoidAxisScale;
    const float bow = splash_half_width_deg(semi, {0, 1, 0}, {1, 0, 0});
    const float dorsal = splash_half_width_deg(semi, {0, 0, 1}, {1, 0, 0});
    EXPECT_NEAR(bow, dorsal, 0.25f * std::max(bow, dorsal));
}

TEST(ShieldSplash, FootprintStaysWellClearOfTheTerminator) {
    // A localised impact patch, not a hemisphere wash. Nothing may still be
    // lit near the 90-degree terminator, on any hull or any hit direction.
    for (glm::vec3 half : {kGalaxyHalf, kSovereignHalf}) {
        const glm::vec3 semi = half * kShieldEllipsoidAxisScale;
        const glm::vec3 axes[3] = {{1, 0, 0}, {0, 1, 0}, {0, 0, 1}};
        for (int i = 0; i < 3; ++i)
            for (int k = 0; k < 3; ++k) {
                if (i == k) continue;
                EXPECT_LT(splash_half_width_deg(semi, axes[i], axes[k]),
                          45.0f) << "hit axis " << i << " toward " << k;
            }
    }
}

TEST(ShieldSplash, FootprintIsInvariantUnderInstanceScale) {
    // The measure is taken in the bubble's unit-sphere space, so a rescaled
    // ship (DockWithStarbase, asteroid systems) keeps the same footprint rather
    // than one that grows with the instance matrix. Replaces the old
    // HitRadiusScalesWithTheInstanceMatrix, which asserted the opposite about a
    // world-space radius that no longer exists.
    const glm::vec3 semi1 = kGalaxyHalf * kShieldEllipsoidAxisScale;
    const glm::vec3 semi2 = semi1 * 3.0f;
    const glm::vec3 axes[3] = {{1, 0, 0}, {0, 1, 0}, {0, 0, 1}};
    for (int i = 0; i < 3; ++i) {
        const int k = (i + 1) % 3;
        EXPECT_NEAR(splash_half_width_deg(semi1, axes[i], axes[k]),
                    splash_half_width_deg(semi2, axes[i], axes[k]),
                    0.5f) << "axis " << i;
    }
}

TEST(ShieldSplash, AntipodeIsNeverLit) {
    const glm::vec3 semi = kGalaxyHalf * kShieldEllipsoidAxisScale;
    for (int k = 0; k < 3; ++k) {
        glm::vec3 dir(0.0f);
        dir[k] = 1.0f;
        const glm::vec3 hit = dir * semi;
        const glm::vec3 antipode = -dir * semi;
        EXPECT_FLOAT_EQ(
            shield_splash_coverage(antipode, hit, glm::vec3(0.0f), semi),
            0.0f) << "axis " << k;
    }
}

TEST(ShieldSplash, ImpactPointItselfIsFullyLit) {
    const glm::vec3 semi = kGalaxyHalf * kShieldEllipsoidAxisScale;
    for (int k = 0; k < 3; ++k) {
        glm::vec3 dir(0.0f);
        dir[k] = 1.0f;
        const glm::vec3 hit = dir * semi;
        EXPECT_NEAR(
            shield_splash_coverage(hit, hit, glm::vec3(0.0f), semi),
            1.0f, 1e-4f) << "axis " << k;
    }
}

TEST(ShieldSplash, SplashLandsOnTheBubbleOnEveryAxis) {
    // The bubble is sqrt(3)x the hull AABB, so a hull hit sits well INSIDE it
    // -- 236 world-units in on a Galaxy's long axis. Measuring falloff from the
    // hit point charges that gap against the splash radius and blanks bow and
    // stern flashes entirely; projecting the impact direction onto the
    // fragment's own radius puts the splash centre ON the bubble instead.
    const glm::vec3 centre(0.0f);
    const glm::vec3 semi = kGalaxyHalf * kShieldEllipsoidAxisScale;
    for (int k = 0; k < 3; ++k) {
        glm::vec3 hit(0.0f), pole(0.0f);
        hit[k] = kGalaxyHalf[k];                                  // hull surface
        pole[k] = semi[k];                                        // bubble surface

        // The gap between the two is most of the splash budget on the long
        // axes -- 236 units on Y -- so anything that measures from the hit
        // point itself blanks the bow and stern flashes.
        if (k != 2) EXPECT_GT(glm::length(pole - hit), 100.0f) << "axis " << k;

        // What actually matters: the bubble pole above a hull hit is lit at
        // full strength, on every axis.
        EXPECT_NEAR(shield_splash_coverage(pole, hit, centre, semi), 1.0f, 1e-4f)
            << "axis " << k;
    }
}
