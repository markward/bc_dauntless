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
// y up) -- how the scene is stored in the viewscreen RTT. The readout sits at
// the TOP-LEFT, i.e. small x and HIGH y. Positions come from readout_layout();
// LayoutAt640x360 pins that arithmetic against hand-derived numbers.

namespace {

constexpr int kW = 640;
constexpr int kH = 360;
// Mid grey: white text reads ABOVE it and the black shadow BELOW it.
constexpr float kGrey = 0.4f;
constexpr std::array<float, 3> kFeed{kGrey, kGrey, kGrey};
constexpr std::array<float, 3> kRed{216.f / 255.f, 43.f / 255.f, 43.f / 255.f};
constexpr std::array<float, 3> kNeutral{1.f, 1.f, 0.686f};

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

renderer::ViewscreenBars bars(const std::string& name, const std::string& detail,
                              std::array<float, 3> dot) {
    renderer::ViewscreenBars b;
    b.visible = true;
    b.name = name;
    b.detail = detail;
    b.dot_rgb = dot;
    return b;
}

/// A read-back rectangle [x0,x1) x [y0,y1) in GL pixels.
struct Region {
    int x0, y0, x1, y1;
    std::vector<float> px;
    Region(int ax0, int ay0, int ax1, int ay1) : x0(ax0), y0(ay0), x1(ax1), y1(ay1) {
        px.resize(static_cast<size_t>(x1 - x0) * (y1 - y0) * 4);
        glReadPixels(x0, y0, x1 - x0, y1 - y0, GL_RGBA, GL_FLOAT, px.data());
    }
    std::array<float, 3> at(int x, int y) const {
        const size_t i = (static_cast<size_t>(y - y0) * (x1 - x0) + (x - x0)) * 4;
        return {px[i], px[i + 1], px[i + 2]};
    }
};

bool near_white(const std::array<float, 3>& p) {
    return std::min({p[0], p[1], p[2]}) > kGrey + 0.25f;
}

/// Rows [lo, hi] holding near-white ink in the region, or {1, 0} when none.
std::pair<int, int> ink_rows(const Region& r) {
    int lo = r.y1, hi = r.y0 - 1;
    for (int y = r.y0; y < r.y1; ++y)
        for (int x = r.x0; x < r.x1; ++x)
            if (near_white(r.at(x, y))) { lo = std::min(lo, y); hi = std::max(hi, y); }
    if (hi < lo) return {1, 0};
    return {lo, hi};
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
    renderer::ViewscreenReadoutLayout lay() const { return pass.readout_layout(kW, kH); }

    std::unique_ptr<renderer::Window> win;
    std::unique_ptr<renderer::Pipeline> pipe;
    std::unique_ptr<renderer::HdrTarget> target;
    renderer::ViewscreenBarsPass pass;
};

}  // namespace

// Font facts (native/assets/fonts/viewscreen_antonio.json): 'H' bearing_y 24
// (cap height), ascent 33, line_height 37 (descent 4). At 640 wide, s = 1:
//   cap top 1 = 360 - 18 = 342; baseline 1 = 342 - 24 = 318
//   dot: d = 0.6 * 24 = 14.4, left 24 -> centre x 31.2, centre y 318 + 12 = 330
//   name x = round(24 + 14.4 + 7) = 45
//   line 1 descent = 318 - 4 = 314; line 2 ascent top = 314 - 4 = 310;
//   baseline 2 = round(310 - 0.7 * 33) = round(286.9) = 287
TEST_F(ViewscreenBarsPass, LayoutAt640x360) {
    ASSERT_TRUE(load());
    const auto l = lay();
    EXPECT_FLOAT_EQ(l.scale1, 1.0f);
    EXPECT_FLOAT_EQ(l.scale2, 0.7f);
    EXPECT_FLOAT_EQ(l.cap_height1, 24.f);
    EXPECT_FLOAT_EQ(l.baseline1, 318.f);
    EXPECT_FLOAT_EQ(l.baseline2, 287.f);
    EXPECT_NEAR(l.dot_cx, 31.2f, 1e-4f);
    EXPECT_NEAR(l.dot_cy, 330.f, 1e-4f);
    EXPECT_NEAR(l.dot_r, 7.2f, 1e-4f);
    EXPECT_FLOAT_EQ(l.name_x, 45.f);
    EXPECT_FLOAT_EQ(l.max_w, 640.f - 45.f - 24.f);
    // Every pixel value scales with the width.
    const auto big = pass.readout_layout(2 * kW, 2 * kH);
    EXPECT_FLOAT_EQ(big.scale1, 2.0f);
    EXPECT_NEAR(big.dot_cx, 62.4f, 1e-4f);
    EXPECT_FLOAT_EQ(big.baseline1, 720.f - 36.f - 48.f);
}

