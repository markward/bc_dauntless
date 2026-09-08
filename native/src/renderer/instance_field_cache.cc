// native/src/renderer/instance_field_cache.cc
#include <renderer/instance_field_cache.h>

#include <renderer/carve_field_cache.h>
#include <voxel/field_brush.h>

#include <glad/glad.h>

namespace renderer {

InstanceFieldCache::InstanceFieldCache(voxel::HullVolumeCache* bake_cache)
    : bake_cache_(bake_cache) {}

InstanceFieldCache::~InstanceFieldCache() {
    for (auto& kv : instances_) {
        if (kv.second.pub.tex2d != 0) {
            GLuint t = kv.second.pub.tex2d;
            glDeleteTextures(1, &t);
        }
    }
}

void InstanceFieldCache::carve(scenegraph::InstanceId id,
                               const std::filesystem::path& source,
                               float authored_res,
                               const glm::vec3& center_body,
                               const glm::vec3& normal_body,
                               float radius) {
    auto it = instances_.find(id);
    if (it == instances_.end()) {
        // Resolve the shared per-hull baked field this instance's private
        // copy starts from. `authored_res` is BC's raw SetDamageResolution
        // ratio, passed straight through -- HullVolumeCache::get is the one
        // that divides it by quality, not us (see instance_field_cache.h /
        // carve_field_cache.h's warnings about this).
        voxel::HullVolumeCache& cache =
            bake_cache_ != nullptr ? *bake_cache_ : renderer::hull_volume_cache();
        const voxel::DistanceField& baked =
            cache.get(source, authored_res, voxel::kDefaultQuality);
        if (baked.empty()) return;   // hull has no baked field: stay absent

        Instance inst;
        inst.field = baked;   // COPY -- this instance's own mutable field,
                              // independent of the shared baked original and
                              // of every other instance's copy of it.
        it = instances_.emplace(id, std::move(inst)).first;
    }

    voxel::field_carve_oblate(it->second.field, center_body, normal_body,
                              radius);
    it->second.dirty = true;
}

const InstanceFieldCache::Entry* InstanceFieldCache::get(
        scenegraph::InstanceId id) {
    auto it = instances_.find(id);
    if (it == instances_.end()) return nullptr;

    Instance& inst = it->second;
    if (inst.dirty) {
        if (upload(inst)) {
            inst.dirty = false;
            ++uploads_;
        }
    }
    // tex2d == 0 only when upload() has never once succeeded for this
    // instance (defensive: not reachable for a field that passed carve()'s
    // !empty() check, but don't hand the caller a texture id of 0 either
    // way).
    return (inst.pub.tex2d != 0) ? &inst.pub : nullptr;
}

void InstanceFieldCache::forget(scenegraph::InstanceId id) {
    auto it = instances_.find(id);
    if (it == instances_.end()) return;
    if (it->second.pub.tex2d != 0) {
        GLuint t = it->second.pub.tex2d;
        glDeleteTextures(1, &t);
    }
    instances_.erase(it);
}

bool InstanceFieldCache::upload(Instance& inst) {
    const voxel::AtlasLayout layout = voxel::atlas_layout_for(inst.field.dims);
    if (!layout.valid()) return false;

    const std::vector<std::uint8_t> pixels =
        voxel::pack_field_to_atlas(inst.field, layout);
    if (pixels.empty()) return false;

    if (inst.pub.tex2d == 0) {
        GLuint t = 0;
        glGenTextures(1, &t);
        inst.pub.tex2d = t;
    }

    GLint prev_unpack = 0;
    glGetIntegerv(GL_UNPACK_ALIGNMENT, &prev_unpack);
    GLint prev_unit = 0;
    glGetIntegerv(GL_ACTIVE_TEXTURE, &prev_unit);
    glActiveTexture(GL_TEXTURE0);

    glBindTexture(GL_TEXTURE_2D, inst.pub.tex2d);
    // pixels is one byte per texel, tightly packed row-major.
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    // GL_R8: 128 encodes the surface (see pack_field_to_atlas), matching the
    // hull-clip shader's texel - 0.5 zero comparison.
    glTexImage2D(GL_TEXTURE_2D, 0, GL_R8, layout.width, layout.height, 0,
                GL_RED, GL_UNSIGNED_BYTE, pixels.data());
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glBindTexture(GL_TEXTURE_2D, 0);
    glActiveTexture(static_cast<GLenum>(prev_unit));
    glPixelStorei(GL_UNPACK_ALIGNMENT, prev_unpack);

    inst.pub.layout = layout;
    inst.pub.origin = inst.field.origin;
    inst.pub.cell   = inst.field.cell;
    inst.pub.dims   = inst.field.dims;
    inst.pub.scale  = inst.field.scale;
    return true;
}

}  // namespace renderer
