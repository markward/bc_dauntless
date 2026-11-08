// native/tests/ui_cef/cef_dirty_rects_test.cc
//
// The CEF overlay's dirty-rect bookkeeping, without GL or CEF. OnPaint copies
// only CEF's dirty rects into the cached bitmap and accumulates them; the
// composite uploads only those regions. The picture must stay pixel-identical
// to a whole-surface copy + upload, which the last tests pin end to end on a
// CPU model of the texture.
#include "cef_dirty_rects.h"

#include <gtest/gtest.h>

#include <cstdint>
#include <vector>

using dauntless::ui_cef::DirtyRegion;
using dauntless::ui_cef::PixelRect;
using dauntless::ui_cef::UploadMode;
using dauntless::ui_cef::apply_paint;
using dauntless::ui_cef::copy_rects;
using dauntless::ui_cef::kFullUploadFraction;
using dauntless::ui_cef::kMaxDirtyRects;
using dauntless::ui_cef::paint_needs_full;
using dauntless::ui_cef::upload_needs_full;

namespace {

bool same(const PixelRect& a, const PixelRect& b) {
    return a.x == b.x && a.y == b.y && a.w == b.w && a.h == b.h;
}

// A BGRA buffer whose every byte depends on (seed, index), so two seeds
// differ at every byte and a misplaced copy cannot pass by accident.
std::vector<std::uint8_t> pattern(int w, int h, int seed) {
    std::vector<std::uint8_t> v(static_cast<size_t>(w) * h * 4);
    for (size_t i = 0; i < v.size(); ++i) {
        v[i] = static_cast<std::uint8_t>((i * 7 + seed * 31 + 1) & 0xFF);
    }
    return v;
}

// `base` with the pixels inside `r` taken from `src` (same size).
std::vector<std::uint8_t> overlay(std::vector<std::uint8_t> base,
                                  const std::vector<std::uint8_t>& src, int w,
                                  PixelRect r) {
    for (int y = r.y; y < r.y + r.h; ++y) {
        for (int x = r.x; x < r.x + r.w; ++x) {
            for (int c = 0; c < 4; ++c) {
                const size_t i = (static_cast<size_t>(y) * w + x) * 4 + c;
                base[i] = src[i];
            }
        }
    }
    return base;
}

}  // namespace

TEST(DirtyRegion, ClipsToSurface) {
    DirtyRegion d;
    d.add({-5, -3, 10, 8}, 100, 100);
    ASSERT_EQ(d.rects().size(), 1u);
    EXPECT_TRUE(same(d.rects()[0], {0, 0, 5, 5}));

    d.clear();
    d.add({95, 90, 20, 20}, 100, 100);
    ASSERT_EQ(d.rects().size(), 1u);
    EXPECT_TRUE(same(d.rects()[0], {95, 90, 5, 10}));

    d.clear();
    d.add({200, 200, 5, 5}, 100, 100);   // wholly outside
    d.add({10, 10, 0, 5}, 100, 100);     // zero width
    EXPECT_TRUE(d.empty());
    EXPECT_FALSE(d.full());
}

TEST(DirtyRegion, MergesOverlapping) {
    DirtyRegion d;
    d.add({10, 10, 10, 10}, 100, 100);
    d.add({15, 15, 10, 10}, 100, 100);
    ASSERT_EQ(d.rects().size(), 1u);
    EXPECT_TRUE(same(d.rects()[0], {10, 10, 15, 15}));
}

TEST(DirtyRegion, MergesTouching) {
    DirtyRegion d;
    d.add({10, 10, 10, 10}, 100, 100);
    d.add({20, 10, 5, 10}, 100, 100);    // shares the x=20 edge
    ASSERT_EQ(d.rects().size(), 1u);
    EXPECT_TRUE(same(d.rects()[0], {10, 10, 15, 10}));
}

TEST(DirtyRegion, MergeIsRepeatedUntilStable) {
    DirtyRegion d;
    d.add({0, 0, 4, 4}, 100, 100);
    d.add({20, 0, 4, 4}, 100, 100);
    ASSERT_EQ(d.rects().size(), 2u);
    // Bridges both: the bounding box of all three is one rect.
    d.add({3, 0, 18, 2}, 100, 100);
    ASSERT_EQ(d.rects().size(), 1u);
    EXPECT_TRUE(same(d.rects()[0], {0, 0, 24, 4}));
}

TEST(DirtyRegion, KeepsDisjointSeparate) {
    DirtyRegion d;
    d.add({0, 0, 5, 5}, 100, 100);
    d.add({50, 50, 5, 5}, 100, 100);
    ASSERT_EQ(d.rects().size(), 2u);
    EXPECT_TRUE(same(d.rects()[0], {0, 0, 5, 5}));
    EXPECT_TRUE(same(d.rects()[1], {50, 50, 5, 5}));
    EXPECT_FALSE(d.full());
    EXPECT_FALSE(d.empty());
}

