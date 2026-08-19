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

TEST(ShieldState, PushHitStoresColorAndBodyPoint) {
    auto s = make_state();
    s.push_hit({1.0f, 2.0f, 3.0f}, {0.5f, 0.6f, 0.7f, 1.0f}, 1.0f, 0.0, 2);
    EXPECT_EQ(s.active_count(), 1u);
    // Find the populated slot (push_hit may pick any empty slot).
    int found = -1;
    for (std::size_t i = 0; i < ShieldState::MaxHits; ++i) {
        if (s.slot(i).current_intensity > 0.0f) { found = static_cast<int>(i); break; }
    }
    ASSERT_NE(found, -1);
    EXPECT_EQ(s.slot(found).point_body, glm::vec3(1.0f, 2.0f, 3.0f));
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
        if (s.slot(i).point_body.x == 0.0f)  found_zero = true;
        if (s.slot(i).point_body.x == 99.0f) found_99 = true;
    }
    EXPECT_FALSE(found_zero);
    EXPECT_TRUE(found_99);
}

// ── hits ride the ship ─────────────────────────────────────────────────────
//
// A splash was stored as a WORLD point and handed to the shader verbatim, while
// u_bubble_center was recomputed from the live instance matrix every frame. As
// the ship flew on, `hit - bubble_centre` swung and eventually inverted, so the
// splash slid across the bubble and then reappeared on the far face.
//
// Magnitudes, on a Galaxy: ShieldGlowDecay is 1.0 s and the splash seeds at
// intensity 0.5, so it stays above the 0.01 inactive threshold for ln(50) =
// 3.9 s. At 6.3 GU/s that is 24.6 GU of travel against a 3.17 GU bubble
// semi-axis -- and the offset from bubble centre to hull is only ~1.83 GU, so
// the direction passes 90 degrees after just 0.29 s and the splash spends most
// of its life pinned to the wrong face. Under sustained beam fire the 8-slot
// ring refreshes every ~133 ms, which caps the visible error at ~0.84 GU; it is
// an isolated hit -- a torpedo, or the last shot of a burst -- that shows the
// full swing.
//
// Fix: store the hit in the ship's BODY frame and re-transform by the instance
// matrix each frame, exactly as hit_vfx_pass.cc already does for spark bursts.

TEST(ShieldState, HitWorldPointFollowsAShipThatTranslates) {
    Hit h{};
    h.point_body = glm::vec3(0.0f, 300.0f, 0.0f);

    const glm::mat4 at_origin(1.0f);
    const glm::mat4 moved =
        glm::translate(glm::mat4(1.0f), glm::vec3(0.0f, 1000.0f, 0.0f));

    EXPECT_EQ(shield_hit_world_point(h, at_origin), glm::vec3(0, 300, 0));
    EXPECT_EQ(shield_hit_world_point(h, moved), glm::vec3(0, 1300, 0));
}

TEST(ShieldState, HitWorldPointFollowsAShipThatRotates) {
    Hit h{};
    h.point_body = glm::vec3(0.0f, 300.0f, 0.0f);   // on the bow

    // Yaw 90 degrees about Z: the bow swings onto -X.
    const glm::mat4 yawed = glm::rotate(glm::mat4(1.0f), glm::radians(90.0f),
                                        glm::vec3(0.0f, 0.0f, 1.0f));
    const glm::vec3 w = shield_hit_world_point(h, yawed);
    EXPECT_NEAR(w.x, -300.0f, 1e-3f);
    EXPECT_NEAR(w.y, 0.0f, 1e-3f);
    // Still on the bow in the ship's own frame — that is the whole point.
    EXPECT_NEAR(glm::length(w), 300.0f, 1e-3f);
}

