// native/tests/renderer/dof_test.cc
#include <gtest/gtest.h>
#include <renderer/dof.h>

namespace {

constexpr float kNear = 1.0f;
constexpr float kFar  = 5000.0f;

// Inverse of linear_depth_gu: the [0,1] depth-buffer value for a view
// distance. Lets the tests below read in game units instead of raw depth.
float depth_for_z(float z, float near_gu = kNear, float far_gu = kFar) {
    const float ndc = (far_gu + near_gu - 2.0f * near_gu * far_gu / z)
                    / (far_gu - near_gu);
    return (ndc + 1.0f) * 0.5f;
}

renderer::DofParams params_at(float focus_gu) {
    renderer::DofParams p;
    p.focus_gu        = focus_gu;
    p.blend           = 1.0f;
    p.near_strength   = 1.0f;
    p.far_strength    = 1.0f;
    p.far_ceiling     = 0.4f;
    p.max_radius_frac = 0.008f;
    // Foreground ramp for a 15 GU hull at the shipped 1x..4x radii.
    p.near_full_gu    = 15.0f;
    p.near_sharp_gu   = 60.0f;
    return p;
}

TEST(Dof, LinearDepthSpansNearToFar) {
    EXPECT_NEAR(renderer::linear_depth_gu(0.0f, kNear, kFar), kNear, 1e-3f);
    EXPECT_NEAR(renderer::linear_depth_gu(1.0f, kNear, kFar), kFar,  1e-1f);
}

TEST(Dof, DepthForZRoundTrips) {
    for (float z : {2.0f, 25.0f, 100.0f, 900.0f}) {
        EXPECT_NEAR(renderer::linear_depth_gu(depth_for_z(z), kNear, kFar),
                    z, z * 1e-3f);
    }
}

TEST(Dof, SharpExactlyAtFocus) {
    const auto p = params_at(100.0f);
    EXPECT_NEAR(renderer::coc_from_depth(depth_for_z(100.0f), kNear, kFar, p),
                0.0f, 1e-4f);
}

// Near field is signed negative and never exceeds the foreground gain.
//
// This used to assert the THIN-LENS clamp: at half the focus distance the
// ratio 1 - focus/z is exactly -1. The foreground is no longer a ratio (it is
// a camera-anchored ramp -- see DofForeground below), so the boundary now sits
// at the ramp's inner end instead. The invariant it was really protecting --
// that the foreground saturates rather than running away -- is unchanged.
TEST(Dof, NearFieldSaturatesAtTheForegroundGain) {
    const auto p = params_at(100.0f);
    // Inside near_full_gu (15) the ramp is fully saturated.
    EXPECT_NEAR(renderer::coc_from_depth(depth_for_z(10.0f), kNear, kFar, p),
                -1.0f, 1e-3f);
    // Closer still stays there, never overshoots.
    EXPECT_NEAR(renderer::coc_from_depth(depth_for_z(3.0f), kNear, kFar, p),
                -1.0f, 1e-3f);
}

TEST(Dof, NearFieldIsProportionalAcrossTheRamp) {
    const auto p = params_at(100.0f);
    // Ramp runs 60 GU (sharp) -> 15 GU (full). At 37.5 GU it is exactly half
    // way: (60 - 37.5) / (60 - 15) = 0.5.
    EXPECT_NEAR(renderer::coc_from_depth(depth_for_z(37.5f), kNear, kFar, p),
                -0.5f, 1e-3f);
    // A quarter of the way in.
    EXPECT_NEAR(renderer::coc_from_depth(depth_for_z(48.75f), kNear, kFar, p),
                -0.25f, 1e-3f);
}

TEST(Dof, FarFieldSaturatesAtTheCeiling) {
    const auto p = params_at(100.0f);
    // z=125: 1 - 100/125 = 0.2, below the 0.4 ceiling.
    EXPECT_NEAR(renderer::coc_from_depth(depth_for_z(125.0f), kNear, kFar, p),
                0.2f, 1e-3f);
    // z=200: 1 - 100/200 = 0.5, above the ceiling -> capped.
    EXPECT_NEAR(renderer::coc_from_depth(depth_for_z(200.0f), kNear, kFar, p),
                0.4f, 1e-3f);
    // z=2000 is far beyond, still exactly the ceiling. This is the anti-mush
    // guarantee: the far field can never blur harder than far_ceiling.
    EXPECT_NEAR(renderer::coc_from_depth(depth_for_z(2000.0f), kNear, kFar, p),
                0.4f, 1e-3f);
}

// The backdrop pass draws the sky with glDepthMask(GL_FALSE), so sky pixels
// never write depth and hold the clear value. Exempting them keeps the
// starfield sharp.
TEST(Dof, StarfieldIsExempt) {
    const auto p = params_at(100.0f);
    EXPECT_EQ(renderer::coc_from_depth(1.0f, kNear, kFar, p), 0.0f);
    // Just inside the 0.98*far threshold is still exempt...
    EXPECT_EQ(renderer::coc_from_depth(depth_for_z(4950.0f), kNear, kFar, p),
              0.0f);
    // ...and just outside it is not.
    EXPECT_GT(renderer::coc_from_depth(depth_for_z(4000.0f), kNear, kFar, p),
              0.0f);
}

// A zero focus distance means "no subject". Without this guard the thin-lens
// term degenerates to 1.0 and the whole frame would blur at the ceiling.
TEST(Dof, NoSubjectMeansNoBlur) {
    const auto p = params_at(0.0f);
    EXPECT_EQ(renderer::coc_from_depth(depth_for_z(100.0f), kNear, kFar, p),
              0.0f);
}

TEST(Dof, StrengthScalesBothSidesIndependently) {
    auto p = params_at(100.0f);
    p.near_strength = 0.5f;
    p.far_strength  = 0.25f;
    // Foreground: half way along the ramp (37.5 GU), scaled by 0.5 -> -0.25.
    EXPECT_NEAR(renderer::coc_from_depth(depth_for_z(37.5f), kNear, kFar, p),
                -0.25f, 1e-3f);
    // Background is untouched by the model change: z=200 gives 0.5 * 0.25.
    EXPECT_NEAR(renderer::coc_from_depth(depth_for_z(200.0f), kNear, kFar, p),
                0.125f, 1e-3f);
}

}  // namespace

