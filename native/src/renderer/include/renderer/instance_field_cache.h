// native/src/renderer/include/renderer/instance_field_cache.h
#pragma once

#include <cstddef>
#include <filesystem>
#include <map>
#include <vector>

#include <glm/glm.hpp>

#include <scenegraph/instance.h>
#include <voxel/distance_field.h>
#include <voxel/field_atlas.h>
#include <voxel/hull_volume_cache.h>
#include <voxel/volume.h>

namespace renderer {

/// Per-instance mutable hull DAMAGE field -- NOT a copy of the hull's own
/// shape.
///
/// Task 3's HullVolumeCache bakes ONE immutable signed distance field per
/// hull SOURCE (the hull's own triangles) and never mutates it -- every
/// instance of that hull (every Galaxy in the sector) must not share one
/// battle-scarred field. This class is the per-INSTANCE layer on top, but on
/// an instance's first carve() it does NOT copy the baked field's cell
/// values: it copies only the baked field's LATTICE (dims/origin/cell/scale)
/// into a private, mutable field for that instance, with every cell set to
/// -127 ("no damage anywhere"), then applies voxel::field_carve_oblate to
/// that. Later carves mutate the same private field in place.
///
/// Why not copy the baked hull SDF itself (the design this class shipped
/// with first, and the bug this comment now warns against): trilinear
/// reconstruction of a hull SDF cannot represent a plate a few cells thick --
/// the reconstructed surface lands inside the real one, so BOTH faces of a
/// thin panel (the saucer rim, pylons) read "outside the hull" and opaque.frag
/// discards them, live, on any ship carrying so much as one entry here. A
/// damage-only field sidesteps this entirely: untouched hull is exactly the
/// no-damage value (-127) everywhere, so it can never be discarded regardless
/// of reconstruction error, and the only cells that carry any signal are
/// ones a brush actually touched, where sub-cell error is harmless (the carve
/// boundary already has kHullFieldIsoMargin's slack -- see opaque.frag).
/// field_carve_oblate needs no change for this: it already computes
/// `d = max(d_old, -d_brush)`, monotonic regardless of what d_old means.
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

    /// Carve into this instance's field, creating it (lattice-only
    /// copy-on-first-carve from the baked cache, filled with "no damage") if
    /// it does not exist yet. No-op -- no entry is created or touched --
    /// when the hull has no baked field (missing or unparseable source, or a
    /// genuinely empty mesh): the baked field is still the one thing that
    /// tells this instance where its lattice sits and how coarse it is.
    void carve(scenegraph::InstanceId id, const std::filesystem::path& source,
               float authored_res, const glm::vec3& center_body,
               const glm::vec3& normal_body, float radius);

    /// The uploaded atlas for this instance, or nullptr if it has none.
    /// Uploads lazily when dirty. Must be called with a GL context current.
    const Entry* get(scenegraph::InstanceId id);

    /// The instance's current damage field, or nullptr when it has none.
    const voxel::DistanceField* field(scenegraph::InstanceId id) const;

    /// Move `cells` out of `parent`'s field into a NEW entry for `child` on
    /// the same lattice. child = parent's values on `cells`, +127 elsewhere;
    /// parent = +127 on `cells`. Both marked dirty. False if parent has no
    /// field or child already has one.
    bool split(scenegraph::InstanceId parent, scenegraph::InstanceId child,
               const std::vector<glm::ivec3>& cells);

    /// Set `cells` to +127 on `id`'s field (a sub-floor component: the
    /// material is gone, no chunk is made). False if no field.
    bool remove_cells(scenegraph::InstanceId id, const std::vector<glm::ivec3>& cells);

    /// Capsule counterpart of carve(): same lazy entry creation, same
    /// lattice.
    void carve_capsule(scenegraph::InstanceId id, const std::filesystem::path& source,
                       float authored_res, const glm::vec3& p0_body,
                       const glm::vec3& p1_body, float radius);

    /// Instance destroyed: release its entry and GL texture.
    void forget(scenegraph::InstanceId id);