TEST(ShieldState, HitStaysOnTheHitFacingAfterTheShipOutrunsIt) {
    // The regression proper. Hit on the bow; ship then flies 24.6 GU forward
    // (3.9 s at 6.3 GU/s, one splash lifetime) along its own +Y.
    Hit h{};
    h.point_body = glm::vec3(0.0f, 322.0f, 0.0f);

    const glm::mat4 later =
        glm::translate(glm::mat4(1.0f), glm::vec3(0.0f, 2460.0f, 0.0f));
    const glm::vec3 bubble_centre(0.0f, 2460.0f, 0.0f);
    const glm::vec3 w = shield_hit_world_point(h, later);

    // Direction from the bubble centre still points at the BOW (+Y), not aft.
    const glm::vec3 dir = glm::normalize(w - bubble_centre);
    EXPECT_GT(dir.y, 0.99f);
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

// UNITS. `register_ship_shield` hands shield_pass.cc the RAW NIF half-extents
// and shield_pass multiplies by `length(inst->world[0])` == BC_MODEL_SCALE ==
// 0.01 before they reach the shader, so u_bubble_semi_axes arrives in GAME
// UNITS -- the same units as v_world_pos and as the weapon's
// DamageRadiusFactor. Anything that compares a distance against a reach must
// therefore be in GU. (The bubble-fit tests above are pure ratios and are
// unaffected by which of the two they use.)
constexpr float kNifToWorld = 0.01f;   // engine/host_loop.py BC_MODEL_SCALE

/// Galaxy / Sovereign bubble semi-axes as the SHADER sees them, in GU.
/// Galaxy: 4.02 / 5.58 / 1.22.
constexpr glm::vec3 kGalaxySemiGu =
    kGalaxyHalf * kNifToWorld * kShieldEllipsoidAxisScale;
constexpr glm::vec3 kSovereignSemiGu =
    kSovereignHalf * kNifToWorld * kShieldEllipsoidAxisScale;

/// Splash coverage at the moment of impact, which is when the core is hottest
/// and every test below wants to measure. Keeps the arg list out of the way.
float coverage_at_t0(const glm::vec3& frag, const glm::vec3& hit,
                     const glm::vec3& centre, const glm::vec3& semi,
                     float reach) {
    return shield_splash_coverage(frag, hit, centre, semi, 0.0f, reach, 0.0f);
}
}  // namespace

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

// ── the splash is a WORLD-SPACE radius, not an angular cap ────────────────
//
// This block replaces four tests that characterised the previous ANGULAR
// design (FootprintIsIsotropicAcrossAnAnisotropicBubble,
// FootprintIsTheSameSizeWhereverItLands, FootprintStaysWellClearOfTheTerminator
// and FootprintIsInvariantUnderInstanceScale). They asserted that the splash
// covers the same number of DEGREES wherever it lands, which the procedural
// splash deliberately no longer does -- they are not regressions, they are the
// old requirement.
//
// Why the requirement changed: measuring in the bubble's unit-sphere space is
// isotropic in angle, but a Galaxy's bubble is 4.02 x 5.58 x 1.22 GU, so a
// fixed 18-degree cap spans 0.43 GU toward the dorsal and 1.74 GU toward the
// bow -- a 4x difference in the size the player actually sees. The splash is
// now a genuine sphere of world radius `reach` intersected with the bubble,
// which is the same rule the hull-carve work settled on: a weapon makes the
// same size of mark on any hull.
namespace {

/// World distance, in GU, from the epicentre out to where coverage falls to
/// half its peak, walking across the bubble surface from `impact_dir` toward
/// `toward`. Returns 0 if nothing is lit.
float splash_half_extent_gu(const glm::vec3& semi, const glm::vec3& impact_dir,
                            const glm::vec3& toward, float reach) {
    const glm::vec3 hit = impact_dir * semi;
    const float peak = coverage_at_t0(hit, hit, glm::vec3(0.0f), semi, reach);
    if (peak <= 0.0f) return 0.0f;
    for (int i = 0; i <= 4000; ++i) {
        const float th = glm::radians(180.0f * static_cast<float>(i) / 4000.0f);
        const glm::vec3 dir =
            glm::normalize(std::cos(th) * impact_dir + std::sin(th) * toward);
        const glm::vec3 frag = dir * semi;
        if (coverage_at_t0(frag, hit, glm::vec3(0.0f), semi, reach)
                < 0.5f * peak)
            return glm::length(frag - hit);
    }
    return 0.0f;
}

}  // namespace

