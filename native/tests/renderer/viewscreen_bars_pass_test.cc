#include <gtest/gtest.h>
#include <algorithm>
#include <array>
#include <cmath>
#include <memory>
#include <string>
#include <vector>
#include <glad/glad.h>
#include <renderer/window.h>
#include <renderer/pipeline.h>
#include <renderer/hdr_target.h>
#include <renderer/viewscreen_bars_pass.h>

// All pixel coordinates are GL framebuffer coordinates (origin bottom-left,
// y up) -- how the scene is stored in the viewscreen RTT. On a 640x360 target
// the top band is y in [324, 360), the bottom band y in [0, 36).

namespace {

constexpr int kW = 640;
constexpr int kH = 360;
constexpr std::array<float, 3> kFeed{0.1f, 0.3f, 0.5f};
constexpr std::array<float, 3> kRed{216.f / 255.f, 43.f / 255.f, 43.f / 255.f};
constexpr std::array<float, 3> kWhite{1.f, 1.f, 1.f};

std::string font_path() {
    return std::string(OPEN_STBC_PROJECT_ROOT) +
           "/native/assets/fonts/viewscreen_antonio.json";
}

std::array<float, 3> pixel(int x, int y) {
    float px[4] = {0, 0, 0, 0};
    glReadPixels(x, y, 1, 1, GL_RGBA, GL_FLOAT, px);
    return {px[0], px[1], px[2]};
}

void expect_rgb(const std::array<float, 3>& got, const std::array<float, 3>& want,
                float tol, const char* what) {
    for (int c = 0; c < 3; ++c)
        EXPECT_NEAR(got[c], want[c], tol) << what << " channel " << c;
}

renderer::ViewscreenBars bars(const std::string& top, const std::string& bottom,
                              std::array<float, 3> band, std::array<float, 3> text) {
    renderer::ViewscreenBars b;
    b.visible = true;
    b.top = top;
    b.bottom = bottom;
    b.band_rgb = band;
    b.text_rgb = text;
    return b;
}

class ViewscreenBarsPass : public ::testing::Test {
protected:
    void SetUp() override {
        try { win = std::make_unique<renderer::Window>(kW, kH, "vs-bars", false); }
        catch (const std::runtime_error& e) { GTEST_SKIP() << e.what(); }
        pipe = std::make_unique<renderer::Pipeline>();
        target = std::make_unique<renderer::HdrTarget>();
        target->resize(kW, kH);
        target->bind();
        glClearColor(kFeed[0], kFeed[1], kFeed[2], 1.0f);   // "feed"
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    }
    void TearDown() override {
        if (win) glBindFramebuffer(GL_FRAMEBUFFER, 0);
    }
    void draw(const renderer::ViewscreenBars& b) {
        pass.render(pipe->viewscreen_bars_shader(), b, kW, kH);
    }
    bool load() { return pass.load_font(font_path()); }

    std::unique_ptr<renderer::Window> win;
    std::unique_ptr<renderer::Pipeline> pipe;
    std::unique_ptr<renderer::HdrTarget> target;
    renderer::ViewscreenBarsPass pass;
};

}  // namespace

TEST_F(ViewscreenBarsPass, DrawsTheBandColourInBothBands) {
    ASSERT_TRUE(load());
    draw(bars("", "", kRed, kWhite));
    expect_rgb(pixel(4, 357), kRed, 0.02f, "top band");
    expect_rgb(pixel(4, 2), kRed, 0.02f, "bottom band");
    expect_rgb(pixel(320, 180), kFeed, 0.001f, "mid-picture");
}

TEST_F(ViewscreenBarsPass, CapsBrightChannels) {
    ASSERT_TRUE(load());
    draw(bars("", "", {1.f, 1.f, 0.686f}, {0.f, 0.f, 0.f}));
    for (const auto& p : {pixel(4, 357), pixel(4, 2)}) {
        const float mx = std::max({p[0], p[1], p[2]});
        EXPECT_LE(mx, renderer::kVsBarsChannelCap + 0.01f);
        EXPECT_GT(mx, renderer::kVsBarsChannelCap - 0.02f);   // drawn, not skipped
    }
}

TEST_F(ViewscreenBarsPass, RoundsOnlyTheInnerCorners) {
    ASSERT_TRUE(load());
    draw(bars("", "", kRed, kWhite));
    expect_rgb(pixel(1, 325), kFeed, 0.02f, "top band inner corner");
    expect_rgb(pixel(1, 358), kRed, 0.02f, "top band outer corner");
    expect_rgb(pixel(1, 34), kFeed, 0.02f, "bottom band inner corner");
    expect_rgb(pixel(1, 1), kRed, 0.02f, "bottom band outer corner");
}

TEST_F(ViewscreenBarsPass, DrawsTextInsideTheBand) {
    ASSERT_TRUE(load());
    draw(bars("KESSOK", "", kRed, kWhite));
    std::vector<float> buf(static_cast<size_t>(kW / 3) * 36 * 4);
    glReadPixels(kW / 3, 324, kW / 3, 36, GL_RGBA, GL_FLOAT, buf.data());
    int differing = 0;
    for (size_t i = 0; i < buf.size(); i += 4)
        if (std::fabs(buf[i + 1] - kRed[1]) > 0.1f) ++differing;
    EXPECT_GT(differing, 20);
}