// ── The foreground ramp: camera-anchored, NOT a thin-lens ratio ──────────
//
// The thin lens made foreground blur a function of focus/z, so the player's
// own hull -- which never moves relative to the chase camera -- had its blur
// set by how far away the TARGET was. Past ~18 km it pinned at maximum, and
// merely switching targets visibly changed your own ship. These pin the
// property that replaced it.

namespace {

// A hull surface 30 GU from the camera: where the chase camera actually puts
// the player ship (~1.5x a 20 GU radius).
constexpr float kHullZ = 30.0f;

}  // namespace

TEST(DofForeground, HullBlurIsIdenticalAcrossEveryTargetDistance) {
    const float d_hull = depth_for_z(kHullZ);
    const float first  = renderer::coc_from_depth(d_hull, kNear, kFar,
                                                  params_at(100.0f));
    for (float target : {150.0f, 400.0f, 1200.0f, 3000.0f, 4500.0f}) {
        EXPECT_NEAR(renderer::coc_from_depth(d_hull, kNear, kFar,
                                             params_at(target)),
                    first, 1e-6f)
            << "the player's hull changed blur because the TARGET moved to "
            << target << " GU -- the foreground must not depend on focus";
    }
    EXPECT_LT(first, 0.0f) << "the foreground should actually be defocused";
}

TEST(DofForeground, RampGivesAGradientAcrossTheHullRatherThanOneFlatValue) {
    // A uniform blur across a shape reads as a smeared TEXTURE; a gradient
    // reads as an object out of focus. Nose and tail must differ.
    const auto p = params_at(400.0f);
    const float nose = renderer::coc_from_depth(depth_for_z(18.0f), kNear, kFar, p);
    const float tail = renderer::coc_from_depth(depth_for_z(45.0f), kNear, kFar, p);
    EXPECT_LT(nose, tail) << "nearer geometry must be blurrier";
    EXPECT_GT(tail - nose, 0.15f)
        << "the gradient across a hull is too flat to read as defocus";
}

TEST(DofForeground, SharpAtAndBeyondTheRampStart) {
    const auto p = params_at(400.0f);
    EXPECT_NEAR(renderer::coc_from_depth(depth_for_z(60.0f), kNear, kFar, p),
                0.0f, 1e-4f);
    EXPECT_NEAR(renderer::coc_from_depth(depth_for_z(90.0f), kNear, kFar, p),
                0.0f, 1e-4f);
}

TEST(DofForeground, SaturatesAtFullBlurInsideTheRamp) {
    const auto p = params_at(400.0f);
    EXPECT_NEAR(renderer::coc_from_depth(depth_for_z(15.0f), kNear, kFar, p),
                -1.0f, 1e-3f);
    EXPECT_NEAR(renderer::coc_from_depth(depth_for_z(5.0f), kNear, kFar, p),
                -1.0f, 1e-3f);
}

TEST(DofForeground, DegenerateRampDisablesForegroundBlurRatherThanDividingByZero) {
    auto p = params_at(400.0f);
    p.near_sharp_gu = p.near_full_gu;    // zero span
    EXPECT_EQ(renderer::coc_from_depth(depth_for_z(20.0f), kNear, kFar, p), 0.0f);
}

TEST(DofForeground, BackgroundIsStillAThinLens) {
    // Only the near side changed; the far side keeps its ratio and its ceiling.
    const auto p = params_at(100.0f);
    EXPECT_NEAR(renderer::coc_from_depth(depth_for_z(125.0f), kNear, kFar, p),
                0.2f, 1e-3f);
    EXPECT_NEAR(renderer::coc_from_depth(depth_for_z(2000.0f), kNear, kFar, p),
                0.4f, 1e-3f);
}