TEST(ShieldSplash, HalfExtentIsTheSameWorldSizeWhereverItLands) {
    // THE load-bearing test for the rebuild. A bow hit and a dorsal hit sit on
    // parts of the bubble whose radii differ by 4.6x (5.58 GU vs 1.22 GU).
    // Under the old angular measure the same splash therefore covered 4x more
    // world distance on the bow than on the dorsal. It must not.
    const float reach = 1.5f;
    const float bow    = splash_half_extent_gu(kGalaxySemiGu, {0, 1, 0}, {1, 0, 0}, reach);
    const float dorsal = splash_half_extent_gu(kGalaxySemiGu, {0, 0, 1}, {1, 0, 0}, reach);
    const float flank  = splash_half_extent_gu(kGalaxySemiGu, {1, 0, 0}, {0, 1, 0}, reach);
    ASSERT_GT(bow, 0.0f);
    ASSERT_GT(dorsal, 0.0f);
    ASSERT_GT(flank, 0.0f);
    EXPECT_NEAR(bow, dorsal, 0.02f * bow) << "bow " << bow << " vs dorsal " << dorsal;
    EXPECT_NEAR(bow, flank, 0.02f * bow) << "bow " << bow << " vs flank " << flank;
}

TEST(ShieldSplash, HalfExtentIsIsotropicAroundOneImpact) {
    // And the patch is round: walking away from a single hit in two
    // perpendicular directions covers the same world distance.
    const float reach = 1.5f;
    const glm::vec3 axes[3] = {{1, 0, 0}, {0, 1, 0}, {0, 0, 1}};
    for (int hit_axis = 0; hit_axis < 3; ++hit_axis) {
        float lo = 1e9f, hi = 0.0f;
        for (int k = 0; k < 3; ++k) {
            if (k == hit_axis) continue;
            const float w = splash_half_extent_gu(kGalaxySemiGu, axes[hit_axis],
                                                   axes[k], reach);
            lo = std::min(lo, w);
            hi = std::max(hi, w);
        }
        ASSERT_GT(lo, 0.0f) << "hit axis " << hit_axis << ": splash invisible";
        EXPECT_LT(hi / lo, 1.05f)
            << "hit axis " << hit_axis << ": splash is not round ("
            << lo << " GU vs " << hi << " GU)";
    }
}

TEST(ShieldSplash, HalfExtentIsTheSameOnAnyHullAndAnyShipScale) {
    // Replaces FootprintIsInvariantUnderInstanceScale, which asserted the same
    // ANGULAR footprint on a rescaled ship. A world-space splash keeps the same
    // GU size instead -- so on a 3x ship it covers 3x FEWER degrees, which is
    // the intent: the weapon, not the target, sets the size of the mark.
    const float reach = 1.5f;
    const float galaxy = splash_half_extent_gu(kGalaxySemiGu, {0, 1, 0}, {1, 0, 0}, reach);
    const float sovereign = splash_half_extent_gu(kSovereignSemiGu, {0, 1, 0}, {1, 0, 0}, reach);
    const float big = splash_half_extent_gu(kGalaxySemiGu * 3.0f, {0, 1, 0}, {1, 0, 0}, reach);
    ASSERT_GT(galaxy, 0.0f);
    EXPECT_NEAR(galaxy, sovereign, 0.05f * galaxy);
    EXPECT_NEAR(galaxy, big, 0.05f * galaxy);
}

TEST(ShieldSplash, HalfExtentTracksTheWeaponReach) {
    // The splash is "sized to the impact": a wider reach means a wider mark.
    const float narrow = splash_half_extent_gu(kGalaxySemiGu, {0, 1, 0}, {1, 0, 0}, 0.6f);
    const float wide   = splash_half_extent_gu(kGalaxySemiGu, {0, 1, 0}, {1, 0, 0}, 2.0f);
    ASSERT_GT(narrow, 0.0f);
    EXPECT_GT(wide, 2.0f * narrow);
}

