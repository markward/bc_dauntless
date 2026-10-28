#include <gtest/gtest.h>

#include <cmath>
#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

#include "lottie/lottie_clip.h"

namespace {

std::filesystem::path fixture(const char* name) {
    return std::filesystem::path(LOTTIE_FIXTURES) / name;
}

struct Px { std::uint8_t r, g, b, a; };

Px at(const std::vector<std::uint8_t>& buf, std::uint32_t w, std::uint32_t x,
      std::uint32_t y) {
    const std::uint8_t* p = &buf[(static_cast<size_t>(y) * w + x) * 4];
    return {p[0], p[1], p[2], p[3]};
}

void expect_all_red(const std::vector<std::uint8_t>& buf) {
    for (size_t i = 0; i < buf.size(); i += 4) {
        ASSERT_EQ(buf[i + 0], 255) << i;
        ASSERT_EQ(buf[i + 1], 0) << i;
        ASSERT_EQ(buf[i + 2], 0) << i;
        ASSERT_EQ(buf[i + 3], 255) << i;
    }
}

}  // namespace

TEST(LottieClip, LoadsSolidRed) {
    std::string err;
    auto clip = lottie::LottieClip::load(fixture("solid_red.json"), &err);
    ASSERT_TRUE(clip) << err;
    EXPECT_FLOAT_EQ(clip->canvas_width(), 64.f);
    EXPECT_FLOAT_EQ(clip->canvas_height(), 32.f);
    EXPECT_FLOAT_EQ(clip->total_frames(), 30.f);
    EXPECT_NEAR(clip->fps(), 30.f, 1e-3);
}

TEST(LottieClip, RenderSolidRedIsOpaqueRed) {
    auto clip = lottie::LottieClip::load(fixture("solid_red.json"), nullptr);
    ASSERT_TRUE(clip);
    std::vector<std::uint8_t> out;
    ASSERT_TRUE(clip->render(0.f, 64, 32, out));
    ASSERT_EQ(out.size(), 64u * 32u * 4u);
    expect_all_red(out);
}

TEST(LottieClip, SlideMovesTheSquare) {
    auto clip = lottie::LottieClip::load(fixture("slide.json"), nullptr);
    ASSERT_TRUE(clip);
    std::vector<std::uint8_t> out;
    ASSERT_TRUE(clip->render(0.f, 64, 32, out));
    Px a = at(out, 64, 5, 16);
    EXPECT_EQ(a.r, 255); EXPECT_EQ(a.g, 255); EXPECT_EQ(a.b, 255);
    EXPECT_EQ(a.a, 255);
    EXPECT_EQ(at(out, 64, 59, 16).a, 0);
    ASSERT_TRUE(clip->render(59.f, 64, 32, out));
    EXPECT_EQ(at(out, 64, 5, 16).a, 0);
    Px b = at(out, 64, 59, 16);
    EXPECT_EQ(b.r, 255); EXPECT_EQ(b.a, 255);
}

TEST(LottieClip, RenderIsDeterministic) {
    auto clip = lottie::LottieClip::load(fixture("slide.json"), nullptr);
    ASSERT_TRUE(clip);
    std::vector<std::uint8_t> a, b;
    ASSERT_TRUE(clip->render(30.f, 64, 32, a));
    ASSERT_TRUE(clip->render(30.f, 64, 32, b));
    EXPECT_EQ(a, b);
}

TEST(LottieClip, RenderScalesToTargetSize) {
    auto clip = lottie::LottieClip::load(fixture("solid_red.json"), nullptr);
    ASSERT_TRUE(clip);
    std::vector<std::uint8_t> out;
    ASSERT_TRUE(clip->render(0.f, 256, 128, out));
    ASSERT_EQ(out.size(), 256u * 128u * 4u);
    expect_all_red(out);
}

TEST(LottieClip, TimelineOffsetCountsFramesFromInPoint) {
    auto clip = lottie::LottieClip::load(fixture("offset_ip.json"), nullptr);
    ASSERT_TRUE(clip);
    EXPECT_FLOAT_EQ(clip->total_frames(), 30.f);
    std::vector<std::uint8_t> out;
    ASSERT_TRUE(clip->render(0.f, 64, 32, out));
    expect_all_red(out);
}

TEST(LottieClip, RejectsNonLottie) {
    std::string err;
    EXPECT_FALSE(lottie::LottieClip::load(fixture("not_lottie.json"), &err));
    EXPECT_EQ(err, "not a Lottie animation");
}

TEST(LottieClip, RejectsBrokenJson) {
    std::string err;
    EXPECT_FALSE(lottie::LottieClip::load(fixture("broken.json"), &err));
    EXPECT_EQ(err, "not a Lottie animation");
}

TEST(LottieClip, RejectsMissingFile) {
    std::string err;
    EXPECT_FALSE(lottie::LottieClip::load(fixture("nope.json"), &err));
    EXPECT_EQ(err, "unreadable file");
}
