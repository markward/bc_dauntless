// native/tests/renderer/letterbox_pass_test.cc
//
// The cutscene letterbox is a renderer pass, not CEF DOM, so that every UI
// element draws over it by construction. See
// docs/superpowers/specs/2026-07-13-letterbox-renderer-pass-design.md
#include <gtest/gtest.h>

#include <renderer/letterbox_pass.h>
#include <renderer/window.h>

#include <glad/glad.h>

#include <cmath>
#include <limits>
#include <memory>
#include <vector>

TEST(LetterboxState, ClampsAndRoundTrips) {
    renderer::letterbox::set_covered(0.125f);
    EXPECT_FLOAT_EQ(renderer::letterbox::covered(), 0.125f);
    renderer::letterbox::set_covered(5.0f);
    EXPECT_FLOAT_EQ(renderer::letterbox::covered(), 1.0f);
    renderer::letterbox::set_covered(-1.0f);
    EXPECT_FLOAT_EQ(renderer::letterbox::covered(), 0.0f);
    renderer::letterbox::set_covered(0.0f);      // restore for other tests
}

TEST(LetterboxState, RejectsNonFiniteInput) {
    // A NaN fCoveredArea from a mission script (StartCutscene(1.0,
    // float('nan'))) must not survive into g_covered: std::clamp's
    // both-comparisons-false-for-NaN behaviour lets it through untouched,
    // and draw() would then feed it to std::lround() -- unspecified result,
    // possibly a garbage scissor rect.
    renderer::letterbox::set_covered(std::numeric_limits<float>::quiet_NaN());
    EXPECT_FLOAT_EQ(renderer::letterbox::covered(), 0.0f);

    renderer::letterbox::set_covered(std::numeric_limits<float>::infinity());
    EXPECT_FLOAT_EQ(renderer::letterbox::covered(), 0.0f);

    renderer::letterbox::set_covered(0.0f);      // restore for other tests
}

namespace {

// GL-only fixture: the pass needs no BC assets, no model, no camera.
class LetterboxPassTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    int fw = 0, fh = 0;

    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(256, 256, "letterbox-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        w->framebuffer_size(&fw, &fh);   // may be 512x512 on a HiDPI display
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glViewport(0, 0, fw, fh);
    }

    void TearDown() override { renderer::letterbox::set_covered(0.0f); }

    // Fill FBO 0 with pure red so any black we read back came from the pass.
    void fill_red() {
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glDisable(GL_SCISSOR_TEST);
        glClearColor(1.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT);
    }

    bool is_black_at(int y) {
        unsigned char px[4] = {0};
        glReadPixels(fw / 2, y, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
        return px[0] == 0 && px[1] == 0 && px[2] == 0;
    }
};

}  // namespace

TEST_F(LetterboxPassTest, ZeroCoverageDrawsNothing) {
    fill_red();
    renderer::letterbox::set_covered(0.0f);
    renderer::letterbox::draw(fw, fh);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
    EXPECT_FALSE(is_black_at(fh - 2));      // top row still red
    EXPECT_FALSE(is_black_at(1));           // bottom row still red
}

TEST_F(LetterboxPassTest, BarsAreBlackAndTheCentreBandIsNot) {
    fill_red();
    // 0.5 total => a quarter of the height per bar: rows [0, fh/4) and
    // [fh - fh/4, fh). Sample well inside each bar and at mid-screen.
    renderer::letterbox::set_covered(0.5f);
    renderer::letterbox::draw(fw, fh);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
    EXPECT_TRUE(is_black_at(fh - 2));               // inside the top bar
    EXPECT_TRUE(is_black_at(1));                    // inside the bottom bar
    EXPECT_FALSE(is_black_at(fh / 2));              // scene survives in the middle
    EXPECT_FALSE(is_black_at(fh / 2 + fh / 8));     // scene sample well below the top bar

    // Straddle both bar edges so a wrong split fraction (e.g. drawing bars
    // at HALF the required size) fails these assertions even though the
    // samples above still pass. bar = fh/4 is the per-bar height at
    // covered=0.5; offsets of 1-2px keep the checks robust to draw()'s
    // std::lround rounding.
    const int bar = fh / 4;
    EXPECT_TRUE(is_black_at(fh - bar + 1));    // just INSIDE the top bar's lower edge
    EXPECT_FALSE(is_black_at(fh - bar - 2));   // just OUTSIDE it — scene must survive
    EXPECT_TRUE(is_black_at(bar - 2));         // just INSIDE the bottom bar's upper edge
    EXPECT_FALSE(is_black_at(bar + 1));        // just OUTSIDE it
}

TEST_F(LetterboxPassTest, LeavesScissorTestDisabledForTheCefComposite) {
    // ui_cef::composite() (which runs right after this pass) disables
    // GL_SCISSOR_TEST itself, so a leak here would not clip the CEF overlay
    // directly. But composite() RESTORES whatever scissor state was active
    // before it ran, so a leaked enabled scissor would survive into the
    // START of the next frame and clip that frame's early target clears
    // (shadow/viewscreen/HDR) to the last bar rectangle.
    fill_red();
    renderer::letterbox::set_covered(0.5f);
    renderer::letterbox::draw(fw, fh);
    EXPECT_FALSE(glIsEnabled(GL_SCISSOR_TEST));
}