TEST(ShieldSplash, ThereIsNoDiscontinuityWhereTheOldTangentBasisFlipped) {
    // Defect 3 of the old design: splash_sample() seeded its tangent basis from
    // ref = |n_hit.z| < 0.9 ? (0,0,1) : (0,1,0), so the texture's rotation
    // changed discontinuously as an impact tracked across |n.z| = 0.9 and the
    // splash visibly POPPED. The procedural splash has no basis at all, so the
    // defect has nowhere to live -- this pins that.
    const float reach = 1.5f;
    const glm::vec3 probe = glm::normalize(glm::vec3(0.3f, 0.2f, 0.93f)) * kGalaxySemiGu;
    float prev = -1.0f, worst_step = 0.0f;
    for (int i = 0; i <= 400; ++i) {
        // Sweep the hit direction through |n.z| = 0.9 in unit-sphere space.
        const float nz = 0.80f + 0.20f * static_cast<float>(i) / 400.0f;
        const float nx = std::sqrt(std::max(0.0f, 1.0f - nz * nz));
        const glm::vec3 hit = glm::vec3(nx, 0.0f, nz) * kGalaxySemiGu;
        const float c = coverage_at_t0(probe, hit, glm::vec3(0.0f),
                                        kGalaxySemiGu, reach);
        if (prev >= 0.0f) worst_step = std::max(worst_step, std::abs(c - prev));
        prev = c;
    }
    // Neighbouring samples are 0.05% of the sweep apart; a basis flip would
    // show up here as a step far larger than the smooth drift between them.
    EXPECT_LT(worst_step, 0.05f) << "largest single-step jump " << worst_step;
}

TEST(ShieldSplash, AntipodeIsNeverLit) {
    for (int k = 0; k < 3; ++k) {
        glm::vec3 dir(0.0f);
        dir[k] = 1.0f;
        const glm::vec3 hit = dir * kGalaxySemiGu;
        const glm::vec3 antipode = -dir * kGalaxySemiGu;
        EXPECT_FLOAT_EQ(
            coverage_at_t0(antipode, hit, glm::vec3(0.0f), kGalaxySemiGu, 1.5f),
            0.0f) << "axis " << k;
    }
}

TEST(ShieldSplash, AntipodeIsNeverLitEvenWhenTheReachExceedsTheBubble) {
    // This is why the hemisphere gate survives the rebuild. A world-space
    // distance is a straight chord, so on a small hull whose bubble is thinner
    // than the reach, the far side is within range and would light up.
    const glm::vec3 tiny(0.9f, 1.2f, 0.25f);      // shuttle-scale bubble, GU
    const glm::vec3 hit(0.0f, 0.0f, tiny.z);
    const glm::vec3 antipode(0.0f, 0.0f, -tiny.z);
    ASSERT_LT(glm::length(antipode - hit), kShieldSplashReachMax)
        << "fixture no longer exercises the wrap case";
    EXPECT_FLOAT_EQ(
        coverage_at_t0(antipode, hit, glm::vec3(0.0f), tiny,
                       kShieldSplashReachMax),
        0.0f);
}

TEST(ShieldSplash, TheEpicentreIsTheBrightestPointAndItBlooms) {
    // Replaces ImpactPointItselfIsFullyLit, which asserted coverage == 1.0
    // exactly. Coverage is no longer capped at 1 -- the hot core is what drives
    // the HDR bloom -- so the meaningful assertion is that the epicentre is the
    // peak and that it clears 1.0.
    const float reach = 1.5f;
    for (int k = 0; k < 3; ++k) {
        glm::vec3 dir(0.0f);
        dir[k] = 1.0f;
        const glm::vec3 hit = dir * kGalaxySemiGu;
        const float at_hit = coverage_at_t0(hit, hit, glm::vec3(0.0f),
                                             kGalaxySemiGu, reach);
        EXPECT_GT(at_hit, 1.0f) << "axis " << k;
        // Anywhere else on the bubble is dimmer.
        const int other = (k + 1) % 3;
        glm::vec3 off(0.0f);
        off[k] = 0.9f;
        off[other] = 0.436f;                        // still a unit direction
        const glm::vec3 frag = glm::normalize(off) * kGalaxySemiGu;
        EXPECT_LT(coverage_at_t0(frag, hit, glm::vec3(0.0f), kGalaxySemiGu, reach),
                  at_hit) << "axis " << k;
    }
}

