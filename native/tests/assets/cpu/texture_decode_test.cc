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

}  // namespace

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
