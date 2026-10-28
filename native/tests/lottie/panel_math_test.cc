#include <lottie/panel_math.h>

#include <gtest/gtest.h>

#include <cstdint>
#include <vector>

using namespace lottie;

TEST(PanelTick, SixtyFpsFileAdvancesAtThirtyHz) {
    PanelTick a = panel_tick(10.0, 10.0, 144.0f, 60.0f);
    EXPECT_EQ(a.tick, 0);
    EXPECT_FLOAT_EQ(a.frame, 0.0f);
    EXPECT_EQ(panel_tick(10.0 + 1.0 / 60.0, 10.0, 144.0f, 60.0f).tick, 0);
    PanelTick b = panel_tick(10.0 + 1.0 / 30.0, 10.0, 144.0f, 60.0f);
    EXPECT_EQ(b.tick, 1);
    EXPECT_FLOAT_EQ(b.frame, 2.0f);
}

TEST(PanelTick, WrapsAndKeepsCounting) {
    PanelTick p = panel_tick(5.0 + 2.4, 5.0, 144.0f, 60.0f);
    EXPECT_FLOAT_EQ(p.frame, 0.0f);
    EXPECT_EQ(p.tick, 72);
}

TEST(PanelTick, SlowFileTicksAtItsOwnRate) {
    PanelTick p = panel_tick(3.0 + 0.5, 3.0, 48.0f, 24.0f);
    EXPECT_EQ(p.tick, 12);
    EXPECT_FLOAT_EQ(p.frame, 12.0f);
}

TEST(PanelTick, SameTimeSameTick) {
    PanelTick a = panel_tick(7.123, 1.0, 144.0f, 60.0f);
    PanelTick b = panel_tick(7.123, 1.0, 144.0f, 60.0f);
    EXPECT_EQ(a.tick, b.tick);
    EXPECT_FLOAT_EQ(a.frame, b.frame);
}

TEST(PanelSize, Rounds) {
    PanelSize a = panel_size(640, 320, 1024);
    EXPECT_EQ(a.w, 1024u); EXPECT_EQ(a.h, 512u);
    PanelSize b = panel_size(320, 640, 512);
    EXPECT_EQ(b.w, 256u); EXPECT_EQ(b.h, 512u);
    PanelSize c = panel_size(640, 321, 1024);
    EXPECT_EQ(c.w, 1024u); EXPECT_EQ(c.h, 514u);
    PanelSize d = panel_size(1, 1000, 2048);
    EXPECT_EQ(d.w, 2u); EXPECT_EQ(d.h, 2048u);
}

namespace {
assets::Image make_still(std::uint32_t w, std::uint32_t h, assets::Image::Format f,
                         std::vector<std::uint8_t> px) {
    assets::Image im;
    im.width = w; im.height = h; im.format = f; im.pixels = std::move(px);
    return im;
}
}  // namespace

TEST(Composite, TransparentLottieShowsStill) {
    std::vector<std::uint8_t> px = {1,2,3,4, 50,60,70,80, 100,110,120,130, 200,210,220,230};
    auto still = make_still(2, 2, assets::Image::Format::RGBA8, px);
    std::vector<std::uint8_t> l(16, 0);
    EXPECT_EQ(composite_panel(still, l, 2, 2), px);
}

TEST(Composite, OpaqueLottieReplaces) {
    auto still = make_still(1, 1, assets::Image::Format::RGBA8, {9, 9, 9, 9});
    std::vector<std::uint8_t> l = {0,255,0,255, 0,255,0,255};
    auto out = composite_panel(still, l, 2, 1);
    EXPECT_EQ(out, l);
}

TEST(Composite, HalfAlphaOverAlphaZeroStill) {
    auto still = make_still(1, 1, assets::Image::Format::RGBA8, {0, 0, 0, 0});
    std::vector<std::uint8_t> l = {128, 128, 128, 128};
    EXPECT_EQ(composite_panel(still, l, 1, 1), l);
}

TEST(Composite, ScalesTheStill) {
    auto still = make_still(1, 1, assets::Image::Format::RGBA8, {10, 20, 30, 40});
    std::vector<std::uint8_t> l(4 * 8, 0);
    auto out = composite_panel(still, l, 4, 2);
    ASSERT_EQ(out.size(), 32u);
    for (int i = 0; i < 8; ++i) {
        EXPECT_EQ(out[i*4+0], 10); EXPECT_EQ(out[i*4+1], 20);
        EXPECT_EQ(out[i*4+2], 30); EXPECT_EQ(out[i*4+3], 40);
    }
}

TEST(Composite, AcceptsRgbStill) {
    auto still = make_still(1, 1, assets::Image::Format::RGB8, {10, 20, 30});
    std::vector<std::uint8_t> l(4, 0);
    auto out = composite_panel(still, l, 1, 1);
    EXPECT_EQ(out, (std::vector<std::uint8_t>{10, 20, 30, 255}));
}
