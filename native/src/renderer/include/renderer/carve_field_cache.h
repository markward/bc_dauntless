// native/src/renderer/include/renderer/carve_field_cache.h
#pragma once

#include <cstdint>
#include <filesystem>
#include <string>
#include <unordered_map>

#include <glm/glm.hpp>

#include <voxel/source_cache.h>
#include <voxel/volume.h>

namespace renderer {

/// True when the ORIGINAL fill volume has hull material behind a carve — the
/// backing-material gate.
///
/// The hull hole (opaque.frag's carve-sphere discard) and the breach scoop
/// (breach.frag, masked by this same fill) are two DIFFERENT shapes. Wherever
/// they disagree — a hull plate thinner than the voxel mask can resolve — the
/// hull is cut and nothing is drawn behind it, so you see straight through the
/// ship. Stock BC has the identical artifact for the identical reason: its
/// authored metaballs are 2.7-6.7 mask cells in radius against a mask 2-4 cells
/// thick.
///
/// So both passes ask this one question before acting on a carve: march inward
/// from its centre along -normal and look for any fill. False → the scoop would
/// have nothing to draw, so the hull must not be cut either. ONE function, so
/// the cut and the scoop cannot drift apart.
///
/// Runs per carve on the CPU rather than per fragment on the GPU: a sampler3D
/// in opaque.frag miscompiles on this Mac's GL driver (a fetch that never
/// executes still drove a degenerate normal NaN), and per carve is enough.
bool carve_has_backing(const voxel::VoxelVolume& fill,
                       const glm::vec3& center_body,
                       const glm::vec3& normal_body);

/// Shared STATIC original-fill cache (hull-breach-2b Path C).
///
/// Serves the original (UNCARVED) hull fill as a GL_R8 3D texture, built
/// once per hull source path and reused across all instances of that hull.
/// The breach pass samples this texture as a material mask: keep a scoop
/// fragment iff fill(p_body) >= iso (solid material), else discard.
///
/// The hull clip no longer needs a fill texture (it is a pure sphere clip);
/// this cache is consumed only by the breach pass.
///
/// Owns GL texture objects; must be constructed/destroyed while a GL context
/// is current (same lifetime contract as BreachPass).
class CarveFieldCache {
public:
    CarveFieldCache() = default;
    ~CarveFieldCache();
    CarveFieldCache(const CarveFieldCache&)            = delete;
    CarveFieldCache& operator=(const CarveFieldCache&) = delete;

    // Isovalue: BC's 0..127 fill field. The 3D texture is GL_R8: occ byte
    // 0..127 samples as occ/255.0 in [0,1]. The shader compares against
    // kIsovalue/255.0 (= 64/255 ≈ 0.251).
    static constexpr int kIsovalue = 64;

    // SPIKE (backing-material gate): the "is there ANY hull material here?"
    // threshold, as opposed to kIsovalue's "is this solid interior?".
    //
    // Measured on stock hulls (Galaxy/Sovereign/Akira, hull-triangle centroids
    // sampled against their own _vox.nif): 39-53% of hull TRIANGLES sit at or
    // outside the kIsovalue surface. The mask's iso surface and the hull mesh
    // simply do not coincide — that is the "folded in" shape of BC's authored
    // volumes. Gating the hull cut at kIsovalue therefore suppresses damage on
    // 13-31% of the hull; gating at "any fill" suppresses 2-11%, which is the
    // irreducible set (marching further inward does not shrink it).
    //
    // The scoop (breach.frag) discards against THIS value, and the hull cut is
    // gated against it CPU-side (frame.cc), so the hole and the interior are the
    // same shape by construction. kIsovalue is retained for the scoop's
    // molten-rim falloff, which wants the solid-interior surface.
    //
    // NOT gated in opaque.frag: adding a sampler3D there was measured to
    // miscompile on this Mac's GL driver — merely declaring the fetch (which
    // never executed, the gate being disabled) made a degenerate vertex normal
    // go NaN through a clamp that had previously absorbed it, failing
    // HullClipTest.DegenerateNormalWithGradientOnStaysFinite. Per-carve on the
    // CPU needs no new sampler, costs nothing per fragment, and answers the same
    // question.
    static constexpr int kBackingIsovalue = 1;

    // Backing probe: how far inward to look, and in how many taps. MEASURED on
    // stock hulls — one tap suppresses 13-31% of the hull surface because the
    // mask's iso surface and the hull mesh do not coincide (39-53% of hull
    // triangles sit at or outside it); marching ~1.5 cells in 4 taps drops that
    // to 2-11%, and marching 3 cells does not improve on it.
    static constexpr int   kBackingTaps  = 4;
    static constexpr float kBackingCells = 1.5f;

    /// A cached static fill entry for one hull source path.
    struct Entry {
        unsigned int tex3d = 0;     // GL_R8 sampler3D (original/uncarved fill)
        glm::ivec3 dims{0};
        glm::vec3  origin{0.0f};
        glm::vec3  cell{1.0f};
    };

    /// Get (build if not yet cached) the static original fill texture for the
    /// given hull source path. Returns nullptr when the source fill is missing
    /// or the GL upload fails. The returned pointer is stable for the lifetime
    /// of the cache (source-keyed, never evicted).
    const Entry* get_for_source(const std::filesystem::path& source);

    /// The CPU-side original fill volume for a hull source — the same data
    /// get_for_source uploads, before it becomes a texture. Used by the
    /// backing-material gate, which runs per carve on the CPU rather than per
    /// fragment on the GPU. Returns an empty volume when the source has none.
    const voxel::VoxelVolume& volume_for_source(
            const std::filesystem::path& source) {
        return source_cache_.get_for_hull(source);
    }

private:
    void upload_texture(Entry& e, const voxel::VoxelVolume& vol);

    std::unordered_map<std::string, Entry> by_source_;
    voxel::SourceVolumeCache source_cache_;
};

}  // namespace renderer