TEST(ShieldSplash, AHullHitStillLightsTheBubbleAboveIt) {
    // The bubble is sqrt(3)x the hull AABB, so a hull anchor sits well INSIDE
    // it -- 2.36 GU in on a Galaxy's long axis, more than a whole reach.
    // Measuring the falloff from the raw hull point would blank bow and stern
    // flashes entirely; shield_splash_epicentre projects it out first.
    const glm::vec3 centre(0.0f);
    const float reach = 1.5f;
    for (int k = 0; k < 3; ++k) {
        glm::vec3 hit(0.0f), pole(0.0f);
        hit[k] = kGalaxyHalf[k] * kNifToWorld;      // hull surface
        pole[k] = kGalaxySemiGu[k];                 // bubble surface above it

        if (k != 2) EXPECT_GT(glm::length(pole - hit), reach) << "axis " << k;

        EXPECT_GT(coverage_at_t0(pole, hit, centre, kGalaxySemiGu, reach), 1.0f)
            << "axis " << k;
    }
}

// ── splash brightness is applied ONCE ──────────────────────────────────────
//
// shield.frag accumulated `color += tint*inten*hex.rgb` AND
// `alpha += hex.a*inten`, and shield_pass blended with
// glBlendFunc(GL_SRC_ALPHA, GL_ONE) -- which multiplies rgb by alpha. So the
// coverage, the hit intensity and the texture each landed in the framebuffer
// SQUARED. Measured against the real shieldhit01.TGA radial profile, peak
// output was 0.64% of full brightness; applied once it is 6.93%, 11x brighter.
//
// The invariant that keeps it fixed: output is LINEAR in both coverage and
// intensity. Anything quadratic means a term is being applied on both the
// colour and the alpha path again.

TEST(ShieldSplash, BrightnessIsLinearInCoverage) {
    const float i = 0.5f;
    const float a = shield_splash_intensity(0.25f, i);
    const float b = shield_splash_intensity(0.50f, i);
    EXPECT_NEAR(b, 2.0f * a, 1e-6f);
}

TEST(ShieldSplash, BrightnessIsLinearInHitIntensity) {
    const float c = 0.4f;
    const float a = shield_splash_intensity(c, 0.25f);
    const float b = shield_splash_intensity(c, 0.50f);
    EXPECT_NEAR(b, 2.0f * a, 1e-6f);
}

TEST(ShieldSplash, FullCoverageAtFullIntensityIsTheOpacityCeiling) {
    EXPECT_NEAR(shield_splash_intensity(1.0f, 1.0f), kShieldSplashOpacity, 1e-6f);
}

TEST(ShieldSplash, NoCoverageEmitsNothing) {
    EXPECT_FLOAT_EQ(shield_splash_intensity(0.0f, 1.0f), 0.0f);
    EXPECT_FLOAT_EQ(shield_splash_intensity(1.0f, 0.0f), 0.0f);
}

// ═══════════════════════════════════════════════════════════════════════════
// PROCEDURAL 3D SPLASH (spike/shield-procedural-splash)
// ═══════════════════════════════════════════════════════════════════════════
//
// The splash is being rebuilt as a purely radial function of WORLD distance
// from the impact, replacing the tangent-plane texture projection. See the
// block comment above shield_splash_shape() in renderer/shield_state.h.
//
TEST(ShieldSplashReach, ScalesWithTheWeaponDamageRadiusFactor) {
    // `radius` is the weapon's DamageRadiusFactor, already plumbed to
    // hit_feedback.dispatch: photon 0.13 GU, phaser 0.15 GU. Against a
    // Galaxy's 1.22 GU thin axis those are far too small to see, so the
    // reach is that radius times a multiplier.
    const float photon = shield_splash_reach(0.13f);
    const float phaser = shield_splash_reach(0.15f);
    EXPECT_NEAR(photon, 0.13f * kShieldSplashReachPerRadius, 1e-5f);
    EXPECT_NEAR(phaser, 0.15f * kShieldSplashReachPerRadius, 1e-5f);
    // Bigger DamageRadiusFactor -> wider splash. (Phaser's IS bigger than
    // photon's; a torpedo reads heavier through intensity, not size.)
    EXPECT_GT(phaser, photon);
}

