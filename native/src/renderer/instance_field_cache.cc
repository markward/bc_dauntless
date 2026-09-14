// native/src/renderer/instance_field_cache.cc
#include <renderer/instance_field_cache.h>

#include <renderer/carve_field_cache.h>
#include <voxel/field_brush.h>
#include <voxel/hull_connectivity.h>

#include <algorithm>
#include <cstdint>
#include <utility>

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

InstanceFieldCache::Instance InstanceFieldCache::make_blank_like(
        const voxel::DistanceField& lattice) {
    // LATTICE ONLY -- see the class comment: an instance field takes the
    // baked field's dims/origin/cell/scale and NOT its values. Every cell
    // starts at -127, "no damage anywhere"; only brushes raise a cell.
    Instance inst;
    inst.field.dims   = lattice.dims;
    inst.field.origin = lattice.origin;
    inst.field.cell   = lattice.cell;
    inst.field.scale  = lattice.scale;
    inst.field.dist.assign(
        static_cast<std::size_t>(lattice.dims.x)
            * static_cast<std::size_t>(lattice.dims.y)
            * static_cast<std::size_t>(lattice.dims.z),
        static_cast<std::int8_t>(-127));
    return inst;
}

void InstanceFieldCache::carve(scenegraph::InstanceId id,
                               const std::filesystem::path& source,
                               float authored_res,
                               const glm::vec3& center_body,
                               const glm::vec3& normal_body,
                               float radius) {
    auto it = instances_.find(id);
    if (it == instances_.end()) {
        // Resolve the shared per-hull baked field: this instance's private
        // field takes only its LATTICE (dims/origin/cell/scale), not its
        // distance values -- see instance_field_cache.h's class comment for
        // why. `authored_res` is BC's raw SetDamageResolution ratio, passed
        // straight through -- HullVolumeCache::get is the one that divides
        // it by quality, not us (see instance_field_cache.h /
        // carve_field_cache.h's warnings about this).
        voxel::HullVolumeCache& cache =
            bake_cache_ != nullptr ? *bake_cache_ : renderer::hull_volume_cache();
        const voxel::DistanceField& baked =
            cache.get(source, authored_res, voxel::kDefaultQuality);
        if (baked.empty()) return;   // hull has no baked field: stay absent

        it = instances_.emplace(id, make_blank_like(baked)).first;
    }

    const voxel::CellBox box = voxel::field_carve_oblate(
        it->second.field, center_body, normal_body, radius);
    it->second.dirty_box.include(box);
    it->second.sever_box.include(box);
}

const voxel::DistanceField* InstanceFieldCache::field(
        scenegraph::InstanceId id) const {
    auto it = instances_.find(id);
    return it == instances_.end() ? nullptr : &it->second.field;
}

bool InstanceFieldCache::split(scenegraph::InstanceId parent,
                               scenegraph::InstanceId child,
                               const std::vector<glm::ivec3>& cells) {
    auto pit = instances_.find(parent);
    if (pit == instances_.end()) return false;
    if (instances_.find(child) != instances_.end()) return false;

    Instance c = make_blank_like(pit->second.field);
    // The chunk is what the parent WAS on the component and nothing
    // anywhere else: +127 ("fully carved") outside the component, so the
    // hull clip discards every fragment that is not part of this piece.
    std::fill(c.field.dist.begin(), c.field.dist.end(), static_cast<std::int8_t>(127));
    voxel::DistanceField& pf = pit->second.field;
    for (const auto& cc : cells) {
        if (cc.x < 0 || cc.y < 0 || cc.z < 0 ||
            cc.x >= pf.dims.x || cc.y >= pf.dims.y || cc.z >= pf.dims.z) continue;
        const std::size_t i = pf.index(cc.x, cc.y, cc.z);
        c.field.dist[i] = pf.dist[i];   // keep the holes it already had
        pf.dist[i] = 127;               // and it is gone from the parent
    }
    c.full = true;
    pit->second.full = true;
    instances_.emplace(child, std::move(c));
    return true;
}

