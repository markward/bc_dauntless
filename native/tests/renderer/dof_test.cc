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

// Near field is signed negative and clamps hard at -1. At half the focus
// distance the thin-lens term is exactly -1, which is the clamp boundary.
TEST(Dof, NearFieldClampsAtMinusOne) {
    const auto p = params_at(100.0f);
    EXPECT_NEAR(renderer::coc_from_depth(depth_for_z(50.0f), kNear, kFar, p),
                -1.0f, 1e-3f);
    // Closer still stays clamped, never overshoots.
    EXPECT_NEAR(renderer::coc_from_depth(depth_for_z(10.0f), kNear, kFar, p),
                -1.0f, 1e-3f);
}

TEST(Dof, NearFieldBelowTheClampIsProportional) {
    const auto p = params_at(100.0f);
    // z=80: 1 - 100/80 = -0.25
    EXPECT_NEAR(renderer::coc_from_depth(depth_for_z(80.0f), kNear, kFar, p),
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
    // z=80: -0.25 * 0.5 = -0.125
    EXPECT_NEAR(renderer::coc_from_depth(depth_for_z(80.0f), kNear, kFar, p),
                -0.125f, 1e-3f);
    // z=200: 0.5 * 0.25 = 0.125, under the ceiling so uncapped.
    EXPECT_NEAR(renderer::coc_from_depth(depth_for_z(200.0f), kNear, kFar, p),
                0.125f, 1e-3f);
}

}  // namespace
