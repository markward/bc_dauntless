#include <assets/texture.h>

#define STB_IMAGE_IMPLEMENTATION
#define STBI_ONLY_TGA
#define STBI_ONLY_PNG
#define STBI_NO_STDIO
#include <stb_image.h>

#include <nif/block.h>

#include <algorithm>
#include <cmath>
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

bool is_png(std::span<const std::uint8_t> bytes) {
    static constexpr std::uint8_t kSig[8] = {0x89, 'P', 'N', 'G', '\r', '\n', 0x1A, '\n'};
    return bytes.size() >= 8 && std::equal(kSig, kSig + 8, bytes.begin());
}

// stb decode shared by both formats; the format-specific header checks run
// before this. `what` names the format in the error message.
Image decode_with_stb(std::span<const std::uint8_t> bytes, const char* what) {
    // Image has no grey+alpha format, so a 2-channel source (a PNG mask saved
    // greyscale-with-alpha) is expanded to RGBA by stb; every other channel
    // count decodes as stored.
    int info_w = 0, info_h = 0, stored = 0;
    const bool known = stbi_info_from_memory(
        bytes.data(), static_cast<int>(bytes.size()), &info_w, &info_h, &stored);
    const int desired = (known && stored == 2) ? 4 : 0;

    int w = 0, h = 0, channels = 0;
    stbi_uc* data = stbi_load_from_memory(
        bytes.data(), static_cast<int>(bytes.size()),
        &w, &h, &channels, desired);
    if (desired != 0) channels = desired;
    if (!data) {
        const char* reason = stbi_failure_reason();
        throw TextureDecodeError(reason ? reason : std::string(what) + " decode failed");
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

}  // namespace

Image decode_tga(std::span<const std::uint8_t> bytes) {
    if (is_indexed_tga(bytes)) {
        throw UnsupportedTga("indexed (color-mapped) TGA is not supported");
    }
    if (is_16bpp_tga(bytes)) {
        throw UnsupportedTga("16bpp TGA is not supported");
    }
    return decode_with_stb(bytes, "tga");
}

Image decode_image(std::span<const std::uint8_t> bytes) {
    // The TGA sniffs above would misread a PNG (its 2nd byte 'P' looks like a
    // colour-map flag), so the signature check must come first.
    if (is_png(bytes)) return decode_with_stb(bytes, "png");
    return decode_tga(bytes);
}

void reconstruct_normal_map_z(Image& image) {
    std::size_t channels = 0;
    switch (image.format) {
        case Image::Format::RGBA8: channels = 4; break;
        case Image::Format::RGB8:  channels = 3; break;
        case Image::Format::R8:    return;   // no x/y to derive z from
    }
    const std::size_t texels = image.pixels.size() / channels;
    for (std::size_t i = 0; i < texels; ++i) {
        std::uint8_t* px = image.pixels.data() + i * channels;
        const float x = px[0] / 127.5f - 1.0f;
        const float y = px[1] / 127.5f - 1.0f;
        const float z = std::sqrt(std::max(0.0f, 1.0f - x * x - y * y));
        px[2] = static_cast<std::uint8_t>(std::lround((z * 0.5f + 0.5f) * 255.0f));
    }
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
