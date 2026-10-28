#include <lottie/panel_math.h>

#include <gtest/gtest.h>

#include <algorithm>
#include <cstdint>
#include <memory>
#include <utility>
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

// The worker's form: the same pixels, written into a caller's buffer (which
// it allocates default-initialised, so nothing is zeroed first).
TEST(Composite, IntoBufferMatchesTheVectorForm) {
    assets::Image still{2, 1, assets::Image::Format::RGBA8, {10, 20, 30, 255, 200, 100, 50, 255}};
    std::vector<std::uint8_t> l(4u * 2u * 4u, 0);
    l[0] = 128; l[3] = 128;   // one half-alpha red lottie texel
    const std::vector<std::uint8_t> want = composite_panel(still, l, 4, 2);
    std::unique_ptr<std::uint8_t[]> buf(new std::uint8_t[want.size()]);
    composite_panel_into(still, l, 4, 2, std::span<std::uint8_t>(buf.get(), want.size()));
    EXPECT_EQ(std::vector<std::uint8_t>(buf.get(), buf.get() + want.size()), want);
}

// The worker's cached form: the still scaled once per (panel, size), then a
// plain "over" per frame. It must give composite_panel_into's bytes exactly.
namespace {
std::vector<std::uint8_t> premul_lottie(std::uint32_t w, std::uint32_t h, int seed) {
    std::vector<std::uint8_t> l(static_cast<std::size_t>(w) * h * 4);
    for (std::size_t i = 0; i < l.size(); i += 4) {
        const auto a = static_cast<std::uint8_t>((i * 37 + seed * 101) % 256);
        l[i + 3] = a;
        for (int k = 0; k < 3; ++k)
            l[i + k] = a == 0 ? 0 : static_cast<std::uint8_t>((i * (k + 3) + seed) % (a + 1u));
    }
    return l;
}
assets::Image patterned_still(std::uint32_t w, std::uint32_t h, assets::Image::Format f) {
    const std::size_t n = f == assets::Image::Format::RGBA8 ? 4 : f == assets::Image::Format::RGB8 ? 3 : 1;
    std::vector<std::uint8_t> px(w * h * n);
    for (std::size_t i = 0; i < px.size(); ++i) px[i] = static_cast<std::uint8_t>((i * 53 + 7) % 256);
    return make_still(w, h, f, std::move(px));
}
}  // namespace

TEST(CachedStill, OverMatchesCompositeByteForByte) {
    using F = assets::Image::Format;
    for (F f : {F::RGBA8, F::RGB8, F::R8}) {
        const assets::Image still = patterned_still(5, 3, f);
        for (auto [w, h] : {std::pair<std::uint32_t, std::uint32_t>{7, 4}, {4, 2}, {5, 3}}) {
            const std::vector<std::uint8_t> scaled = scale_still_rgba(still, w, h);
            ASSERT_EQ(scaled.size(), static_cast<std::size_t>(w) * h * 4);
            for (int seed = 0; seed < 3; ++seed) {
                const auto l = premul_lottie(w, h, seed);
                std::vector<std::uint8_t> got(l.size(), 0xAB);
                over_into(scaled, l, got);
                EXPECT_EQ(got, composite_panel(still, l, w, h))
                    << "format " << static_cast<int>(f) << " " << w << "x" << h << " seed " << seed;
            }
        }
    }
}

TEST(CachedStill, ScaledStillIsTheCompositeOverNothing) {
    const assets::Image still = patterned_still(3, 2, assets::Image::Format::RGBA8);
    const std::vector<std::uint8_t> clear(6u * 4u * 4u, 0);
    EXPECT_EQ(scale_still_rgba(still, 6, 4), composite_panel(still, clear, 6, 4));
}

TEST(CachedStill, EmptyStillScalesToTransparentBlack) {
    EXPECT_EQ(scale_still_rgba(assets::Image{}, 3, 2), std::vector<std::uint8_t>(24, 0));
}

// The still is rounded to 8 bits once, before the over: within one step of
// blending the unrounded bilinear sample, as the pre-cache composite did.
TEST(CachedStill, WithinOneStepOfTheUnroundedStill) {
    const assets::Image still{2, 1, assets::Image::Format::RGBA8, {0, 0, 0, 0, 255, 255, 255, 255}};
    const std::uint32_t w = 7, h = 1;
    const auto l = premul_lottie(w, h, 1);
    const auto got = composite_panel(still, l, w, h);
    for (std::uint32_t x = 0; x < w; ++x) {
        const float fx = std::clamp((x + 0.5f) * 2.f / w - 0.5f, 0.f, 1.f);
        for (int k = 0; k < 4; ++k) {
            const float la = l[x * 4 + 3] / 255.f;
            const float want = (l[x * 4 + k] / 255.f + fx * (1.f - la)) * 255.f;
            EXPECT_NEAR(got[x * 4 + k], want, 1.0f) << x << " " << k;
        }
    }
}