TEST(DirtyRegion, CollapsesPastMaxRects) {
    DirtyRegion d;
    for (int i = 0; i < kMaxDirtyRects; ++i) {
        d.add({i * 100, 0, 2, 2}, 2000, 2000);
    }
    ASSERT_EQ(d.rects().size(), static_cast<size_t>(kMaxDirtyRects));
    d.add({kMaxDirtyRects * 100, 50, 2, 2}, 2000, 2000);
    ASSERT_EQ(d.rects().size(), 1u);
    EXPECT_TRUE(same(d.rects()[0], {0, 0, kMaxDirtyRects * 100 + 2, 52}));
    EXPECT_FALSE(d.full());
}

TEST(DirtyRegion, LargeAreaBecomesFull) {
    EXPECT_FLOAT_EQ(kFullUploadFraction, 0.5f);
    DirtyRegion d;
    d.add({0, 0, 100, 50}, 100, 100);    // exactly 50%: not more than half
    EXPECT_FALSE(d.full());
    d.add({0, 50, 100, 1}, 100, 100);    // 51%
    EXPECT_TRUE(d.full());
    EXPECT_FALSE(d.empty());
    // Once full, further rects change nothing.
    d.add({0, 90, 5, 5}, 100, 100);
    EXPECT_TRUE(d.full());

    DirtyRegion disjoint;                // the SUM decides, not one rect
    disjoint.add({0, 0, 100, 26}, 100, 100);
    disjoint.add({0, 75, 100, 25}, 100, 100);
    EXPECT_TRUE(disjoint.full());
}

TEST(DirtyRegion, ClearResets) {
    DirtyRegion d;
    d.add({0, 0, 5, 5}, 100, 100);
    d.mark_full();
    EXPECT_TRUE(d.full());
    d.clear();
    EXPECT_FALSE(d.full());
    EXPECT_TRUE(d.empty());
    EXPECT_TRUE(d.rects().empty());
}

TEST(DirtyRegion, SizeChangeForcesFull) {
    EXPECT_FALSE(paint_needs_full(640, 480, 640, 480));
    EXPECT_TRUE(paint_needs_full(640, 480, 641, 480));
    EXPECT_TRUE(paint_needs_full(640, 480, 640, 479));
    EXPECT_TRUE(paint_needs_full(640, 480, 480, 640));   // same w*h, swapped
    EXPECT_TRUE(paint_needs_full(0, 0, 640, 480));       // first paint
}

TEST(CopyRects, CopiesOnlyTheRects) {
    const int w = 16, h = 8;
    const std::vector<std::uint8_t> src = pattern(w, h, 1);
    std::vector<std::uint8_t> dst(src.size(), 0xAB);   // sentinel
    const std::vector<PixelRect> rects = {{1, 1, 3, 2}, {10, 4, 6, 4}};
    copy_rects(dst.data(), src.data(), w, h, rects);

    std::vector<std::uint8_t> want(src.size(), 0xAB);
    for (const PixelRect& r : rects) want = overlay(want, src, w, r);
    EXPECT_EQ(dst, want);
}

TEST(CopyRects, SizeChangeCopiesWhole) {
    // A 4x2 bitmap repainted as 2x4 (same byte count) with only one tiny
    // dirty rect: the w/h swap must still copy every byte.
    std::vector<std::uint8_t> bitmap;
    int bw = 0, bh = 0;
    DirtyRegion d;
    const auto first = pattern(4, 2, 1);
    apply_paint(bitmap, bw, bh, d, first.data(), 4, 2, {{0, 0, 1, 1}});
    EXPECT_EQ(bitmap, first);           // first paint is whole too
    EXPECT_TRUE(d.full());
    d.clear();

    const auto swapped = pattern(2, 4, 2);
    apply_paint(bitmap, bw, bh, d, swapped.data(), 2, 4, {{0, 0, 1, 1}});
    EXPECT_EQ(bw, 2);
    EXPECT_EQ(bh, 4);
    EXPECT_EQ(bitmap, swapped);
    EXPECT_TRUE(d.full());
}

TEST(CopyRects, PaintWithNoRectsCopiesWhole) {
    std::vector<std::uint8_t> bitmap;
    int bw = 0, bh = 0;
    DirtyRegion d;
    const auto a = pattern(8, 8, 1);
    apply_paint(bitmap, bw, bh, d, a.data(), 8, 8, {{0, 0, 8, 8}});
    d.clear();
    const auto b = pattern(8, 8, 2);
    apply_paint(bitmap, bw, bh, d, b.data(), 8, 8, {});
    EXPECT_EQ(bitmap, b);
    EXPECT_TRUE(d.full());
}

