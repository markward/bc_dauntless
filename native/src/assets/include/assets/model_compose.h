// native/src/assets/src/model_compose.h
//
// Compose a head NIF's geometry onto a body Model's skeleton (SP3).
//
// A bridge officer is authored as two NIFs: a skinned body (carrying the
// Bip01 skeleton + animations) and a separate head. To render them as one
// skinned instance they must share a single skeleton and material palette.
// `graft_head` appends the head's meshes into the body Model, welding them to
// the body skeleton BC-style (§3.5): each vertex keeps its authored skin
// weights and its bone indices are remapped by bone NAME via weld_head_bones
// (alias bones absorb bind-pose mismatches; head-only bones are appended).
// Materials/textures are appended with the index remapping an append implies.
//
// The work is split so the CPU-side composition is testable without a GL
// context:
//   * graft_head_cpu — pure: remaps materials/textures into `body`, builds the
//     rigid-bound MeshCpu list, attaches them to a node. No GL.
//   * graft_head     — calls graft_head_cpu, uploads each MeshCpu, appends the
//     GL Mesh to body.meshes. Needs a current GL context.
#pragma once

#include <filesystem>
#include <functional>
#include <map>
#include <span>
#include <string>
#include <string_view>
#include <vector>

#include <assets/animation.h>
#include <assets/mesh.h>
#include <assets/model.h>
#include <assets/texture.h>