TEST(ShieldSplashReach, IsClampedAtBothEnds) {
    // Callers with no ray (collisions, splash damage) pass radius 0, which
    // must still produce a visible splash rather than nothing.
    EXPECT_FLOAT_EQ(shield_splash_reach(0.0f), kShieldSplashReachMin);
    EXPECT_FLOAT_EQ(shield_splash_reach(-1.0f), kShieldSplashReachMin);
    // And a freak DamageRadiusFactor may not wrap the whole bubble.
    EXPECT_FLOAT_EQ(shield_splash_reach(1000.0f), kShieldSplashReachMax);
}

// ── epicentre: the splash is anchored ON the bubble ────────────────────────
//
// hit_feedback passes `shield_point` (the bubble entry) when a ray exists and
// the HULL impact point when one does not (collisions, splash damage). The
// bubble stands sqrt(3) off the hull -- 2.36 GU on a Galaxy's long axis -- so
// a raw hull point sits deep inside. Projecting whatever arrives onto the
// ellipsoid surface normalises both callers to one anchor, and makes a world
// distance from it meaningful.

TEST(ShieldSplashEpicentre, LandsExactlyOnTheEllipsoidSurface) {
    const glm::vec3 centre(0.0f);
    for (int k = 0; k < 3; ++k) {
        glm::vec3 hull(0.0f);
        hull[k] = kGalaxyHalf[k] * kNifToWorld;      // hull surface, well inside
        const glm::vec3 epi =
            shield_splash_epicentre(hull, centre, kGalaxySemiGu);
        // On the surface <=> unit length once divided by the semi-axes.
        EXPECT_NEAR(glm::length((epi - centre) / kGalaxySemiGu), 1.0f, 1e-5f)
            << "axis " << k;
    }
}

TEST(ShieldSplashEpicentre, PreservesTheImpactDirection) {
    const glm::vec3 centre(2.0f, -3.0f, 0.5f);       // off-origin bubble
    const glm::vec3 hull = centre + glm::vec3(0.4f, 1.1f, -0.2f);
    const glm::vec3 epi =
        shield_splash_epicentre(hull, centre, kGalaxySemiGu);
    const glm::vec3 a = glm::normalize((hull - centre) / kGalaxySemiGu);
    const glm::vec3 b = glm::normalize((epi - centre) / kGalaxySemiGu);
    EXPECT_NEAR(glm::dot(a, b), 1.0f, 1e-5f);
}

TEST(ShieldSplashEpicentre, PushesAHullHitOutByTheFullBubbleStandoff) {
    // The gap this exists to close: on a Galaxy's long axis the hull point is
    // 3.22 GU out and the bubble is 5.58 GU out, so anchoring on the hull puts
    // the splash 2.36 GU -- more than a whole reach -- behind the surface the
    // player is looking at.
    const glm::vec3 centre(0.0f);
    const glm::vec3 hull(0.0f, kGalaxyHalf.y * kNifToWorld, 0.0f);
    const glm::vec3 epi = shield_splash_epicentre(hull, centre, kGalaxySemiGu);
    EXPECT_GT(glm::length(epi - hull), 2.0f);
    EXPECT_NEAR(epi.y, kGalaxySemiGu.y, 1e-4f);
}

TEST(ShieldSplashEpicentre, AHitAtTheBubbleCentreDoesNotProduceNaN) {
    // Degenerate but reachable: a point-blank collision resolving to the
    // ship's own AABB centre. Must not divide by zero and poison the frame --
    // a NaN here reaches the HDR bloom amplifier.
    const glm::vec3 centre(1.0f, 2.0f, 3.0f);
    const glm::vec3 epi =
        shield_splash_epicentre(centre, centre, kGalaxySemiGu);
    EXPECT_TRUE(std::isfinite(epi.x) && std::isfinite(epi.y) &&
                std::isfinite(epi.z));
}

