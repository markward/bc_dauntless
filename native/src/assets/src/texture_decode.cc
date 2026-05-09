#include <assets/texture.h>

#define STB_IMAGE_IMPLEMENTATION
#define STBI_ONLY_TGA
#define STBI_NO_STDIO
#include <stb_image.h>

#include <nif/block.h>

#include <string>

namespace assets {

namespace {

bool is_indexed_tga(std::span<const std::uint8_t> bytes) {
    if (bytes.size() < 18) return false;
    // byte 1: color map type; byte 2: image type
    // image type 1 = uncompressed color-mapped, 9 = RLE color-mapped
    return bytes[1] != 0 || bytes[2] == 1 || bytes[2] == 9;
}

bool is_16bpp_tga(std::span<const std::uint8_t> bytes) {
    if (bytes.size() < 18) return false;
    return bytes[16] == 16;  // bits-per-pixel field in TGA header
}

}  // namespace

Image decode_tga(std::span<const std::uint8_t> bytes) {
    if (is_indexed_tga(bytes)) {
        throw UnsupportedTga("indexed (color-mapped) TGA is not supported");
    }
    if (is_16bpp_tga(bytes)) {
        throw UnsupportedTga("16bpp TGA is not supported");
    }

    int w = 0, h = 0, channels = 0;
    stbi_uc* data = stbi_load_from_memory(
        bytes.data(), static_cast<int>(bytes.size()),
        &w, &h, &channels, /*desired_channels=*/0);
    if (!data) {
        const char* reason = stbi_failure_reason();
        throw TextureDecodeError(reason ? reason : "tga decode failed");
    }

    Image img;
    img.width  = static_cast<std::uint32_t>(w);
    img.height = static_cast<std::uint32_t>(h);
    switch (channels) {
        case 1: img.format = Image::Format::R8;    break;
        case 3: img.format = Image::Format::RGB8;  break;
        case 4: img.format = Image::Format::RGBA8; break;
        default:
            stbi_image_free(data);
            throw UnsupportedTga(
                "unexpected channel count from stb: " + std::to_string(channels));
    }

    const std::size_t total =
        static_cast<std::size_t>(w) * static_cast<std::size_t>(h) *
        static_cast<std::size_t>(channels);
    img.pixels.assign(data, data + total);
    stbi_image_free(data);
    return img;
}

Image decode_raw_image(const nif::NiRawImageData& raw) {
    Image img;
    img.width  = raw.width;
    img.height = raw.height;

    std::size_t channels = 0;
    switch (raw.image_type) {
        case 1: img.format = Image::Format::RGB8;  channels = 3; break;
        case 2: img.format = Image::Format::RGBA8; channels = 4; break;
        default:
            throw UnsupportedTga(
                "NiRawImageData::image_type expected 1 (RGB) or 2 (RGBA), got "
                + std::to_string(raw.image_type));
    }

    const std::size_t expected =
        static_cast<std::size_t>(raw.width) *
        static_cast<std::size_t>(raw.height) * channels;
    if (raw.pixels.size() != expected) {
        throw TextureDecodeError(
            "NiRawImageData payload size mismatch: expected "
            + std::to_string(expected) + ", got "
            + std::to_string(raw.pixels.size()));
    }
    img.pixels = raw.pixels;
    return img;
}

}  // namespace assets
