// native/tests/renderer/dof_pass_test.cc
//
// The GL half of DOF. These tests pin BEHAVIOUR that is observable through
// the framebuffer -- they cannot read the shader's CoC directly, so the
// anti-drift guard is the starfield-threshold pair at the bottom: it forces
// the shader's exemption to agree with dof.h's at the one depth where the
// two could silently diverge.
#include <gtest/gtest.h>
#include <glad/glad.h>
#include <renderer/dof.h>
#include <renderer/dof_pass.h>
#include <renderer/hdr_target.h>
#include <renderer/window.h>
#include <memory>
#include <vector>

namespace {

constexpr int   kSize = 64;
constexpr float kNear = 1.0f;
constexpr float kFar  = 5000.0f;

float depth_for_z(float z) {
    const float ndc = (kFar + kNear - 2.0f * kNear * kFar / z) / (kFar - kNear);
    return (ndc + 1.0f) * 0.5f;
}

class DofPassTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    void SetUp() override {
        try { w = std::make_unique<renderer::Window>(kSize, kSize, "dof-test", false); }
        catch (const std::runtime_error& e) { GTEST_SKIP() << "no GL: " << e.what(); }
    }

    /// Fill an HdrTarget with a vertical split (left half black, right half
    /// white) at a uniform depth. The step edge is what a blur visibly softens.
    void fill_step_edge(renderer::HdrTarget& t, float depth) {
        t.resize(kSize, kSize);
        t.bind();
        glEnable(GL_SCISSOR_TEST);
        glClearDepth(static_cast<double>(depth));

        glScissor(0, 0, kSize / 2, kSize);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

        glScissor(kSize / 2, 0, kSize / 2, kSize);
        glClearColor(1.0f, 1.0f, 1.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

        glDisable(GL_SCISSOR_TEST);
        glClearDepth(1.0);
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
    }

    /// Read the row of pixels straddling the step edge.
    std::vector<float> read_edge_row(const renderer::HdrTarget& t) {
        glBindFramebuffer(GL_READ_FRAMEBUFFER, t.fbo());
        std::vector<float> px(kSize * 4);
        glReadPixels(0, kSize / 2, kSize, 1, GL_RGBA, GL_FLOAT, px.data());
        glBindFramebuffer(GL_READ_FRAMEBUFFER, 0);
        std::vector<float> row(kSize);
        for (int i = 0; i < kSize; ++i) row[i] = px[i * 4];
        return row;
    }

    /// How many pixels along the row sit strictly between black and white.
    /// A sharp step has none; a blurred one has a band.
    int transition_width(const std::vector<float>& row) {
        int n = 0;
        for (float v : row) if (v > 0.02f && v < 0.98f) ++n;
        return n;
    }

    renderer::DofParams params_at(float focus_gu, float blend = 1.0f) {
        renderer::DofParams p;
        p.focus_gu        = focus_gu;
        p.blend           = blend;
        p.near_strength   = 1.0f;
        p.far_strength    = 1.0f;
        p.far_ceiling     = 0.4f;
        p.max_radius_frac = 0.05f;   // exaggerated so the blur is unmistakable
        // Foreground ramp for a 15 GU hull at the shipped 1x..4x radii. A ZERO
        // span means "no foreground blur" by design, so leaving these unset
        // would silently disable the whole near field in every test here.
        p.near_full_gu    = 15.0f;
        p.near_sharp_gu   = 60.0f;
        return p;
    }
};

// Geometry sitting exactly at the focus distance has CoC 0, so the pass is an
// identity. This is the guarantee that an in-focus subject stays crisp.
TEST_F(DofPassTest, AtFocusThePassIsIdentity) {
    renderer::HdrTarget src, dst;
    fill_step_edge(src, depth_for_z(100.0f));
    dst.resize(kSize, kSize);

    renderer::DofPass pass;
    pass.draw(src.color_texture(), src.depth_texture(), dst.fbo(),
              kSize, kSize, kNear, kFar, params_at(100.0f));

    EXPECT_EQ(transition_width(read_edge_row(dst)), 0);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// Geometry well beyond the focus distance defocuses, softening the step.
//
// This asserts a BAND, not just "> 0". `transition_width() > 0` is blind to
// magnitude: deleting the `* u_texel` conversion on dof.frag's tap offset (a
// 64x units error at this fixture's resolution, orders of magnitude worse at
// real resolution) still leaves some soft pixel somewhere and would pass a
// bare "> 0" check, even though it turns the whole row into a smear.
//
// Expected magnitude, worked from this fixture's own params_at(): dd = 1 -
// focus/z = 1 - 100/500 = 0.8, saturated at far_ceiling 0.4; max_radius_px =
// max_radius_frac * fh = 0.05 * 64 = 3.2 px; so center_r = 0.4 * 3.2 = 1.28
// px. The 24-tap Vogel kernel samples out to that radius (sqrt(t) spacing,
// t in (0,1]), softening roughly a +/-1.28 px window around the boundary,
// and GL_LINEAR sampling adds a little more. Measured in this environment:
// transition_width == 2. [1, 5] is generous enough to absorb filtering
// differences without losing discrimination: the u_texel deletion above
// produces width == 64 (the entire row), nowhere close to this band.
TEST_F(DofPassTest, FarFieldSoftensAStepEdge) {
    renderer::HdrTarget src, dst;
    fill_step_edge(src, depth_for_z(500.0f));   // focus at 100 -> far field
    dst.resize(kSize, kSize);

    renderer::DofPass pass;
    pass.draw(src.color_texture(), src.depth_texture(), dst.fbo(),
              kSize, kSize, kNear, kFar, params_at(100.0f));

    const int width = transition_width(read_edge_row(dst));
    EXPECT_GE(width, 1);
    EXPECT_LE(width, 5);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// blend == 0 means "no subject focused". Even if the host were to run the
// pass anyway, the image must come through untouched.
TEST_F(DofPassTest, ZeroBlendIsIdentity) {
    renderer::HdrTarget src, dst;
    fill_step_edge(src, depth_for_z(500.0f));
    dst.resize(kSize, kSize);

    renderer::DofPass pass;
    pass.draw(src.color_texture(), src.depth_texture(), dst.fbo(),
              kSize, kSize, kNear, kFar, params_at(100.0f, /*blend=*/0.0f));

    EXPECT_EQ(transition_width(read_edge_row(dst)), 0);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// SCATTER-AS-GATHER GUARD. Every fixture above is uniform-depth, so a tap's
// own CoC always equals the centre pixel's CoC and dof.frag's weight term
// `w = clamp(tap_r - r + 1.0, 0.0, 1.0)` is identically 1.0 by construction
// -- it can never be exercised there. Replacing that line with
// `float w = 1.0;` leaves every test above green. This fixture puts two
// DIFFERENT depths on either side of the step so the weight has real work
// to do: a sharp (in-focus) region next to a defocused one.
TEST_F(DofPassTest, ScatterAsGatherWeightStopsSharpBleedingIntoBlur) {
    renderer::HdrTarget src, dst;
    src.resize(kSize, kSize);
    src.bind();
    glEnable(GL_SCISSOR_TEST);

    // Left half: white, sitting exactly at the focus distance -- sharp,
    // coc == 0, so any tap landing here has its own tap_r == 0.
    glClearDepth(static_cast<double>(depth_for_z(100.0f)));
    glScissor(0, 0, kSize / 2, kSize);
    glClearColor(1.0f, 1.0f, 1.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    // Right half: black, far away -- defocused.
    glClearDepth(static_cast<double>(depth_for_z(2000.0f)));
    glScissor(kSize / 2, 0, kSize / 2, kSize);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    glDisable(GL_SCISSOR_TEST);
    glClearDepth(1.0);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    dst.resize(kSize, kSize);

    // Bigger radius than the other fixtures, and far_ceiling raised to 1.0
    // (not params_at()'s 0.4) so the far side's CoC is not capped well below
    // its geometric radius: max_radius_px = 0.2 * 64 = 12.8 px, dd = 1 -
    // 100/2000 = 0.95, so center_r = 0.95 * 12.8 ~= 12.2 px -- big enough
    // that an ungated tap would unmistakably reach across the boundary.
    renderer::DofParams p = params_at(100.0f);
    p.max_radius_frac = 0.2f;
    p.far_ceiling     = 1.0f;

    renderer::DofPass pass;
    pass.draw(src.color_texture(), src.depth_texture(), dst.fbo(),
              kSize, kSize, kNear, kFar, p);

    glBindFramebuffer(GL_READ_FRAMEBUFFER, dst.fbo());
    float px[4];
    // A few pixels INTO the defocused (black) side, near the boundary --
    // close enough for the wide kernel to reach across into the sharp white
    // region if nothing were stopping it. Measured in this environment:
    // 0.0074 with the weight intact, 0.29 with it replaced by `w = 1.0` --
    // 0.1 sits well clear of both.
    glReadPixels(kSize / 2 + 3, kSize / 2, 1, 1, GL_RGBA, GL_FLOAT, px);
    glBindFramebuffer(GL_READ_FRAMEBUFFER, 0);

    EXPECT_LT(px[0], 0.1f)
        << "sharp in-focus white bled across the depth boundary into the "
           "blurred region -- the scatter-as-gather weight is not gating "
           "taps by their OWN circle of confusion";
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// ANTI-DRIFT GUARD. dof.h and dof.frag hold the same CoC curve in two
// languages; nothing makes them agree automatically. These two cases
// bracket the starfield threshold, so a change to one file's exemption
// without the other turns one of them red.
TEST_F(DofPassTest, StarfieldThresholdAgreesWithTheCppReference) {
    const auto p = params_at(100.0f);

    // Inside the exemption: dof.h says CoC 0, so the shader must be identity.
    ASSERT_EQ(renderer::coc_from_depth(depth_for_z(4950.0f), kNear, kFar, p), 0.0f);
    {
        renderer::HdrTarget src, dst;
        fill_step_edge(src, depth_for_z(4950.0f));
        dst.resize(kSize, kSize);
        renderer::DofPass pass;
        pass.draw(src.color_texture(), src.depth_texture(), dst.fbo(),
                  kSize, kSize, kNear, kFar, p);
        EXPECT_EQ(transition_width(read_edge_row(dst)), 0)
            << "shader blurred a depth dof.h exempts";
    }

    // Outside it: dof.h says nonzero, so the shader must blur.
    //
    // Sampled at 4700 GU, not 4000: the exemption threshold is far * 0.98 =
    // 4900, so 4000 sits nowhere near it and this pair is blind to any
    // exemption factor above ~0.80 -- e.g. if the shader's 0.98 in dof.frag
    // silently drifted to 0.90 (threshold 4500), 4000 would still be caught
    // as "outside" by both languages and the test would stay green while the
    // two curves had already diverged. 4700 sits between a 0.90 threshold
    // (4500, wrongly exempts 4700) and the real 0.98 (4900, does not), so it
    // catches that drift. Not closer to 4900: at near=1, far=5000 the
    // depth-buffer values for e.g. 4890 vs 4900 differ by only ~1e-6 (~17
    // LSBs of a 24-bit depth buffer), which risks a flaky test; 4700 differs
    // from the 4900 threshold by ~3.5e-6 (~58 LSBs), comfortably stable.
    ASSERT_GT(renderer::coc_from_depth(depth_for_z(4700.0f), kNear, kFar, p), 0.0f);
    {
        renderer::HdrTarget src, dst;
        fill_step_edge(src, depth_for_z(4700.0f));
        dst.resize(kSize, kSize);
        renderer::DofPass pass;
        pass.draw(src.color_texture(), src.depth_texture(), dst.fbo(),
                  kSize, kSize, kNear, kFar, p);
        EXPECT_GT(transition_width(read_edge_row(dst)), 0)
            << "shader left sharp a depth dof.h blurs";
    }
}

}  // namespace

namespace {

// ── The near field, end to end through the shader ───────────────────────
//
// The CoC maths is covered by dof_test.cc, and the far field by the tests
// above. This is the link neither reaches: whether the SHADER's foreground
// branch, driven by the ramp uniforms, actually blurs. It is also the branch
// that silently does nothing if near_sharp_gu / near_full_gu fail to arrive,
// because a zero span is defined as "no foreground blur".

TEST_F(DofPassTest, ForegroundAtHullDistanceIsBlurred) {
    renderer::HdrTarget src, dst;
    // A hull 30 GU from the camera -- where the chase camera puts the player
    // ship -- with the subject far beyond it.
    fill_step_edge(src, depth_for_z(30.0f));
    dst.resize(kSize, kSize);

    renderer::DofPass pass;
    pass.draw(src.color_texture(), src.depth_texture(), dst.fbo(),
              kSize, kSize, kNear, kFar, params_at(400.0f));

    EXPECT_GT(transition_width(read_edge_row(dst)), 0)
        << "geometry 30 GU from the camera, with the subject at 400 GU, was "
           "left sharp -- the foreground ramp is not reaching the shader";
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(DofPassTest, ForegroundBlurIsUnchangedByTheSubjectsDistance) {
    // THE property the camera-anchored ramp exists for. The hull does not
    // move; its blur must not care where the target is.
    auto width_for = [&](float focus_gu) {
        renderer::HdrTarget src, dst;
        fill_step_edge(src, depth_for_z(30.0f));
        dst.resize(kSize, kSize);
        renderer::DofPass pass;
        pass.draw(src.color_texture(), src.depth_texture(), dst.fbo(),
                  kSize, kSize, kNear, kFar, params_at(focus_gu));
        return transition_width(read_edge_row(dst));
    };
    const int near_target = width_for(150.0f);
    EXPECT_GT(near_target, 0) << "no foreground blur at all";
    for (float far_target : {600.0f, 2000.0f, 4000.0f}) {
        EXPECT_EQ(width_for(far_target), near_target)
            << "the hull's blur changed because the target moved to "
            << far_target << " GU";
    }
}

TEST_F(DofPassTest, AZeroSpanRampLeavesTheForegroundSharp) {
    // The documented degenerate case, pinned so it stays a deliberate no-op
    // rather than becoming a divide-by-zero.
    renderer::HdrTarget src, dst;
    fill_step_edge(src, depth_for_z(30.0f));
    dst.resize(kSize, kSize);

    auto p = params_at(400.0f);
    p.near_sharp_gu = p.near_full_gu;
    renderer::DofPass pass;
    pass.draw(src.color_texture(), src.depth_texture(), dst.fbo(),
              kSize, kSize, kNear, kFar, p);

    EXPECT_EQ(transition_width(read_edge_row(dst)), 0);
}

}  // namespace