TEST(CopyRects, PaintCopiesOnlyDirtyAndAccumulates) {
    std::vector<std::uint8_t> bitmap;
    int bw = 0, bh = 0;
    DirtyRegion d;
    const auto a = pattern(32, 32, 1);
    apply_paint(bitmap, bw, bh, d, a.data(), 32, 32, {{0, 0, 32, 32}});
    d.clear();

    // CEF's buffer is the WHOLE latest frame; a byte outside the dirty rect
    // is not copied (proved by the buffer differing there).
    const auto b = pattern(32, 32, 2);
    apply_paint(bitmap, bw, bh, d, b.data(), 32, 32, {{2, 3, 4, 5}});
    EXPECT_EQ(bitmap, overlay(a, b, 32, {2, 3, 4, 5}));
    ASSERT_EQ(d.rects().size(), 1u);
    EXPECT_TRUE(same(d.rects()[0], {2, 3, 4, 5}));
    EXPECT_FALSE(d.full());

    // Out-of-surface parts of a CEF rect are clipped, not copied.
    apply_paint(bitmap, bw, bh, d, b.data(), 32, 32, {{30, 30, 10, 10}});
    EXPECT_EQ(bitmap,
              overlay(overlay(a, b, 32, {2, 3, 4, 5}), b, 32, {30, 30, 2, 2}));
    EXPECT_EQ(d.rects().size(), 2u);
}

TEST(CefDirtyUpload, FullUploadWhenModeRegionOrTextureDemandsIt) {
    DirtyRegion part;
    part.add({0, 0, 2, 2}, 100, 100);
    DirtyRegion whole;
    whole.mark_full();

    EXPECT_FALSE(upload_needs_full(UploadMode::OnPaint, true, false, part));
    EXPECT_TRUE(upload_needs_full(UploadMode::Always, true, false, part));
    EXPECT_TRUE(upload_needs_full(UploadMode::OnPaint, true, false, whole));
    EXPECT_TRUE(upload_needs_full(UploadMode::OnPaint, false, false, part));
    EXPECT_TRUE(upload_needs_full(UploadMode::OnPaint, true, true, part));
    EXPECT_TRUE(upload_needs_full(UploadMode::Never, true, true, part));
}

// End to end on a CPU model of the GL texture: a sequence of paints and
// composites in each mode must leave the texture byte-identical to CEF's
// latest buffer after every upload, exactly as a whole-surface upload would.
TEST(CefDirtyUpload, TextureMatchesLatestBufferAcrossPaints) {
    using dauntless::ui_cef::should_upload;
    struct Paint { int w, h, seed; std::vector<PixelRect> rects; };
    const std::vector<std::vector<Paint>> frames = {
        {Paint{24, 16, 1, {{0, 0, 24, 16}}}},
        {Paint{24, 16, 2, {{1, 1, 3, 3}}}, Paint{24, 16, 3, {{10, 2, 4, 6}}}},
        {},                                              // no paint
        {Paint{24, 16, 4, {{20, 12, 10, 10}}}},          // overhangs the edge
        {Paint{16, 24, 5, {{0, 0, 2, 2}}}},              // w/h swap
        {Paint{16, 24, 6, {{3, 3, 1, 1}}}, Paint{16, 24, 7, {{5, 9, 2, 2}}},
         Paint{16, 24, 8, {{0, 0, 16, 13}}}},            // crosses half
        {Paint{16, 24, 9, {}}},                          // no rects reported
        {Paint{16, 24, 10, {{1, 20, 3, 2}}}},
    };
    for (UploadMode mode : {UploadMode::Always, UploadMode::OnPaint}) {
        std::vector<std::uint8_t> bitmap, texture, latest;
        int bw = 0, bh = 0, tw = 0, th = 0;
        std::uint64_t gen = 0, uploaded = 0;
        DirtyRegion d;
        for (const auto& frame : frames) {
            for (const Paint& p : frame) {
                // CEF's buffer: the previous frame with ONLY the dirty
                // rects repainted (whole on a size change).
                std::vector<std::uint8_t> next = pattern(p.w, p.h, p.seed);
                if (!latest.empty() && !paint_needs_full(bw, bh, p.w, p.h) &&
                    !p.rects.empty()) {
                    std::vector<std::uint8_t> merged = latest;
                    for (PixelRect r : p.rects) {
                        r = dauntless::ui_cef::clip_rect(r, p.w, p.h);
                        merged = overlay(merged, next, p.w, r);
                    }
                    next = merged;
                }
                latest = next;
                apply_paint(bitmap, bw, bh, d, latest.data(), p.w, p.h,
                            p.rects);
                ++gen;
            }
            if (bitmap.empty()) continue;
            const bool allocated = tw > 0 && th > 0;
            const bool differs = bw != tw || bh != th;
            if (should_upload(mode, allocated, differs, gen, uploaded)) {
                if (upload_needs_full(mode, allocated, differs, d)) {
                    texture = bitmap;
                    tw = bw;
                    th = bh;
                } else {
                    copy_rects(texture.data(), bitmap.data(), bw, bh,
                               d.rects());
                }
                uploaded = gen;
                d.clear();
            }
            EXPECT_EQ(bitmap, latest) << "mode " << static_cast<int>(mode);
            EXPECT_EQ(texture, latest) << "mode " << static_cast<int>(mode);
        }
    }
}