// ── shape: rings over a filled disc, plus a hot core and a slow afterglow ──
//
// The whole splash is one scalar function of (world distance, age, reach).
// No basis, no uv, no projection, no texture -- which is what makes it
// radially symmetric by construction rather than by correction.
namespace {

/// Largest `d` at which the MOVING part of the splash still contributes.
///
/// Subtracting the value at `kShieldSplashRippleLife` removes the afterglow,
/// which carries no age term (RippleGeometryIsFinishedButTheAfterglowIsNot
/// proves that is all that is left there). Without the subtraction this
/// measures the glow instead: the afterglow alone clears a 0.05 threshold out
/// to 0.888x the reach at EVERY age, so the front never moves and the test
/// fails against a perfectly good implementation. Measure the thing you mean.
float ripple_extent_gu(float age, float reach, float thresh) {
    float last = 0.0f;
    for (int i = 0; i <= 2000; ++i) {
        const float d = reach * 2.0f * static_cast<float>(i) / 2000.0f;
        const float moving = shield_splash_shape(d, age, reach, 0.0f)
                           - shield_splash_shape(d, kShieldSplashRippleLife,
                                                 reach, 0.0f);
        if (moving > thresh) last = d;
    }
    return last;
}

}  // namespace

TEST(ShieldSplashShape, CoreIsHotEnoughToBloom) {
    // The single biggest reason to go procedural: a texture sample is capped
    // at 1.0 and can never drive the HDR bloom. The core must exceed it.
    EXPECT_GT(shield_splash_shape(0.0f, 0.0f, 1.5f, 0.0f), 1.0f);
}

TEST(ShieldSplashShape, TheFrontExpandsWithAge) {
    const float reach = 1.5f;
    const float early = ripple_extent_gu(0.10f * kShieldSplashRippleLife, reach, 0.02f);
    const float mid   = ripple_extent_gu(0.40f * kShieldSplashRippleLife, reach, 0.02f);
    const float late  = ripple_extent_gu(0.80f * kShieldSplashRippleLife, reach, 0.02f);
    EXPECT_GT(mid, early);
    EXPECT_GT(late, mid);
}

TEST(ShieldSplashShape, NothingRipplesAheadOfTheLeadingFront) {
    // The disc gates the rings, and the disc ends at the front. Beyond it the
    // only term left is the afterglow, which carries no age dependence -- so
    // the value there must be IDENTICAL at two different ages.
    const float reach = 1.5f;
    const float d = 0.80f * reach;          // ahead of the front at both ages
    const float a = shield_splash_shape(d, 0.10f * kShieldSplashRippleLife, reach, 0.0f);
    const float b = shield_splash_shape(d, 0.20f * kShieldSplashRippleLife, reach, 0.0f);
    EXPECT_NEAR(a, b, 1e-6f);
    EXPECT_GT(a, 0.0f) << "afterglow should still be present out here";
}

TEST(ShieldSplashShape, RippleGeometryIsFinishedButTheAfterglowIsNot) {
    // This is the two-timescale decision made testable. Past the ripple life
    // the moving parts are gone, so the shape stops changing with age -- what
    // remains fades on the hit's own ~3.9s intensity decay, applied by the
    // caller, not here.
    const float reach = 1.5f;
    for (float d : {0.0f, 0.3f, 0.9f, 1.4f}) {
        const float at_life = shield_splash_shape(d, kShieldSplashRippleLife, reach, 0.0f);
        const float much_later = shield_splash_shape(d, 10.0f * kShieldSplashRippleLife, reach, 0.0f);
        EXPECT_NEAR(at_life, much_later, 1e-6f) << "d=" << d;
    }
    EXPECT_GT(shield_splash_shape(0.0f, kShieldSplashRippleLife, reach, 0.0f), 0.0f)
        << "afterglow must survive the ripple";
}

TEST(ShieldSplashShape, TheCoreOutshinesTheAfterglowItLeavesBehind) {
    const float reach = 1.5f;
    const float peak = shield_splash_shape(0.0f, 0.0f, reach, 0.0f);
    const float after = shield_splash_shape(0.0f, kShieldSplashRippleLife, reach, 0.0f);
    EXPECT_GT(peak, 5.0f * after);
}