TEST_F(ViewscreenBarsPass, DrawsTheAffiliationDot) {
    ASSERT_TRUE(load());
    draw(bars("KESSOK", "DST: 2.45 km  SPD: 1414 kph", kRed));
    const auto l = lay();
    expect_rgb(pixel(static_cast<int>(l.dot_cx), static_cast<int>(l.dot_cy)),
               kRed, 0.03f, "dot centre");
}

TEST_F(ViewscreenBarsPass, CapsTheDotColour) {
    ASSERT_TRUE(load());
    draw(bars("KESSOK", "", kNeutral));
    const auto l = lay();
    const auto p = pixel(static_cast<int>(l.dot_cx), static_cast<int>(l.dot_cy));
    const float mx = std::max({p[0], p[1], p[2]});
    EXPECT_LE(mx, renderer::kVsBarsChannelCap + 0.01f);
    EXPECT_GT(mx, renderer::kVsBarsChannelCap - 0.02f);   // drawn, not skipped
}

TEST_F(ViewscreenBarsPass, DrawsWhiteNameTextTopLeft) {
    ASSERT_TRUE(load());
    draw(bars("KESSOK", "", kRed));
    const auto l = lay();
    const int y_top = static_cast<int>(l.baseline1 + l.cap_height1) + 1;
    const Region r(static_cast<int>(l.name_x), static_cast<int>(l.baseline1), 320, y_top);
    int white = 0;
    for (int y = r.y0; y < r.y1; ++y)
        for (int x = r.x0; x < r.x1; ++x) {
            const auto p = r.at(x, y);
            if (near_white(p)) {
                ++white;
                EXPECT_LE(std::max({p[0], p[1], p[2]}), renderer::kVsBarsChannelCap + 0.01f);
            }
        }
    EXPECT_GT(white, 20);
}

TEST_F(ViewscreenBarsPass, DrawsSmallerDetailLineBelow) {
    ASSERT_TRUE(load());
    draw(bars("H", "H", kRed));
    const auto l = lay();
    const int x0 = static_cast<int>(l.name_x) - 1;
    const int split = static_cast<int>(l.baseline1) - 2;   // between the lines
    const auto [a_lo, a_hi] = ink_rows(Region(x0, split, x0 + 40, kH));
    const auto [b_lo, b_hi] = ink_rows(Region(x0, split - 60, x0 + 40, split));
    ASSERT_LE(a_lo, a_hi) << "no line-1 ink";
    ASSERT_LE(b_lo, b_hi) << "no line-2 ink";
    EXPECT_LT(b_hi, a_lo) << "line 2 sits below line 1";
    EXPECT_LT(b_hi - b_lo, a_hi - a_lo) << "line 2 is smaller";
    // Line 2 starts at the name's x, not the dot's: no ink left of the name.
    const auto [d_lo, d_hi] = ink_rows(Region(0, split - 60, x0, split));
    EXPECT_GT(d_lo, d_hi) << "line 2 must not start under the dot";
}

TEST_F(ViewscreenBarsPass, NoBackgroundOrBandAnywhere) {
    ASSERT_TRUE(load());
    draw(bars("KESSOK", "DST: 2.45 km  SPD: 1414 kph", kRed));
    expect_rgb(pixel(320, 357), kFeed, 0.001f, "old top band, middle");
    expect_rgb(pixel(600, 357), kFeed, 0.001f, "old top band, right");
    expect_rgb(pixel(4, 357), kFeed, 0.001f, "old top band, left");
    expect_rgb(pixel(320, 2), kFeed, 0.001f, "old bottom band");
    expect_rgb(pixel(320, 180), kFeed, 0.001f, "picture centre");
}

TEST_F(ViewscreenBarsPass, ShadowIsDrawn) {
    ASSERT_TRUE(load());
    draw(bars("KESSOK", "", kRed));
    const auto l = lay();
    const Region r(static_cast<int>(l.name_x), static_cast<int>(l.baseline1) - 4, 200,
                   static_cast<int>(l.baseline1 + l.cap_height1) + 2);
    int dark = 0;
    for (int y = r.y0; y < r.y1; ++y)
        for (int x = r.x0; x < r.x1; ++x) {
            const auto p = r.at(x, y);
            if (std::max({p[0], p[1], p[2]}) < kGrey - 0.1f) ++dark;
        }
    EXPECT_GT(dark, 5);
}