bool InstanceFieldCache::remove_cells(scenegraph::InstanceId id,
                                      const std::vector<glm::ivec3>& cells) {
    auto it = instances_.find(id);
    if (it == instances_.end()) return false;
    voxel::DistanceField& f = it->second.field;
    for (const auto& cc : cells) {
        if (cc.x < 0 || cc.y < 0 || cc.z < 0 ||
            cc.x >= f.dims.x || cc.y >= f.dims.y || cc.z >= f.dims.z) continue;
        f.dist[f.index(cc.x, cc.y, cc.z)] = 127;
    }
    it->second.full = true;
    return true;
}

void InstanceFieldCache::carve_capsule(scenegraph::InstanceId id,
                                       const std::filesystem::path& source,
                                       float authored_res,
                                       const glm::vec3& p0_body,
                                       const glm::vec3& p1_body,
                                       float radius) {
    auto it = instances_.find(id);
    if (it == instances_.end()) {
        voxel::HullVolumeCache& cache =
            bake_cache_ != nullptr ? *bake_cache_ : renderer::hull_volume_cache();
        const voxel::DistanceField& baked =
            cache.get(source, authored_res, voxel::kDefaultQuality);
        if (baked.empty()) return;
        it = instances_.emplace(id, make_blank_like(baked)).first;
    }
    const voxel::CellBox box = voxel::field_carve_capsule(
        it->second.field, p0_body, p1_body, radius);
    it->second.dirty_box.include(box);
    it->second.sever_box.include(box);
}