TEST_F(ViewscreenBarsPass, TextIsRightWayUp) {
    ASSERT_TRUE(load());
    draw(bars("T", "", kRed, kWhite));
    std::vector<float> buf(static_cast<size_t>(kW) * 36 * 4);
    glReadPixels(0, 324, kW, 36, GL_RGBA, GL_FLOAT, buf.data());
    // Coverage = how far green moved off the band toward the (capped) white.
    auto cov = [&](int x, int y) {
        return std::max(0.0f, buf[(static_cast<size_t>(y) * kW + x) * 4 + 1] - kRed[1]);
    };
    // Scan the middle third only: the rounded inner corners at the band's
    // ends show the feed, which would read as "coverage" in the lower rows.
    const int xa = kW / 3, xb = 2 * kW / 3;
    int y0 = 36, y1 = -1;
    for (int y = 0; y < 36; ++y)
        for (int x = xa; x < xb; ++x)
            if (cov(x, y) > 0.05f) { y0 = std::min(y0, y); y1 = std::max(y1, y); }
    ASSERT_LT(y0, y1) << "no glyph pixels in the top band";
    const float mid = 0.5f * (y0 + y1);
    float upper = 0.f, lower = 0.f;
    for (int y = y0; y <= y1; ++y)
        for (int x = xa; x < xb; ++x)
            (y > mid ? upper : lower) += (y == mid ? 0.f : cov(x, y));
    EXPECT_GT(upper, lower * 1.1f) << "a T is wide at the top (higher y)";
}

TEST_F(ViewscreenBarsPass, InvisibleDrawsNothing) {
    ASSERT_TRUE(load());
    auto b = bars("KESSOK", "1.0 km / 0 kph", kRed, kWhite);
    b.visible = false;
    draw(b);
    expect_rgb(pixel(4, 357), kFeed, 0.001f, "top band");
    expect_rgb(pixel(4, 2), kFeed, 0.001f, "bottom band");
}

TEST_F(ViewscreenBarsPass, MissingGlyphAdvancesWithoutDrawing) {
    ASSERT_TRUE(load());
    const auto space = pass.layout_line_for_test(" ", 1e9f);   // drawn glyphs only
    EXPECT_TRUE(space.empty());
    const auto pens = pass.layout_line_for_test("A\xc3\xa9" "B", 1e9f);
    ASSERT_EQ(pens.size(), 2u) << "only A and B are drawn";
    const float a_adv = pens[0].second;
    const auto sp = pass.layout_line_for_test("A A", 1e9f);
    ASSERT_EQ(sp.size(), 2u);
    const float space_adv = sp[1].first - sp[0].first - a_adv;
    EXPECT_GT(space_adv, 0.f);
    EXPECT_FLOAT_EQ(pens[0].first, 0.f);
    EXPECT_FLOAT_EQ(pens[1].first, a_adv + 2.f * space_adv);
}

TEST_F(ViewscreenBarsPass, LongNameIsEllipsised) {
    ASSERT_TRUE(load());
    const std::string fit = pass.fit_for_test(std::string(200, 'W'), 604.f);
    ASSERT_GE(fit.size(), 3u);
    EXPECT_EQ(fit.substr(fit.size() - 3), "...");
    EXPECT_LT(fit.size(), 200u);
    const auto pens = pass.layout_line_for_test(fit, 1e9f);
    ASSERT_FALSE(pens.empty());
    EXPECT_LE(pens.back().first + pens.back().second, 604.f);
    // A string that fits is drawn whole.
    EXPECT_EQ(pass.fit_for_test("KESSOK", 604.f), "KESSOK");
}

TEST_F(ViewscreenBarsPass, BadFontPathFailsSoft) {
    EXPECT_FALSE(pass.load_font("/nonexistent.json"));
    EXPECT_FALSE(pass.has_font());
    draw(bars("KESSOK", "1.0 km / 0 kph", kRed, kWhite));
    expect_rgb(pixel(4, 357), kFeed, 0.001f, "top band");
    expect_rgb(pixel(4, 2), kFeed, 0.001f, "bottom band");
}

TEST_F(ViewscreenBarsPass, EnsureFontAttemptsOncePerDistinctRoot) {
    const std::string good = std::string(OPEN_STBC_PROJECT_ROOT) + "/native/assets";
    // A bad root fails, and the same bad root is not retried.
    EXPECT_FALSE(pass.ensure_font("/nonexistent_root"));
    EXPECT_FALSE(pass.has_font());
    EXPECT_FALSE(pass.ensure_font("/nonexistent_root"));
    // A new root (the later set_project_asset_root) gets a fresh attempt.
    EXPECT_TRUE(pass.ensure_font(good));
    EXPECT_TRUE(pass.has_font());
    // Once loaded, a further call is a cheap success.
    EXPECT_TRUE(pass.ensure_font(good));
}