TEST_F(ViewscreenBarsPass, TextIsRightWayUp) {
    ASSERT_TRUE(load());
    draw(bars("T", "", kRed));
    const auto l = lay();
    // Name only (right of the dot), line 1's rows.
    const Region r(static_cast<int>(l.name_x) - 1, static_cast<int>(l.baseline1) - 4,
                   static_cast<int>(l.name_x) + 40, kH);
    auto cov = [&](int x, int y) { return std::max(0.0f, r.at(x, y)[1] - kGrey); };
    int y0 = r.y1, y1 = r.y0 - 1;
    for (int y = r.y0; y < r.y1; ++y)
        for (int x = r.x0; x < r.x1; ++x)
            if (cov(x, y) > 0.05f) { y0 = std::min(y0, y); y1 = std::max(y1, y); }
    ASSERT_LT(y0, y1) << "no glyph pixels on line 1";
    const float mid = 0.5f * (y0 + y1);
    float upper = 0.f, lower = 0.f;
    for (int y = y0; y <= y1; ++y)
        for (int x = r.x0; x < r.x1; ++x)
            (y > mid ? upper : lower) += (y == mid ? 0.f : cov(x, y));
    EXPECT_GT(upper, lower * 1.1f) << "a T is wide at the top (higher y)";
}

TEST_F(ViewscreenBarsPass, InvisibleDrawsNothing) {
    ASSERT_TRUE(load());
    auto b = bars("KESSOK", "DST: 1.00 km  SPD: 0 kph", kRed);
    b.visible = false;
    draw(b);
    const auto l = lay();
    expect_rgb(pixel(static_cast<int>(l.dot_cx), static_cast<int>(l.dot_cy)), kFeed,
               0.001f, "dot");
    const auto [lo, hi] = ink_rows(Region(0, 200, 320, kH));
    EXPECT_GT(lo, hi) << "no text drawn";
}

TEST_F(ViewscreenBarsPass, MissingGlyphAdvancesWithoutDrawing) {
    ASSERT_TRUE(load());
    const auto space = pass.layout_line_for_test(" ", 1e9f, 1.f);   // drawn glyphs only
    EXPECT_TRUE(space.empty());
    const auto pens = pass.layout_line_for_test("A\xc3\xa9" "B", 1e9f, 1.f);
    ASSERT_EQ(pens.size(), 2u) << "only A and B are drawn";
    const float a_adv = pens[0].second;
    const auto sp = pass.layout_line_for_test("A A", 1e9f, 1.f);
    ASSERT_EQ(sp.size(), 2u);
    const float space_adv = sp[1].first - sp[0].first - a_adv;
    EXPECT_GT(space_adv, 0.f);
    EXPECT_FLOAT_EQ(pens[0].first, 0.f);
    EXPECT_FLOAT_EQ(pens[1].first, a_adv + 2.f * space_adv);
}

TEST_F(ViewscreenBarsPass, LongNameIsEllipsised) {
    ASSERT_TRUE(load());
    const auto l = lay();
    for (const float scale : {l.scale1, l.scale2}) {
        const std::string fit = pass.fit_for_test(std::string(200, 'W'), l.max_w, scale);
        ASSERT_GE(fit.size(), 3u);
        EXPECT_EQ(fit.substr(fit.size() - 3), "...");
        EXPECT_LT(fit.size(), 200u);
        const auto pens = pass.layout_line_for_test(fit, 1e9f, scale);
        ASSERT_FALSE(pens.empty());
        EXPECT_LE(pens.back().first + pens.back().second, l.max_w);
        // A string that fits is drawn whole.
        EXPECT_EQ(pass.fit_for_test("KESSOK", l.max_w, scale), "KESSOK");
    }
    // The smaller line fits more of the same glyphs.
    EXPECT_GT(pass.fit_for_test(std::string(200, 'W'), l.max_w, l.scale2).size(),
              pass.fit_for_test(std::string(200, 'W'), l.max_w, l.scale1).size());
}

TEST_F(ViewscreenBarsPass, BadFontPathFailsSoft) {
    EXPECT_FALSE(pass.load_font("/nonexistent.json"));
    EXPECT_FALSE(pass.has_font());
    draw(bars("KESSOK", "DST: 1.00 km  SPD: 0 kph", kRed));
    const auto [lo, hi] = ink_rows(Region(0, 200, 320, kH));
    EXPECT_GT(lo, hi) << "no text drawn";
    expect_rgb(pixel(31, 330), kFeed, 0.001f, "where the dot would be");
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