    /// The union of every brush box written to `id` since the last take
    /// (empty for an unknown instance, or when nothing was carved since),
    /// and clears it. This is what the severance check consumes -- see
    /// voxel::hull_severance_local -- and it is deliberately separate from
    /// the upload's own dirty box: the render and the Python-side check run
    /// on different cadences, so each keeps its own accumulator. split()
    /// and remove_cells() do not touch it: they are the OUTPUT of a check,
    /// not new damage.
    voxel::CellBox take_severance_box(scenegraph::InstanceId id);

    /// True exactly once per instance: the first time the severance check
    /// asks. That first check must be the full BFS (a hull whose bake is
    /// already several components has to shed them once), and every check
    /// after it may rely on the single-component invariant. False for an
    /// unknown instance. A chunk created by split() is a new instance and
    /// gets its own first check.
    bool take_first_severance_check(scenegraph::InstanceId id);

    std::size_t size() const { return instances_.size(); }

    /// How many times get() has actually re-uploaded a texture, as opposed
    /// to serving an already-current one -- the same reason
    /// voxel::HullVolumeCache exposes bakes(): a cache that silently
    /// re-uploads a whole atlas every frame is otherwise indistinguishable
    /// from one that works.
    std::size_t uploads() const { return uploads_; }

    /// How many of those uploads were REGION uploads (glTexSubImage2D of the
    /// dirty box only) rather than a whole-atlas glTexImage2D. Every upload
    /// after an instance's first should be one, except after split() /
    /// remove_cells(); the test pins that, since a cache that quietly fell
    /// back to full uploads would still render correctly.
    std::size_t partial_uploads() const { return partial_uploads_; }

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
        // This instance's own mutable DAMAGE field: same lattice as the
        // baked hull field (dims/origin/cell/scale), but its cell VALUES
        // are not the baked field's -- they start at -127 ("no damage") and
        // only ever move where a carve touched them. See this header's
        // class comment.
        voxel::DistanceField field;
        Entry pub;
        // The packed atlas bytes stay resident so a later carve can
        // re-encode only its box into them (voxel::pack_field_region_to_
        // atlas) and upload that rectangle; `dirty_box` is the union of the
        // brush boxes since the last upload. `full` forces a whole-atlas
        // pack + glTexImage2D: the first upload, and after split() /
        // remove_cells(), which touch arbitrary cells.
        std::vector<std::uint8_t> atlas;
        voxel::CellBox dirty_box;
        voxel::CellBox sever_box;
        bool severance_checked = false;
        bool full = true;
        bool dirty() const { return full || !dirty_box.empty(); }
    };

    // Packs `inst.field` and uploads it to `inst.pub.tex2d` (creating the
    // texture on first use), refreshing every other Entry field to match.
    // Returns false -- leaving inst.pub and the dirty flag untouched -- when
    // the field can't be packed (defensive: not reachable for a field that
    // passed the !empty() check in carve(), but upload() does not assume
    // that invariant on its own).
    bool upload(Instance& inst);

    // The lattice-only construction shared by carve() (on an instance's
    // first carve) and split() (for the new child): copies `lattice`'s
    // dims/origin/cell/scale but NOT its cell values -- every cell starts at
    // -127, "no damage anywhere". See this header's class comment for why.
    static Instance make_blank_like(const voxel::DistanceField& lattice);

    std::map<scenegraph::InstanceId, Instance, InstanceIdLess> instances_;
    voxel::HullVolumeCache* bake_cache_ = nullptr;
    std::size_t uploads_ = 0;
    std::size_t partial_uploads_ = 0;
};

/// Result of hull_carve_deposit: the sphere slot's visible radius before and
/// after this deposit. Exists so hull_carve_deposit does not need to know
/// anything about breach events itself -- the caller (host_bindings.cc's
/// hull_carve_add) compares the two to decide whether to fire one.
/// What hull_split_detached does before paying for voxel::hull_connectivity.
enum class SeveranceDecision {
    kSkip,     // nothing can have been severed since the last check
    kFullBfs   // run hull_connectivity
};

/// The decision, as a pure function so the binding's glue is testable:
/// `first` (take_first_severance_check) forces the full BFS; otherwise an
/// empty `box` (nothing carved since the last check -- hull_breakup.drain
/// can ask twice for one carve) skips it, and a non-empty box skips it only
/// when voxel::hull_severance_local proves the carve cut nothing off.
SeveranceDecision severance_decision(bool first,
                                     const voxel::DistanceField& baked,
                                     const voxel::DistanceField& damage,
                                     const voxel::CellBox& box);

