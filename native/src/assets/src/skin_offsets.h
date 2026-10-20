#pragma once
// Re-seat a legacy-skinned shape from its skin offsets when its own vertex
// array disagrees with them.
//
// BC's NiTriShapeSkinController stores, per (bone, vertex) influence, the
// vertex's position in that bone's space; BC skins from those offsets, so the
// shape's vertex array is only a starting copy. In every stock character the
// two agree to ~0.0003 units, so the loader bakes the vertex array and skins
// that. kessok_head.NIF is the exception: its vertex array is stored rotated
// 90° and shifted ~44 units from where its offsets put it, which buried the
// Kessok's head in its chest.
#include <assets/mesh.h>
#include <nif/block.h>

#include <glm/glm.hpp>

#include <optional>
#include <vector>

namespace assets::detail {

/// Vertex-vs-offset disagreement (model units) above which a shape is re-seated.
/// The stock corpus's own drift tops out at ~0.0003; the Kessok head's is ~44.
inline constexpr float kSkinOffsetTolerance = 0.01f;

/// `cpu` holds the shape's vertices already baked into bind-model space.
/// `skin_bone_bind_world[b]` is the bind-model transform of the skin's bone b,
/// or nullopt when the skeleton has no such bone (then nothing is changed:
/// the offsets cannot be evaluated).
///
/// If every skinned vertex already sits within kSkinOffsetTolerance of
/// Σ w·bone_bind·offset, `cpu` is left byte-identical and this returns false.
/// Otherwise skinned vertices move to that position, unskinned ones follow the
/// least-squares transform fitted from old to new positions, normals turn by
/// that transform, and this returns true.
bool seat_from_skin_offsets(
    MeshCpu& cpu,
    const nif::NiTriShapeSkinController& skin,
    const std::vector<std::optional<glm::mat4>>& skin_bone_bind_world);

}  // namespace assets::detail
