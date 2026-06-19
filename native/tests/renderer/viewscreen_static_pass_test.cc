#include <gtest/gtest.h>
#include <memory>
#include <vector>
#include <glad/glad.h>
#include <renderer/window.h>
#include <renderer/pipeline.h>
#include <renderer/hdr_target.h>
#include <renderer/viewscreen_static_pass.h>

static std::vector<float> read_center(int w, int h) {
    std::vector<float> buf(static_cast<size_t>(w) * h * 4);
    glReadPixels(0, 0, w, h, GL_RGBA, GL_FLOAT, buf.data());
    return buf;  // pixel 0 is enough for a solid fill
}

TEST(ViewscreenStaticPass, BlendsNoiseOverFeed) {
    std::unique_ptr<renderer::Window> win;
    try { win = std::make_unique<renderer::Window>(16, 16, "vs-static", false); }
    catch (const std::runtime_error& e) { GTEST_SKIP() << e.what(); }

    renderer::Pipeline pipe;
    renderer::HdrTarget target;
    target.resize(16, 16);
    target.bind();
    glClearColor(0.2f, 0.4f, 0.6f, 1.0f);          // "feed"
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    // Inject a 1x1 mid-grey noise texture directly (bypass file load).
    renderer::ViewscreenStaticPass pass;
    pass.set_solid_noise_for_test(0.8f);            // helper: 1x1 (0.8,0.8,0.8)
    pass.render(pipe.viewscreen_static_shader(), /*intensity=*/0.5f, /*t=*/0.0);

    auto px = read_center(16, 16);
    // mix(0.2, 0.8, 0.5) = 0.5 ; mix(0.4,0.8,0.5)=0.6 ; mix(0.6,0.8,0.5)=0.7
    EXPECT_NEAR(px[0], 0.5f, 0.02f);
    EXPECT_NEAR(px[1], 0.6f, 0.02f);
    EXPECT_NEAR(px[2], 0.7f, 0.02f);
}

TEST(ViewscreenStaticPass, IntensityZeroLeavesFeed) {
    std::unique_ptr<renderer::Window> win;
    try { win = std::make_unique<renderer::Window>(16, 16, "vs-static0", false); }
    catch (const std::runtime_error& e) { GTEST_SKIP() << e.what(); }
    renderer::Pipeline pipe;
    renderer::HdrTarget target; target.resize(16, 16); target.bind();
    glClearColor(0.2f, 0.4f, 0.6f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    renderer::ViewscreenStaticPass pass;
    pass.set_solid_noise_for_test(0.8f);
    pass.render(pipe.viewscreen_static_shader(), 0.0f, 0.0);
    auto px = read_center(16, 16);
    EXPECT_NEAR(px[0], 0.2f, 0.001f);
    EXPECT_NEAR(px[1], 0.4f, 0.001f);
    EXPECT_NEAR(px[2], 0.6f, 0.001f);
}
