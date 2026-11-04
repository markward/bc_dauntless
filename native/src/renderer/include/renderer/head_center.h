// native/src/renderer/include/renderer/head_center.h
//
// The posed HEAD centre of a skinned character: the officer-zoom look-at
// point (get_instance_head_center) and what the bridge officer pick projects
// (engine/ui/bridge_officer_picking.py), asked for each officer every bridge
// frame. head_center.cc is optimised in every configuration with no
// multiply-add contraction, so its answer is bit-identical to the -O0 code it
// replaced (pinned by native/tests/renderer/head_center_test.cc).
#pragma once

#include <cstddef>
#include <cstdint>
#include <optional>
#include <unordered_map>
#include <vector>

#include <glm/glm.hpp>

#include <scenegraph/instance.h>

namespace assets { struct Model; }

namespace renderer {

/// MODEL-space (before inst.world) centre of the skinned head: the AABB
/// centre of the vertices in the grafted head mesh range
/// [model.head_mesh_begin, meshes.size()), each skinned exactly as
/// skinned_bridge.vert does (sum w_k * palette[idx_k] * v). Without a head
/// range (head_mesh_begin < 0, non-composed models) the head is the vertices
/// bound to "Bip01 Head"; with neither, the whole skinned body's centre.
/// The mesh range is the canonical partition (graft_head_cpu,
/// model_compose.h): on bind-mismatched pairs the weld moves head vertices
/// onto ALIAS bones ("<bone>@head-bind"), so the bone-index test misses them.
/// nullopt when no vertex is skinned (empty palette, no weights).
std::optional<glm::vec3> skinned_head_center(const assets::Model& model,
                                             const std::vector<glm::mat4>& palette);

/// skinned_head_center memoised per instance on ALL of its inputs: the
/// instance, its model handle and model, and the palette's exact bytes. A hit
/// returns the stored bits, so the answer never differs from a recompute.
/// Assumes a loaded model's vertex data never changes (true: meshes are
/// built once at load). Model handles are reissued only after the host's
/// init/shutdown, which must clear() this cache.
class HeadCenterCache {
public:
    /// More entries than this (instances realised over a long session) and
    /// the cache starts over rather than growing.
    static constexpr std::size_t kMaxEntries = 64;

    std::optional<glm::vec3> get(scenegraph::InstanceId id,
                                 std::uint64_t model_handle,
                                 const assets::Model& model,
                                 const std::vector<glm::mat4>& palette);
    void clear() { entries_.clear(); }
    std::size_t size() const { return entries_.size(); }
    /// Misses so far (test hook).
    std::size_t computes() const { return computes_; }

private:
    struct Entry {
        std::uint64_t model_handle = 0;
        const assets::Model* model = nullptr;
        std::vector<glm::mat4> palette;
        std::optional<glm::vec3> center;
    };
    std::unordered_map<std::uint64_t, Entry> entries_;
    std::size_t computes_ = 0;
};

}  // namespace renderer