// ── Partial uploads: only the rectangle that changed reaches the GPU.
namespace {
std::vector<std::uint8_t> image(std::uint32_t w, std::uint32_t h, std::uint8_t fill) {
    return std::vector<std::uint8_t>(static_cast<std::size_t>(w) * h * 4, fill);
}
void poke(std::vector<std::uint8_t>& img, std::uint32_t w, std::uint32_t x, std::uint32_t y,
          int channel) {
    img[(static_cast<std::size_t>(y) * w + x) * 4 + channel] ^= 0xFF;
}
}  // namespace

TEST(ChangedRect, IdenticalImagesHaveNone) {
    const auto a = image(5, 4, 7);
    EXPECT_FALSE(changed_rect(a, a, 5, 4).has_value());
}

TEST(ChangedRect, OnePixelInAnyChannel) {
    for (int channel = 0; channel < 4; ++channel) {
        const auto a = image(5, 4, 7);
        auto b = a;
        poke(b, 5, 3, 2, channel);
        const auto r = changed_rect(a, b, 5, 4);
        ASSERT_TRUE(r) << channel;
        EXPECT_EQ(r->x, 3u);
        EXPECT_EQ(r->y, 2u);
        EXPECT_EQ(r->w, 1u);
        EXPECT_EQ(r->h, 1u);
    }
}

TEST(ChangedRect, SpansTheOutermostChangedRowsAndColumns) {
    const auto a = image(8, 6, 0);
    auto b = a;
    poke(b, 8, 1, 4, 0);   // leftmost and lowest
    poke(b, 8, 6, 1, 3);   // rightmost and highest
    poke(b, 8, 3, 2, 1);   // inside
    const auto r = changed_rect(a, b, 8, 6);
    ASSERT_TRUE(r);
    EXPECT_EQ(r->x, 1u);
    EXPECT_EQ(r->y, 1u);
    EXPECT_EQ(r->w, 6u);
    EXPECT_EQ(r->h, 4u);
}

TEST(ChangedRect, CornersGiveTheWholeImage) {
    const auto a = image(4, 3, 9);
    auto b = a;
    poke(b, 4, 0, 0, 2);
    poke(b, 4, 3, 2, 2);
    const auto r = changed_rect(a, b, 4, 3);
    ASSERT_TRUE(r);
    EXPECT_EQ(r->x, 0u);
    EXPECT_EQ(r->y, 0u);
    EXPECT_EQ(r->w, 4u);
    EXPECT_EQ(r->h, 3u);
}

TEST(CopyRect, PacksTheRectangleRowByRow) {
    std::vector<std::uint8_t> img(4 * 3 * 4);
    for (std::size_t i = 0; i < img.size(); ++i) img[i] = static_cast<std::uint8_t>(i);
    std::vector<std::uint8_t> out(2 * 2 * 4, 0xAA);
    copy_rect(img, 4, PanelRect{1, 1, 2, 2}, out);
    std::vector<std::uint8_t> want;
    for (std::uint32_t y = 1; y < 3; ++y)
        for (std::uint32_t x = 1; x < 3; ++x)
            for (int k = 0; k < 4; ++k) want.push_back(img[(y * 4 + x) * 4 + k]);
    EXPECT_EQ(out, want);
}

// ── Size cap: a panel is drawn at no more than twice its authored canvas
// (never below 512 on the long edge, never above the quality's edge).
TEST(PanelEdgeCap, TwiceTheCanvas) {
    EXPECT_EQ(panel_edge_cap(2048, 512.f, 512.f), 1024u);
    EXPECT_EQ(panel_edge_cap(2048, 640.f, 320.f), 1280u);
    EXPECT_EQ(panel_edge_cap(2048, 320.f, 640.f), 1280u);
}

TEST(PanelEdgeCap, QualityEdgeWinsWhenSmaller) {
    EXPECT_EQ(panel_edge_cap(1024, 640.f, 320.f), 1024u);
    EXPECT_EQ(panel_edge_cap(512, 4096.f, 4096.f), 512u);
}

TEST(PanelEdgeCap, SmallCanvasesKeepAFloor) {
    EXPECT_EQ(panel_edge_cap(2048, 64.f, 32.f), 512u);
    EXPECT_EQ(panel_edge_cap(1024, 1.f, 1.f), 512u);
    // The floor never lifts a panel past its quality's edge.
    EXPECT_EQ(panel_edge_cap(256, 64.f, 32.f), 256u);
}

TEST(PanelEdgeCap, FractionalCanvasRoundsUp) {
    EXPECT_EQ(panel_edge_cap(2048, 600.4f, 10.f), 1201u);
}
