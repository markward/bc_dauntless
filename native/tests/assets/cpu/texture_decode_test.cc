#include <gtest/gtest.h>
#include <assets/texture.h>

#include <cstdint>
#include <vector>

namespace {

// 2x1 24-bit uncompressed TGA. TGA stores BGR order in pixels.
// Pixel 0: red (BGR 00, 00, FF). Pixel 1: blue (BGR FF, 00, 00).
// stb returns RGB on output, so we expect:
//   pixel 0 = R: FF, G: 00, B: 00
//   pixel 1 = R: 00, G: 00, B: FF
std::vector<std::uint8_t> make_tga_24bit_2x1() {
    return {
        0,                 // id length
        0,                 // color map type (none)
        2,                 // image type: uncompressed true-color
        0, 0, 0, 0, 0,     // color map spec
        0, 0, 0, 0,        // x/y origin
        2, 0,              // width = 2 (LE)
        1, 0,              // height = 1
        24,                // bits per pixel
        0,                 // image descriptor
        0x00, 0x00, 0xFF,  // pixel 0 BGR
        0xFF, 0x00, 0x00,  // pixel 1 BGR
    };
}

std::vector<std::uint8_t> make_tga_indexed_unsupported() {
    return {
        0,
        1,                 // color map type: present
        1,                 // image type: uncompressed color-mapped
        0, 0, 0, 0, 16,    // color map spec
        0, 0, 0, 0,
        2, 0, 1, 0,
        8,
        0,
    };
}

std::vector<std::uint8_t> make_tga_16bpp_unsupported() {
    return {
        0, 0, 2,
        0, 0, 0, 0, 0,
        0, 0, 0, 0,
        1, 0, 1, 0,
        16,                // bits per pixel
        0,
        0x00, 0x00,
    };
}

// 2x1 RGBA PNG (written by Pillow). Pixel 0: opaque red (FF 00 00 FF).
// Pixel 1: half-transparent blue (00 00 FF 80). Hull-name decal masks are
// authored as PNG, so the alpha channel must survive the decode.
std::vector<std::uint8_t> make_png_rgba_2x1() {
    return {
        0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00, 0x00, 0x0d,
        0x49, 0x48, 0x44, 0x52, 0x00, 0x00, 0x00, 0x02, 0x00, 0x00, 0x00, 0x01,
        0x08, 0x06, 0x00, 0x00, 0x00, 0xf4, 0x22, 0x7f, 0x8a, 0x00, 0x00, 0x00,
        0x0e, 0x49, 0x44, 0x41, 0x54, 0x78, 0x9c, 0x63, 0xf8, 0xcf, 0xc0, 0x00,
        0x42, 0x0d, 0x00, 0x0f, 0x7a, 0x03, 0x7e, 0x77, 0xe9, 0x7f, 0x97, 0x00,
        0x00, 0x00, 0x00, 0x49, 0x45, 0x4e, 0x44, 0xae, 0x42, 0x60, 0x82,
    };
}

// 2x1 grey+alpha PNG. Pixel 0: grey 200, alpha 255. Pixel 1: grey 50,
// alpha 64. A mask saved as greyscale-with-alpha must still decode.
std::vector<std::uint8_t> make_png_grey_alpha_2x1() {
    return {
        0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00, 0x00, 0x0d,
        0x49, 0x48, 0x44, 0x52, 0x00, 0x00, 0x00, 0x02, 0x00, 0x00, 0x00, 0x01,
        0x08, 0x04, 0x00, 0x00, 0x00, 0x5e, 0x2b, 0xb7, 0x01, 0x00, 0x00, 0x00,
        0x0d, 0x49, 0x44, 0x41, 0x54, 0x78, 0x9c, 0x63, 0x38, 0xf1, 0xdf, 0xc8,
        0x01, 0x00, 0x06, 0xc6, 0x02, 0x3a, 0x57, 0xaa, 0xa3, 0x45, 0x00, 0x00,
        0x00, 0x00, 0x49, 0x45, 0x4e, 0x44, 0xae, 0x42, 0x60, 0x82,
    };
}

}  // namespace

TEST(TextureDecode, DecodeImageExpandsGreyAlphaPngToRgba) {
    auto img = assets::decode_image(make_png_grey_alpha_2x1());
    EXPECT_EQ(img.format, assets::Image::Format::RGBA8);
    const std::vector<std::uint8_t> expected = {200, 200, 200, 255,
                                                50, 50, 50, 64};
    EXPECT_EQ(img.pixels, expected);
}

TEST(TextureDecode, DecodeImageReadsPngWithAlpha) {
    auto img = assets::decode_image(make_png_rgba_2x1());
    EXPECT_EQ(img.width, 2u);
    EXPECT_EQ(img.height, 1u);
    EXPECT_EQ(img.format, assets::Image::Format::RGBA8);
    ASSERT_EQ(img.pixels.size(), 8u);
    const std::vector<std::uint8_t> expected = {0xFF, 0x00, 0x00, 0xFF,
                                                0x00, 0x00, 0xFF, 0x80};
    EXPECT_EQ(img.pixels, expected);
}

TEST(TextureDecode, DecodeImageStillReadsTga) {
    auto img = assets::decode_image(make_tga_24bit_2x1());
    EXPECT_EQ(img.format, assets::Image::Format::RGB8);
    ASSERT_EQ(img.pixels.size(), 6u);
    EXPECT_EQ(img.pixels[0], 0xFFu);
    EXPECT_EQ(img.pixels[5], 0xFFu);
}