const InstanceFieldCache::Entry* InstanceFieldCache::get(
        scenegraph::InstanceId id) {
    auto it = instances_.find(id);
    if (it == instances_.end()) return nullptr;

    Instance& inst = it->second;
    if (inst.dirty()) {
        if (upload(inst)) {
            inst.full = false;
            inst.dirty_box = voxel::CellBox{};
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

voxel::CellBox InstanceFieldCache::take_severance_box(scenegraph::InstanceId id) {
    auto it = instances_.find(id);
    if (it == instances_.end()) return voxel::CellBox{};
    return std::exchange(it->second.sever_box, voxel::CellBox{});
}

bool InstanceFieldCache::take_first_severance_check(scenegraph::InstanceId id) {
    auto it = instances_.find(id);
    if (it == instances_.end()) return false;
    return !std::exchange(it->second.severance_checked, true);
}

SeveranceDecision severance_decision(bool first,
                                     const voxel::DistanceField& baked,
                                     const voxel::DistanceField& damage,
                                     const voxel::CellBox& box) {
    if (first) return SeveranceDecision::kFullBfs;
    if (box.empty()) return SeveranceDecision::kSkip;
    return voxel::hull_severance_local(baked, damage, box) == voxel::Severance::kConnected
               ? SeveranceDecision::kSkip
               : SeveranceDecision::kFullBfs;
}

bool InstanceFieldCache::upload(Instance& inst) {
    const voxel::AtlasLayout layout = voxel::atlas_layout_for(inst.field.dims);
    if (!layout.valid()) return false;

    // Region path: the texture exists, nothing forced a full refresh, and
    // the resident atlas can be patched in place. A failed region pack
    // (which the voxel tests say cannot happen for an in-range box) falls
    // through to the full path rather than leaving stale texels.
    const bool region =
        inst.pub.tex2d != 0 && !inst.full && !inst.dirty_box.empty() &&
        inst.pub.layout.width == layout.width &&
        inst.pub.layout.height == layout.height &&
        voxel::pack_field_region_to_atlas(inst.field, layout, inst.dirty_box,
                                          inst.atlas);
    if (!region) {
        inst.atlas = voxel::pack_field_to_atlas(inst.field, layout);
        if (inst.atlas.empty()) return false;
    }

    if (inst.pub.tex2d == 0) {
        GLuint t = 0;
        glGenTextures(1, &t);
        inst.pub.tex2d = t;
    }

    GLint prev_unpack = 0;
    glGetIntegerv(GL_UNPACK_ALIGNMENT, &prev_unpack);
    GLint prev_row_length = 0;
    glGetIntegerv(GL_UNPACK_ROW_LENGTH, &prev_row_length);
    GLint prev_unit = 0;
    glGetIntegerv(GL_ACTIVE_TEXTURE, &prev_unit);
    glActiveTexture(GL_TEXTURE0);

    glBindTexture(GL_TEXTURE_2D, inst.pub.tex2d);
    // pixels is one byte per texel, tightly packed row-major.
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    if (region) {
        // One sub-image per touched slice, read straight out of the
        // resident atlas: ROW_LENGTH makes GL stride by the full atlas
        // width while we hand it the rectangle's top-left byte.
        glPixelStorei(GL_UNPACK_ROW_LENGTH, layout.width);
        for (int z = inst.dirty_box.lo.z; z <= inst.dirty_box.hi.z; ++z) {
            const voxel::AtlasRect r =
                voxel::atlas_rect_for(layout, inst.field.dims, inst.dirty_box, z);
            const std::uint8_t* src =
                inst.atlas.data()
                + static_cast<std::size_t>(r.y) * static_cast<std::size_t>(layout.width)
                + static_cast<std::size_t>(r.x);
            glTexSubImage2D(GL_TEXTURE_2D, 0, r.x, r.y, r.w, r.h,
                            GL_RED, GL_UNSIGNED_BYTE, src);
        }
        glPixelStorei(GL_UNPACK_ROW_LENGTH, prev_row_length);
        ++partial_uploads_;
    } else {
        // GL_R8: 128 encodes the surface (see pack_field_to_atlas), matching the
        // hull-clip shader's sample_hull_field, which subtracts 128.0/255.0 EXACTLY
        // (NOT 0.5 -- opaque.frag's own comment at that subtraction calls out the
        // distinction as load-bearing) before comparing against zero.
        glTexImage2D(GL_TEXTURE_2D, 0, GL_R8, layout.width, layout.height, 0,
                     GL_RED, GL_UNSIGNED_BYTE, inst.atlas.data());
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    }
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

HullCarveDepositResult hull_carve_deposit(
        scenegraph::HullCarveField& carve,
        InstanceFieldCache* field_cache,
        scenegraph::InstanceId id,
        const std::filesystem::path& source,
        float authored_res,
        const glm::vec3& center_body,
        const glm::vec3& normal_body,
        float influ_radius_model,
        float strength,
        float floor_radius_model,
        float radius_modifier,
        float inv_scale,
        const voxel::VoxelVolume* fill) {
    scenegraph::HullCarve& c =
        carve.add(center_body, influ_radius_model, strength, normal_body);
    const float prev_radius = c.radius;
    // Strength -> an ABSOLUTE carve radius (GU): a weapon carves the same
    // hole whatever it hits, so no scaling by hull size. radius_modifier is
    // BC's per-ship DamageRadMod (default 1.0; only big fixed structures set
    // it bigger). inv_scale converts that GU radius to the instance's model
    // units, same as influ_radius_model/floor_radius_model already are.
    const float vis_gu =
        scenegraph::hull_carve_strength_to_radius_gu(c.strength) * radius_modifier;
    const float vis_model = vis_gu * inv_scale;
    c.radius = std::max(c.radius, std::max(floor_radius_model, vis_model));

    // Carve the per-instance distance field at the SLOT's own centre/normal
    // -- NOT this call's raw center_body/normal_body -- so the two
    // representations describe the same damage even when this deposit
    // MERGED into an existing carve. HullCarveField::add deliberately keeps
    // a merged slot's original centre/normal (a swept beam gouges a line,
    // not one carve dragged to the newest hit point; see hull_carve.cc), so
    // c.center_body/c.surface_normal are only equal to this call's
    // center_body/normal_body on a slot's FIRST deposit. Carving at the raw
    // call-site point instead would anchor the field's hole at whichever hit
    // happened to land most recently while the sphere and the scoop stayed
    // fixed at the first hit -- the two representations would visibly drift
    // apart under any sustained fire on one hull section. No-op when there
    // is no field to carve (missing/disabled cache, or a hull with no baked
    // source).
    //
    // Backing-material gate (see this function's doc comment): a carve with
    // nothing behind it must not be cut into the field either, or the hull
    // discards with no scoop drawn behind it -- see straight through the
    // ship. `fill == nullptr` means no fill volume was available to gate
    // with, so the carve proceeds exactly as it did before this gate
    // existed.
    if (field_cache != nullptr && !source.empty() &&
        (fill == nullptr || carve_has_backing(*fill, c.center_body,
                                              c.surface_normal))) {
        field_cache->carve(id, source, authored_res, c.center_body,
                           c.surface_normal, c.radius);
    }

    return HullCarveDepositResult{prev_radius, c.radius};
}

}  // namespace renderer
