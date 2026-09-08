// native/src/renderer/carve_field_cache.cc
#include <renderer/carve_field_cache.h>

#include <glad/glad.h>

#include <cmath>

namespace renderer {

bool carve_has_backing(const voxel::VoxelVolume& fill,
                       const glm::vec3& center_body,
                       const glm::vec3& normal_body) {
    if (fill.occ.empty()) return true;      // no volume to consult → don't gate
    if (fill.cell.x <= 0.0f) return true;
    const float reach = CarveFieldCache::kBackingCells * fill.cell.x;
    for (int t = 1; t <= CarveFieldCache::kBackingTaps; ++t) {
        const float d =
            reach * static_cast<float>(t) / CarveFieldCache::kBackingTaps;
        const glm::vec3 p = center_body - normal_body * d;
        const glm::vec3 g = (p - fill.origin) / fill.cell;
        const glm::ivec3 c(static_cast<int>(std::floor(g.x)),
                           static_cast<int>(std::floor(g.y)),
                           static_cast<int>(std::floor(g.z)));
        if (c.x < 0 || c.y < 0 || c.z < 0 ||
            c.x >= fill.dims.x || c.y >= fill.dims.y || c.z >= fill.dims.z)
            continue;                       // outside the grid: genuinely nothing
        if (fill.occ[fill.index(c.x, c.y, c.z)] >=
            CarveFieldCache::kBackingIsovalue)
            return true;
    }
    return false;
}

float carve_cavity_depth_cells(const voxel::VoxelVolume& fill,
                               const glm::vec3& center_body,
                               const glm::vec3& normal_body) {
    // No volume to consult means no opinion — a mod ship with no _vox.nif keeps
    // its scoop rather than losing it to a probe with nothing to say. Same
    // contract as carve_has_backing's empty-volume case.
    if (fill.occ.empty() || fill.cell.x <= 0.0f)
        return CarveFieldCache::kCavityMaxCells;

    const float reach = CarveFieldCache::kCavityMaxCells * fill.cell.x;
    int hits = 0;
    for (int t = 1; t <= CarveFieldCache::kCavityTaps; ++t) {
        const float d =
            reach * static_cast<float>(t) / CarveFieldCache::kCavityTaps;
        const glm::vec3 p = center_body - normal_body * d;
        const glm::vec3 g = (p - fill.origin) / fill.cell;
        const glm::ivec3 c(static_cast<int>(std::floor(g.x)),
                           static_cast<int>(std::floor(g.y)),
                           static_cast<int>(std::floor(g.z)));
        if (c.x < 0 || c.y < 0 || c.z < 0 ||
            c.x >= fill.dims.x || c.y >= fill.dims.y || c.z >= fill.dims.z)
            continue;                       // off the grid: no material here
        if (fill.occ[fill.index(c.x, c.y, c.z)] >=
            CarveFieldCache::kBackingIsovalue)
            ++hits;
    }
    return CarveFieldCache::kCavityMaxCells * static_cast<float>(hits)
           / CarveFieldCache::kCavityTaps;
}

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

    upload_texture(e, fill);
    return (e.tex3d != 0) ? &e : nullptr;
}

}  // namespace renderer
