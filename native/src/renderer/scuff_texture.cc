// native/src/renderer/scuff_texture.cc
#include "renderer/scuff_texture.h"

#include <cstdint>
#include <cstdio>
#include <fstream>
#include <iterator>
#include <string>
#include <vector>

#include <assets/texture.h>
#include <renderer/asset_path.h>

namespace renderer {
namespace {

unsigned int    g_id       = 0;
unsigned int    g_override = 0;
bool            g_tried    = false;
assets::Texture g_owner;            // owns g_id

bool read_file(const std::string& path, std::vector<std::uint8_t>& out) {
    std::ifstream in(path, std::ios::binary);
    if (!in) return false;
    out.assign(std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>());
    return true;
}

}  // namespace

unsigned int ensure_scuff_normal_texture() {
    if (g_override != 0) return g_override;
    if (g_tried) return g_id;
    g_tried = true;

    // TGA, not PNG: the asset decoder is built STBI_ONLY_TGA (BC content is
    // all TGA) and its header sniff refuses a PNG as "indexed".
    const std::string resolved = project_asset_path("textures/scuff_normal.tga");
    std::vector<std::uint8_t> bytes;
    if (!read_file(resolved, bytes)) {
        std::fprintf(stderr, "[scuff] no normal map at %s -- collision scuffs draw "
                     "albedo only\n", resolved.c_str());
        return 0;
    }
    try {
        assets::Image img = assets::decode_tga(bytes);
        assets::reconstruct_normal_map_z(img);
        // GL_REPEAT (upload_image's default) is what the per-scuff UV offset
        // relies on; mipmaps are the band limit at range.
        assets::Texture tex = assets::upload_image(img, /*generate_mipmaps=*/true);
        g_id    = tex.id();
        g_owner = std::move(tex);
    } catch (const std::exception& e) {
        std::fprintf(stderr, "[scuff] failed to load '%s': %s\n", resolved.c_str(), e.what());
    }
    return g_id;
}

void reset_scuff_normal_texture() {
    g_owner = assets::Texture{};
    g_id    = 0;
    g_tried = false;
}

void set_scuff_normal_texture_override(unsigned int id) { g_override = id; }

}  // namespace renderer
