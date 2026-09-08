// native/src/renderer/include/renderer/instance_field_cache.h
#pragma once

#include <cstddef>
#include <filesystem>
#include <map>

#include <glm/glm.hpp>

#include <scenegraph/instance.h>
#include <voxel/distance_field.h>
#include <voxel/field_atlas.h>
#include <voxel/hull_volume_cache.h>

namespace renderer {

/// Per-instance mutable hull damage field.
///
/// Task 3's HullVolumeCache bakes ONE immutable signed distance field per
/// hull SOURCE and never mutates it -- every instance of that hull (every
/// Galaxy in the sector) must not share one battle-scarred field. This class
/// is the per-INSTANCE layer on top: on an instance's first carve() it
/// copies the shared baked field into a private, mutable field just for that
/// instance, then applies voxel::field_carve_oblate to the copy. Later
/// carves mutate that same private copy in place.
///
/// An instance that is never carve()'d has NO entry here at all -- get()
/// returns nullptr, nothing is packed, nothing is uploaded. That is the
/// point: an undamaged ship must cost exactly what it costs today (a fixed
/// carve-sphere array of zero active spheres), not "a field nobody looks at
/// yet".
///
/// Uploads are lazy and coalesced: a carve() only marks the instance dirty;
/// the actual pack-to-atlas + glTexImage2D happens on the next get(), and
/// only once, however many times get() is called before the next carve().
///
/// Owns one GL_R8 2D atlas texture per damaged instance, so -- like
/// CarveFieldCache -- it must be constructed and destroyed while a GL
/// context is current, and get() (which may upload) must be called with one
/// current too.
class InstanceFieldCache {
public:
    /// One instance's uploaded atlas plus the geometry the hull-clip shader
    /// needs to map a body-frame point onto it.
    struct Entry {
        unsigned int tex2d = 0;        // GL_R8 atlas
        voxel::AtlasLayout layout;
        glm::vec3 origin{0.0f};
        glm::vec3 cell{1.0f};
        glm::ivec3 dims{0};
        float scale = 1.0f;
    };

    /// `bake_cache` is where carve() reads the shared, per-hull baked field
    /// to copy on an instance's first carve. Left null (the production
    /// default), carve() resolves it lazily to the process-wide
    /// renderer::hull_volume_cache() singleton.
    ///
    /// That singleton fixes its on-disk root at whatever
    /// set_hull_volume_cache_root last configured BEFORE the first call to
    /// hull_volume_cache() anywhere in the process -- see carve_field_cache.h.
    /// native/tests/renderer/hull_volume_cache_root_test.cc documents itself
    /// as the ONLY caller of that singleton getter in the renderer_tests
    /// binary specifically so that "first call" stays deterministic; tests
    /// of this class inject their own local voxel::HullVolumeCache here
    /// instead of adding a second caller.
    explicit InstanceFieldCache(voxel::HullVolumeCache* bake_cache = nullptr);
    ~InstanceFieldCache();

    InstanceFieldCache(const InstanceFieldCache&) = delete;
    InstanceFieldCache& operator=(const InstanceFieldCache&) = delete;

    /// Carve into this instance's field, creating it (copy-on-first-carve
    /// from the baked cache) if it does not exist yet. No-op -- no entry is
    /// created or touched -- when the hull has no baked field (missing or
    /// unparseable source, or a genuinely empty mesh).
    void carve(scenegraph::InstanceId id, const std::filesystem::path& source,
               float authored_res, const glm::vec3& center_body,
               const glm::vec3& normal_body, float radius);

    /// The uploaded atlas for this instance, or nullptr if it has none.
    /// Uploads lazily when dirty. Must be called with a GL context current.
    const Entry* get(scenegraph::InstanceId id);

    /// Instance destroyed: release its entry and GL texture.
    void forget(scenegraph::InstanceId id);

    std::size_t size() const { return instances_.size(); }

    /// How many times get() has actually re-uploaded a texture, as opposed
    /// to serving an already-current one -- the same reason
    /// voxel::HullVolumeCache exposes bakes(): a cache that silently
    /// re-uploads a whole atlas every frame is otherwise indistinguishable
    /// from one that works.
    std::size_t uploads() const { return uploads_; }

private:
    // Deliberately not std::unordered_map<InstanceId, ...>: that needs a
    // std::hash<scenegraph::InstanceId> specialization, and the only one in
    // this codebase lives in renderer/shield_state.h, an unrelated header
    // this class has no business depending on. A small ordered map with an
    // inline comparator needs nothing else.
    struct InstanceIdLess {
        bool operator()(const scenegraph::InstanceId& a,
                        const scenegraph::InstanceId& b) const {
            if (a.index != b.index) return a.index < b.index;
            return a.generation < b.generation;
        }
    };

    struct Instance {
        voxel::DistanceField field;   // this instance's own mutable copy
        Entry pub;
        bool dirty = true;
    };

    // Packs `inst.field` and uploads it to `inst.pub.tex2d` (creating the
    // texture on first use), refreshing every other Entry field to match.
    // Returns false -- leaving inst.pub and the dirty flag untouched -- when
    // the field can't be packed (defensive: not reachable for a field that
    // passed the !empty() check in carve(), but upload() does not assume
    // that invariant on its own).
    bool upload(Instance& inst);

    std::map<scenegraph::InstanceId, Instance, InstanceIdLess> instances_;
    voxel::HullVolumeCache* bake_cache_ = nullptr;
    std::size_t uploads_ = 0;
};

}  // namespace renderer