TEST(ShieldSplashShape, RingsProduceSeveralConcentricCrests) {
    // "Rings over a filled disc": there must actually be more than one crest,
    // or this is just a blob. Counted as local maxima in d at mid-life.
    const float reach = 1.5f;
    const float age = 0.5f * kShieldSplashRippleLife;
    int crests = 0;
    float prev = shield_splash_shape(0.0f, age, reach, 0.0f);
    float cur = shield_splash_shape(0.002f, age, reach, 0.0f);
    for (int i = 2; i <= 1500; ++i) {
        const float d = 0.002f * static_cast<float>(i);
        const float next = shield_splash_shape(d, age, reach, 0.0f);
        if (cur > prev && cur >= next) ++crests;
        prev = cur;
        cur = next;
    }
    EXPECT_GE(crests, 2) << "expected concentric ring crests, found " << crests;
}

TEST(ShieldSplashShape, RingPhaseJitterVariesTheLookBetweenHits) {
    // Replaces the four shieldhit0*.TGA variants: same shape, different ring
    // phase per hit, so a burst does not look rubber-stamped.
    const float reach = 1.5f;
    const float age = 0.5f * kShieldSplashRippleLife;
    const float d = 0.35f * reach;
    EXPECT_NE(shield_splash_shape(d, age, reach, 0.0f),
              shield_splash_shape(d, age, reach, 0.5f));
}

TEST(ShieldSplashShape, IsFiniteAndNonNegativeEverywhere) {
    // A NaN or a negative here reaches the HDR bloom amplifier, which is
    // exactly how the black-square bug got in.
    for (float reach : {kShieldSplashReachMin, 1.5f, kShieldSplashReachMax}) {
        for (int ai = 0; ai <= 40; ++ai) {
            const float age = 0.1f * static_cast<float>(ai) - 0.5f;  // incl. negative
            for (int di = 0; di <= 60; ++di) {
                const float d = 0.1f * static_cast<float>(di);
                const float v = shield_splash_shape(d, age, reach, 0.25f);
                ASSERT_TRUE(std::isfinite(v))
                    << "d=" << d << " age=" << age << " reach=" << reach;
                ASSERT_GE(v, 0.0f)
                    << "d=" << d << " age=" << age << " reach=" << reach;
            }
        }
    }
}

TEST(ShieldState, PushHitStoresTheWeaponRadius) {
    // The splash is "sized to the impact", so the weapon's DamageRadiusFactor
    // has to survive the trip from hit_feedback.dispatch into the slot the
    // shader reads. It was already plumbed as far as dispatch and stopped
    // there, going only to the decal and hull-carve calls.
    auto s = make_state();
    s.push_hit({1.0f, 0.0f, 0.0f}, {0, 0, 0, 0}, 1.0f, 0.0, 1, /*radius_gu=*/0.13f);
    int found = -1;
    for (std::size_t i = 0; i < ShieldState::MaxHits; ++i)
        if (s.slot(i).current_intensity > 0.0f) { found = static_cast<int>(i); break; }
    ASSERT_NE(found, -1);
    EXPECT_FLOAT_EQ(s.slot(found).radius_gu, 0.13f);
}

TEST(ShieldState, ARecycledSlotDoesNotInheritThePreviousWeaponRadius) {
    // push_hit overwrites the dimmest slot when all 8 are full -- a phaser
    // fills every slot at 60Hz -- so a stale radius would silently resize the
    // next weapon's splash.
    auto s = make_state();
    for (std::size_t i = 0; i < ShieldState::MaxHits; ++i)
        s.push_hit({1.0f, 0.0f, 0.0f}, {0, 0, 0, 0}, 1.0f, 0.0, 0, 2.0f);
    s.push_hit({1.0f, 0.0f, 0.0f}, {0, 0, 0, 0}, 1.0f, 0.0, 0, 0.13f);
    bool seen = false;
    for (std::size_t i = 0; i < ShieldState::MaxHits; ++i)
        if (s.slot(i).radius_gu == 0.13f) seen = true;
    EXPECT_TRUE(seen) << "the new hit's radius never landed in a slot";
}