namespace assets {

/// CPU-only stage of the head graft. On success:
///   * appends a copy of each grafted head material to body.materials, with
///     each stage's texture_index offset by the original body.textures.size();
///   * MOVES the head's textures into body.textures (assets::Texture is a
///     move-only RAII owner of its GL handle — it cannot be copied, so the
///     head is cannibalized; callers pass an owned head they no longer need);
///   * returns one ready-to-upload MeshCpu per head mesh that had cpu_data, with
///     vertex positions UNTOUCHED and bone indices remapped onto the body
///     skeleton by name (weld_head_bones; authored weights preserved). Heads
///     with no skeleton fall back to a rigid bind on the attach bone.
///     material_index points at the appended material; node_index is the node
///     the GL mesh must be registered on.
/// Returns an empty vector and leaves `body` unchanged when `attach_bone` is
/// not found in body.skeleton, or when the head has no graftable meshes.
/// `out_node_index` (if non-null) receives the body node index the new meshes
/// were attached to (so graft_head can register the uploaded GL meshes there).
std::vector<MeshCpu> graft_head_cpu(Model& body, Model& head,
                                    std::string_view attach_bone,
                                    int* out_node_index = nullptr);

/// Suffix for alias bones appended by weld_head_bones. The suffix guarantees
/// no clip track or rest_locals entry ever matches the alias by name, so its
/// posed local stays identity and build_bone_palette yields
/// posed_body_bone_world * head_inverse_bind — BC's exact §3.5 semantics.
inline constexpr std::string_view kHeadBindAliasSuffix = "@head-bind";

/// §3.5 bone rebinding (the BC "weld"). Maps every head-skeleton bone onto the
/// body skeleton by NAME, returning head-bone-index -> body-palette-index:
///   * name found, inverse binds equal (1e-4 component epsilon): the body
///     bone's own index — 18 of the 22 SDK body/head pairs are bit-identical;
///   * name found, binds differ (4 SDK pairs, per-bone translation deltas up
///     to ~5.9 units): appends an ALIAS bone (parent = the matched body bone,
///     local = identity, inverse_bind_pose = the HEAD's, name suffixed with
///     kHeadBindAliasSuffix) and maps to it. Reused if already appended.
///   * name missing from the body (e.g. "Bip01 Ponytail1"): appends a REAL
///     bone (name/local/inverse_bind from the head, parent = the mapped index
///     of its head-skeleton parent, resolved recursively).
/// Mutates `body` only by appending bones; existing indices stay valid.
std::vector<int> weld_head_bones(Skeleton& body, const Skeleton& head);

/// Full graft: graft_head_cpu + GL upload. Appends one GL Mesh to body.meshes
/// per grafted MeshCpu and registers each on the chosen body node's mesh list.
/// Requires a current GL context. `head` is cannibalized (its textures are
/// moved into `body`).
///
/// Returns the body.meshes indices of the newly-appended (grafted head) meshes,
/// in append order. Empty when the attach bone is missing or the head has no
/// graftable meshes (body unchanged). The body's own meshes are precisely
/// `[0, body.meshes.size() - returned.size())` — i.e. everything *before* the
/// first returned index — which lets callers partition body vs. head materials
/// for per-region texture overrides.
std::vector<int> graft_head(Model& body, Model& head,
                            std::string_view attach_bone);

/// Function that decodes+uploads a TGA-on-disk Image into a GL Texture. The
/// default (passed as `{}` to set_base_texture) reads the file, decode_tga's
/// it, and upload_image's it with mipmaps. Injectable so the override can be
/// unit-tested with a stub uploader and no GL context.
using TgaTextureLoaderFn =
    std::function<Texture(const std::filesystem::path&)>;

/// Replace the Base texture stage of every material referenced by `mesh_indices`
/// (indices into `model.meshes`) with the texture decoded+uploaded from
/// `tga_path`. The new texture is appended once to `model.textures` and shared
/// by all targeted materials; their `StageSlot::Base` `texture_index` is
/// repointed at it. This is how a per-officer skin (a differently-NAMED .tga
/// than the one the NIF embeds, e.g. "FedRed_body.tga" vs the NIF's "body.tga")
/// actually overrides the authored default — without it, all officers sharing a
/// body NIF render with the same baked-in skin.
///
/// `loader` (empty -> the default: read_file + decode_tga + upload_image) lets
/// callers inject a stub for CPU-only tests. Returns true if the override was
/// applied. Returns false WITHOUT mutating the model when `tga_path` is empty,
/// missing, or fails to load (a warning is logged to stderr), or when none of
/// `mesh_indices` reference a material with a Base stage — so a bad skin path
/// safely leaves the NIF default in place.
bool set_base_texture(Model& model, std::span<const int> mesh_indices,
                      const std::filesystem::path& tga_path,
                      const TgaTextureLoaderFn& loader = {});

/// Candidate on-disk paths for an SDK-registered face-texture filename, in
/// resolution order: the literal path first, then filename-spelling variants
/// ("eyes_closed" -> "eyesclosed" / "eyes_close" — four SDK characters register
/// a "*_eyes_closed.tga" that ships nowhere; the on-disk convention is
/// "*_eyesclosed.tga", or "*_eyes_close.tga" for Brex), then the "_head"-infix
/// variant of each (the Felix/Korbus quirk). Pure — no file I/O. Never empty;
/// front() is always `path`.
std::vector<std::filesystem::path> face_texture_candidates(
    const std::filesystem::path& path);

/// Host-facing one-shot: load `body_nif` (skinned) and `head_nif` from disk
/// (each model's NIF-default textures resolved against its own NIF directory,
/// exactly like the AssetCache path), graft the head onto the body's
/// `attach_bone`, then — if a per-officer skin override is given — replace the
/// Base texture stage of the body materials with `body_tex` and of the grafted
/// head materials with `head_tex`. Returns the composed Model by value
/// (mutable, GL handles uploaded). Both models are built with keep_cpu_data so
/// cpu-walking passes (bounds, shields) keep working. Requires a current GL
/// context. Throws on NIF load/build failure.
///
/// `body_tex` / `head_tex` are per-officer skin FILE paths (e.g.
/// "…/Bodies/BodyFemS/FedFemRed_body.tga"). BC officer skins are
/// differently-NAMED files than the basename the NIF embeds ("body.tga"), so a
/// pure search-dir lookup can never select them — set_base_texture overrides
/// the loaded material's Base stage instead. An empty path leaves the NIF
/// default; a missing/unreadable path logs a warning and leaves the default.
/// The body override targets every material on the body's own (pre-graft)
/// meshes; the head override targets only the grafted head meshes.
/// `face_images` (optional): per-officer lip-sync face textures, slot name
/// ("a","e","u","blink1","blink2","eyesclosed") -> .tga path. Each is uploaded
/// into the composed model and recorded in Model::face_textures; missing/bad
/// images are warned and skipped. Also sets Model::head_mesh_begin. Empty =>
/// no face textures (lip-sync simply no-ops for that officer).
Model compose_officer_model(
    const std::filesystem::path& body_nif,
    const std::filesystem::path& body_tex,
    const std::filesystem::path& head_nif,
    const std::filesystem::path& head_tex,
    std::string_view attach_bone,
    const std::map<std::string, std::filesystem::path>& face_images = {});

}  // namespace assets
