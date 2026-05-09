#include <gtest/gtest.h>
#include <assets/texture.h>
#include <nif/block.h>

TEST(RawImageDecode, Rgb24Decodes) {
    nif::NiRawImageData raw;
    raw.width = 2;
    raw.height = 1;
    raw.image_type = 1;  // RGB
    raw.pixels = {0xFF, 0x00, 0x00, 0x00, 0x00, 0xFF};

    auto img = assets::decode_raw_image(raw);
    EXPECT_EQ(img.width, 2u);
    EXPECT_EQ(img.height, 1u);
    EXPECT_EQ(img.format, assets::Image::Format::RGB8);
    EXPECT_EQ(img.pixels.size(), 6u);
    EXPECT_EQ(img.pixels[0], 0xFFu);
    EXPECT_EQ(img.pixels[5], 0xFFu);
}

TEST(RawImageDecode, Rgba32Decodes) {
    nif::NiRawImageData raw;
    raw.width = 1;
    raw.height = 1;
    raw.image_type = 2;  // RGBA
    raw.pixels = {0x10, 0x20, 0x30, 0x40};

    auto img = assets::decode_raw_image(raw);
    EXPECT_EQ(img.format, assets::Image::Format::RGBA8);
    ASSERT_EQ(img.pixels.size(), 4u);
    EXPECT_EQ(img.pixels[3], 0x40u);
}

TEST(RawImageDecode, MismatchedPixelLengthThrows) {
    nif::NiRawImageData raw;
    raw.width = 4;
    raw.height = 4;
    raw.image_type = 1;  // expects 4*4*3 = 48 bytes
    raw.pixels = {0, 0, 0};

    EXPECT_THROW(assets::decode_raw_image(raw), assets::TextureDecodeError);
}

TEST(RawImageDecode, UnknownImageTypeThrows) {
    nif::NiRawImageData raw;
    raw.width = 1;
    raw.height = 1;
    raw.image_type = 99;
    raw.pixels = {0};

    EXPECT_THROW(assets::decode_raw_image(raw), assets::UnsupportedTga);
}