TEST(TextureDecode, DecodeImageKeepsTgaRejections) {
    EXPECT_THROW(assets::decode_image(make_tga_indexed_unsupported()),
                 assets::UnsupportedTga);
    EXPECT_THROW(assets::decode_image(make_tga_16bpp_unsupported()),
                 assets::UnsupportedTga);
}

TEST(TextureDecode, TruncatedPngThrowsDecodeError) {
    auto bytes = make_png_rgba_2x1();
    bytes.resize(20);   // signature intact, IHDR cut short
    EXPECT_THROW(assets::decode_image(bytes), assets::TextureDecodeError);
}

TEST(TextureDecode, Tga24BitDecodesToRgb) {
    auto bytes = make_tga_24bit_2x1();
    auto img = assets::decode_tga(bytes);
    EXPECT_EQ(img.width, 2u);
    EXPECT_EQ(img.height, 1u);
    EXPECT_EQ(img.format, assets::Image::Format::RGB8);
    ASSERT_EQ(img.pixels.size(), 6u);
    // Pixel 0: red (FF 00 00 in RGB)
    EXPECT_EQ(img.pixels[0], 0xFFu);
    EXPECT_EQ(img.pixels[1], 0x00u);
    EXPECT_EQ(img.pixels[2], 0x00u);
    // Pixel 1: blue (00 00 FF in RGB)
    EXPECT_EQ(img.pixels[3], 0x00u);
    EXPECT_EQ(img.pixels[4], 0x00u);
    EXPECT_EQ(img.pixels[5], 0xFFu);
}

TEST(TextureDecode, IndexedTgaThrowsUnsupported) {
    EXPECT_THROW(
        assets::decode_tga(make_tga_indexed_unsupported()),
        assets::UnsupportedTga);
}

TEST(TextureDecode, SixteenBppTgaThrowsUnsupported) {
    EXPECT_THROW(
        assets::decode_tga(make_tga_16bpp_unsupported()),
        assets::UnsupportedTga);
}

TEST(TextureDecode, GarbageThrowsDecodeError) {
    std::vector<std::uint8_t> garbage = {0xDE, 0xAD, 0xBE, 0xEF};
    EXPECT_THROW(assets::decode_tga(garbage), assets::TextureDecodeError);
}

// ── Tangent-space normal map: blue is re-derived from red/green at ingest ──
// CGSovereign's top_normal.tga exports z in UNSIGNED 0..1 range (z = B/255):
// 100% of its 153,647 tilted texels are unit length under that decode and 30%
// under the standard B/127.5-1. Read the standard way, a 71-degree edge
// (248,128,81) becomes 111 degrees -- z NEGATIVE -- which the shader's
// max(z,0) pins at exactly 90, and a 90-degree normal is immune to the
// strength multiplier. z = sqrt(1 - x^2 - y^2) is the authored z for a correct
// map and the only correct z for that one, so it is recomputed for every
// texel: no per-map heuristic, no encoding to detect.
namespace {
assets::Image rgba_texel(std::uint8_t r, std::uint8_t g, std::uint8_t b) {
    assets::Image img;
    img.width = 1; img.height = 1;
    img.format = assets::Image::Format::RGBA8;
    img.pixels = {r, g, b, 255};
    return img;
}
}  // namespace

TEST(NormalMapZ, UnsignedRangeBlueIsRecomputedFromRedGreen) {
    // x = 248/127.5-1 = 0.945, y = 0  ->  z = sqrt(1-0.893) = 0.327
    // encoded (0.327*0.5+0.5)*255 = 169.2
    auto img = rgba_texel(248, 128, 81);
    assets::reconstruct_normal_map_z(img);
    EXPECT_EQ(img.pixels[0], 248u);
    EXPECT_EQ(img.pixels[1], 128u);
    EXPECT_NEAR(img.pixels[2], 169, 1);
    EXPECT_EQ(img.pixels[3], 255u);
}

TEST(NormalMapZ, CorrectlyEncodedTexelIsUnchangedWithinQuantisation) {
    // (0.514, 0.514, 0.686) encoded: R=G=193, B=215. Already unit length.
    auto img = rgba_texel(193, 193, 215);
    assets::reconstruct_normal_map_z(img);
    EXPECT_EQ(img.pixels[0], 193u);
    EXPECT_EQ(img.pixels[1], 193u);
    EXPECT_NEAR(img.pixels[2], 215, 1);
}

TEST(NormalMapZ, FlatTexelStaysFlat) {
    auto img = rgba_texel(128, 128, 255);
    assets::reconstruct_normal_map_z(img);
    EXPECT_EQ(img.pixels[2], 255u);
}

TEST(NormalMapZ, OverlongXyClampsToHorizontalNotNaN) {
    // x = y = 0.945: x^2+y^2 = 1.79 > 1. sqrt of a negative must not happen;
    // z clamps to 0, encoded 128.
    auto img = rgba_texel(248, 248, 0);
    assets::reconstruct_normal_map_z(img);
    EXPECT_EQ(img.pixels[2], 128u);
}

TEST(NormalMapZ, Rgb8IsHandledAndR8IsLeftAlone) {
    assets::Image rgb;
    rgb.width = 2; rgb.height = 1;
    rgb.format = assets::Image::Format::RGB8;
    rgb.pixels = {248, 128, 81,   128, 128, 255};
    assets::reconstruct_normal_map_z(rgb);
    EXPECT_NEAR(rgb.pixels[2], 169, 1);
    EXPECT_EQ(rgb.pixels[5], 255u);

    assets::Image r8;
    r8.width = 1; r8.height = 1;
    r8.format = assets::Image::Format::R8;
    r8.pixels = {81};
    assets::reconstruct_normal_map_z(r8);   // no xy to derive from: no-op
    EXPECT_EQ(r8.pixels[0], 81u);
}
