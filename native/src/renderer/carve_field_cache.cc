// native/src/renderer/carve_field_cache.cc
#include <renderer/carve_field_cache.h>

#include <renderer/breach_pass.h>  // BreachPass::build_carved_fill (static)

#include <scenegraph/hull_carve.h>

#include <glad/glad.h>

namespace renderer {

CarveFieldCache::~CarveFieldCache() {
    for (auto& kv : by_instance_) {
        if (kv.second.tex3d) {
            GLuint t = kv.second.tex3d;
            glDeleteTextures(1, &t);
            kv.second.tex3d = 0;
        }
    }
}

std::uint64_t CarveFieldCache::carve_version(
        const scenegraph::HullCarveField& carve) const {
    // Max active carve seq strictly increases on every add/grow (hull_carve.cc),
    // so it is a monotone version key; 0 means no active carves.
    std::uint64_t v = 0;
    for (const auto& s : carve.slots()) {
        if (s.active && s.seq > v) v = s.seq;
    }
    return v;
}

void CarveFieldCache::upload_texture(Entry& e) {
    const voxel::VoxelVolume& vol = e.carved;
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

    glBindTexture(GL_TEXTURE_3D, e.tex3d);
    // occ is one byte per cell (0..127), tightly packed x-fastest.
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    // GL_R8: byte b samples as b/255.0 in [0,1]. The shader's u_carve_iso is
    // kIsovalue/255.0 so the clip and the DC isovalue (kIsovalue) mean the same
    // surface. LINEAR gives a smoother clip edge between cells.
    glTexImage3D(GL_TEXTURE_3D, 0, GL_R8,
                 vol.dims.x, vol.dims.y, vol.dims.z, 0,
                 GL_RED, GL_UNSIGNED_BYTE, vol.occ.data());
    glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    // CLAMP_TO_EDGE: a texcoord outside [0,1] samples the outermost carved node
    // near the impact — that edge clamp is what lets the surface hole appear at
    // the hull boundary (intended; see opaque.frag clip).
    glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_WRAP_R, GL_CLAMP_TO_EDGE);
    glBindTexture(GL_TEXTURE_3D, 0);

    glPixelStorei(GL_UNPACK_ALIGNMENT, prev_unpack);

    e.dims   = vol.dims;
    e.origin = vol.origin;
    e.cell   = vol.cell;
}

const CarveFieldCache::Entry* CarveFieldCache::get(
        std::uintptr_t instance_key,
        const std::filesystem::path& source,
        const scenegraph::HullCarveField& carve) {
    const std::uint64_t version = carve_version(carve);
    if (version == 0) return nullptr;          // no active carves
    if (source.empty()) return nullptr;

    Entry& e = by_instance_[instance_key];
    if (e.carve_version == version && e.tex3d != 0 && e.palette != nullptr) {
        return &e;  // unchanged carves -> reuse the carved fill + texture
    }

    const voxel::VoxelVolume& fill = source_cache_.get_for_hull(source);
    if (fill.occ.empty()) return nullptr;

    // Build the carved fill ONCE (source fill + every active carve sphere).
    // This same VoxelVolume is consumed by the breach DC extraction.
    e.carved        = BreachPass::build_carved_fill(fill, carve);
    e.palette       = &source_cache_.planes_for_hull(source);
    e.carve_version = version;
    upload_texture(e);

    if (e.tex3d == 0) return nullptr;  // upload failed (degenerate volume)
    return &e;
}

}  // namespace renderer
