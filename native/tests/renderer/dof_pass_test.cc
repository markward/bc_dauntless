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
TEST_F(DofPassTest, FarFieldSoftensAStepEdge) {
    renderer::HdrTarget src, dst;
    fill_step_edge(src, depth_for_z(500.0f));   // focus at 100 -> far field
    dst.resize(kSize, kSize);

    renderer::DofPass pass;
    pass.draw(src.color_texture(), src.depth_texture(), dst.fbo(),
              kSize, kSize, kNear, kFar, params_at(100.0f));

    EXPECT_GT(transition_width(read_edge_row(dst)), 0);
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
    ASSERT_GT(renderer::coc_from_depth(depth_for_z(4000.0f), kNear, kFar, p), 0.0f);
    {
        renderer::HdrTarget src, dst;
        fill_step_edge(src, depth_for_z(4000.0f));
        dst.resize(kSize, kSize);
        renderer::DofPass pass;
        pass.draw(src.color_texture(), src.depth_texture(), dst.fbo(),
                  kSize, kSize, kNear, kFar, p);
        EXPECT_GT(transition_width(read_edge_row(dst)), 0)
            << "shader left sharp a depth dof.h blurs";
    }
}

}  // namespace
