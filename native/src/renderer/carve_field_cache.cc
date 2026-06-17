// native/src/renderer/carve_field_cache.cc
#include <renderer/carve_field_cache.h>

#include <glad/glad.h>

namespace renderer {

CarveFieldCache::~CarveFieldCache() {
    for (auto& kv : by_source_) {
        if (kv.second.tex3d) {
            GLuint t = kv.second.tex3d;
            glDeleteTextures(1, &t);
            kv.second.tex3d = 0;
        }
    }
}

void CarveFieldCache::upload_texture(Entry& e, const voxel::VoxelVolume& vol) {
    if (vol.occ.empty() || vol.dims.x <= 0 || vol.dims.y <= 0 ||
        vol.dims.z <= 0) {
        return;
    }

    if (e.tex3d == 0) {
        GLuint t = 0;
        glGenTextures(1, &t);
        e.tex3d = t;
    }

    GLint prev_unpack = 0;
    glGetIntegerv(GL_UNPACK_ALIGNMENT, &prev_unpack);
    GLint prev_unit = 0;
    glGetIntegerv(GL_ACTIVE_TEXTURE, &prev_unit);
    glActiveTexture(GL_TEXTURE0);

    glBindTexture(GL_TEXTURE_3D, e.tex3d);
    // occ is one byte per cell (0..127), tightly packed x-fastest.
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    // GL_R8: byte b samples as b/255.0 in [0,1]. The shader's u_fill_iso is
    // kIsovalue/255.0 so the fill mask and the original isovalue match.
    // LINEAR gives a smoother mask edge between cells.
    glTexImage3D(GL_TEXTURE_3D, 0, GL_R8,
                 vol.dims.x, vol.dims.y, vol.dims.z, 0,
                 GL_RED, GL_UNSIGNED_BYTE, vol.occ.data());
    glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_WRAP_R, GL_CLAMP_TO_EDGE);
    glBindTexture(GL_TEXTURE_3D, 0);
    glActiveTexture(static_cast<GLenum>(prev_unit));

    glPixelStorei(GL_UNPACK_ALIGNMENT, prev_unpack);

    e.dims   = vol.dims;
    e.origin = vol.origin;
    e.cell   = vol.cell;
}

const CarveFieldCache::Entry* CarveFieldCache::get_for_source(
        const std::filesystem::path& source) {
    if (source.empty()) return nullptr;

    const std::string key = source.string();
    auto it = by_source_.find(key);
    if (it != by_source_.end()) {
        // Already cached (including an attempted-but-failed upload with tex3d==0).
        return (it->second.tex3d != 0) ? &it->second : nullptr;
    }

    // First time for this source: decode the original (uncarved) fill.
    Entry& e = by_source_[key];
    const voxel::VoxelVolume& fill = source_cache_.get_for_hull(source);
    if (fill.occ.empty()) return nullptr;

    e.fill = fill;
    upload_texture(e, fill);
    return (e.tex3d != 0) ? &e : nullptr;
}

}  // namespace renderer
