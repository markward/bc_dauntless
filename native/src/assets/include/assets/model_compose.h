// native/src/assets/src/model_compose.h
//
// Compose a head NIF's geometry onto a body Model's skeleton (SP3).
//
// A bridge officer is authored as two NIFs: a skinned body (carrying the
// Bip01 skeleton + animations) and a separate head. To render them as one
// skinned instance they must share a single skeleton and material palette.
// `graft_head` appends the head's meshes into the body Model, rigid-binding
// every grafted vertex to the body skeleton's attach bone (e.g.
// "Bip01 Head"), and appends the head's materials/textures with the index
// remapping that an append implies.
//
// The work is split so the CPU-side composition is testable without a GL
// context:
//   * graft_head_cpu — pure: remaps materials/textures into `body`, builds the
//     rigid-bound MeshCpu list, attaches them to a node. No GL.
//   * graft_head     — calls graft_head_cpu, uploads each MeshCpu, appends the
//     GL Mesh to body.meshes. Needs a current GL context.
#pragma once

#include <filesystem>
#include <string_view>
#include <vector>

#include <assets/mesh.h>
#include <assets/model.h>

namespace assets {

/// CPU-only stage of the head graft. On success:
///   * appends a copy of each grafted head material to body.materials, with
///     each stage's texture_index offset by the original body.textures.size();
///   * MOVES the head's textures into body.textures (assets::Texture is a
///     move-only RAII owner of its GL handle — it cannot be copied, so the
///     head is cannibalized; callers pass an owned head they no longer need);
///   * returns one ready-to-upload MeshCpu per head mesh that had cpu_data,
///     with every vertex rigid-bound to the attach bone (bone_indices
///     (idx,0,0,0), bone_weights (255,0,0,0)), material_index pointing at the
///     appended material, and node_index set to the node the GL mesh must be
///     registered on.
/// Returns an empty vector and leaves `body` unchanged when `attach_bone` is
/// not found in body.skeleton, or when the head has no graftable meshes.
/// `out_node_index` (if non-null) receives the body node index the new meshes
/// were attached to (so graft_head can register the uploaded GL meshes there).
std::vector<MeshCpu> graft_head_cpu(Model& body, Model& head,
                                    std::string_view attach_bone,
                                    int* out_node_index = nullptr);

/// Full graft: graft_head_cpu + GL upload. Appends one GL Mesh to body.meshes
/// per grafted MeshCpu and registers each on the chosen body node's mesh list.
/// Requires a current GL context. Returns false (body unchanged) if the attach
/// bone is missing or the head has no graftable meshes. `head` is cannibalized
/// (its textures are moved into `body`).
bool graft_head(Model& body, Model& head, std::string_view attach_bone);

/// Host-facing one-shot: load `body_nif` (skinned) and `head_nif` from disk
/// (resolving each model's textures against its own search-dir list, exactly
/// like the AssetCache path), graft the head onto the body's `attach_bone`, and
/// return the composed Model by value (mutable, GL handles uploaded). Both
/// models are built with keep_cpu_data so cpu-walking passes (bounds, shields)
/// keep working. Requires a current GL context. Throws on load/build failure.
///
/// Note on textures: BC characters reference their skins by the filenames
/// embedded in the NIF (e.g. "body.tga", "head.tga"), resolved against the
/// search dirs — there is no per-material "replace base texture" path in the
/// pipeline. So `body_tex_dirs` / `head_tex_dirs` are texture *search
/// directories*; pass the per-officer skin directory to substitute a skin.
Model compose_officer_model(
    const std::filesystem::path& body_nif,
    const std::vector<std::filesystem::path>& body_tex_dirs,
    const std::filesystem::path& head_nif,
    const std::vector<std::filesystem::path>& head_tex_dirs,
    std::string_view attach_bone);

}  // namespace assets
