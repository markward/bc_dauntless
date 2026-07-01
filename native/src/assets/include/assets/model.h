// native/src/assets/include/assets/model.h
#pragma once

#include <filesystem>
#include <string>
#include <unordered_map>
#include <vector>

#include <glm/glm.hpp>

#include <assets/animation.h>
#include <assets/material.h>
#include <assets/mesh.h>
#include <assets/skeleton.h>
#include <assets/texture.h>

namespace assets {

/// A BC `ObjectClass::ReplaceTexture(new, old)` request, baked into a model at
/// build time to render a Federation ship's registry / hull-name. `old_substring`
/// is matched (CASE-SENSITIVE — BC's "ID" tag is uppercase, and a case-fold would
/// also hit "...Bridge...") against each NIF texture's embedded basename;
/// `new_texture` is the replacement TGA, resolved by basename against the
/// model's texture search dirs (case-insensitive) exactly like the NIF's own
/// textures — so a BC-style path that omits the LOD subdir
/// ("FedShips/Dauntless.tga" for a file really in FedShips/High/) still resolves.
/// Participates in the AssetCache key so each distinct registry yields a distinct
/// model variant while same-registry hulls still share one. See model_build.cc
/// `apply_texture_replacements`.
struct TextureReplacement {
    std::string old_substring;
    std::string new_texture;
};

struct Node {
    std::string       name;
    int               parent_index = -1;
    glm::mat4         local_transform{1.0f};
    std::vector<int>  children;
    std::vector<int>  meshes;
};

/// Per-NiFlipController texture animation. `texture_indices` lists the
/// frames (indices into Model::textures) in cycle order. `delta` is
/// seconds per frame. The renderer pairs this with a wall time via
/// assets::compute_flip_frame_index to pick the active frame each draw.
struct TextureAnimation {
    std::vector<int> texture_indices;
    double           delta       = 0.0;
    double           start_time  = 0.0;
    double           frequency   = 1.0;
    double           phase       = 0.0;
};

struct Model {
    std::vector<Node>             nodes;
    int                           root_node = 0;
    std::vector<Mesh>             meshes;
    std::vector<Texture>          textures;
    std::vector<Material>         materials;
    Skeleton                      skeleton;
    std::vector<AnimationClip>    animations;
    std::vector<TextureAnimation> texture_animations;
    /// A small (~96) sample of MODEL-SPACE hull surface points, already
    /// transformed out of node-local space (node->model bake applied at load).
    /// Spread across all mesh shapes for whole-hull VFX anchoring (electrical
    /// discharges, wake). Empty for models with no meshes. ~negligible memory.
    std::vector<glm::vec3>        surface_points;
    std::filesystem::path         source;

    /// Index of the first grafted HEAD mesh in `meshes` (-1 if none). Head
    /// meshes are appended last by compose_officer_model, so the head set is
    /// [head_mesh_begin, meshes.size()). Used by the lip-sync face sink to
    /// blend only the head meshes' base texture.
    int                           head_mesh_begin = -1;
    /// Officer FACE-texture set: slot name ("a","e","u","blink1","blink2",
    /// "eyesclosed") -> index into `textures`. Populated by
    /// compose_officer_model from the character's facial images; empty for
    /// non-officer models. "neutral" is implicit (the head's own base texture).
    std::unordered_map<std::string, int> face_textures;
};

}  // namespace assets