struct HullCarveDepositResult {
    float prev_radius = 0.0f;  // c.radius BEFORE this deposit
    float radius = 0.0f;       // c.radius AFTER this deposit
};

/// Deposit hull-damage strength onto BOTH representations of one instance's
/// damage in a single call: the fixed 24-slot sphere ring (`carve`,
/// scenegraph::HullCarveField -- still the only thing the breach scoop, the
/// framework lattice and the breach-event ring read) and, alongside it, the
/// per-instance distance field (`field_cache`) -- using the SAME body-frame
/// centre/normal and the SAME derived visible radius for both, so the two
/// representations describe the same damage.
///
/// "Same centre/normal" means the SPHERE SLOT's stored centre/normal, not
/// this call's `center_body`/`normal_body` arguments -- they coincide only
/// on a slot's first deposit. HullCarveField::add deliberately does NOT move
/// an existing slot's centre/normal when a later hit merges into it within
/// influence radius (a swept beam gouges a line, not one carve dragged along
/// it -- see hull_carve.cc); it only grows `strength` and re-derives
/// `radius` in place. This function reads the merged slot BACK from `add()`
/// and carves the field at *its* centre/normal, so a merged hit's field
/// carve stays anchored where the sphere and the scoop are, growing in
/// place exactly like the sphere does, rather than wandering to wherever the
/// most recent raw hit landed.
///
/// This is the entire sequence host_bindings.cc's `hull_carve_add` pybind
/// binding runs once it has transformed a hit into body frame and converted
/// GU to model units: deposit strength into the sphere ring, derive the
/// visible radius from the grown total via
/// scenegraph::hull_carve_strength_to_radius_gu (monotonic -- never below
/// `floor_radius_model`, never shrinking), then carve the field at the
/// (possibly merged) slot's own centre/normal with that radius. It lives
/// here, not inlined in the pybind lambda, specifically so a test can call
/// this IDENTICAL code path instead of re-deriving the same arithmetic and
/// silently drifting from it -- host_bindings.cc's `hull_carve_add` is a
/// thin wrapper around this function plus the world->body transform and the
/// breach-event push.
///
/// `field_cache` may be null and `source` may be empty (a hull with no baked
/// field, or field carving unavailable) -- the sphere ring is still updated
/// exactly as it was before this feature existed.
///
/// `fill` is the same backing-material gate the sphere path already applies
/// in frame.cc (renderer::carve_has_backing / CarveFieldCache::
/// volume_for_source): the ORIGINAL, uncarved fill volume for this hull
/// source, used only to decide whether the FIELD carve below should happen
/// at all. When `fill` is non-null and carve_has_backing(*fill, slot centre,
/// slot normal) is false, the field carve is skipped -- same as frame.cc
/// dropping that slot from u_carve_spheres and breach_pass.cc drawing no
/// scoop for it -- so a hole with nothing behind it in the sphere/scoop
/// representation cannot appear as a see-through hole in the field
/// representation either. `fill` is null when no fill volume is available
/// for this source (matching frame.cc's carve_fill_entry: an empty/missing
/// mask means "nothing to gate with", so the carve proceeds ungated, exactly
/// as it did before this parameter existed). This gate intentionally does
/// NOT touch the sphere ring above -- `carve.add()` and the derived radius
/// are computed identically regardless of `fill`.
///
/// NOTE: this duplicates the backing-material decision that frame.cc's
/// sphere path already makes (carve_has_backing is the same ONE function
/// carve_field_cache.h asks both the hull cut and the scoop to share) --
/// consolidating so the field path shares that single call site too (e.g. by
/// moving the gate inside scenegraph::HullCarveField::add) is follow-up
/// work, not done here.
///
/// Every radius argument here is already in MODEL UNITS (or a plain
/// multiplier, for radius_modifier/inv_scale); this function performs no
/// GU<->model conversion of its own -- the caller does that once, the same
/// way it always has.
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
    const voxel::VoxelVolume* fill = nullptr);

}  // namespace renderer
