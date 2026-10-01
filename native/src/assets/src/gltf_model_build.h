// native/src/assets/src/gltf_model_build.h
//
// Build an assets::Model directly from a glTF/GLB file (rock-catalogue plan,
// Task 2) -- the glTF-loading twin of build_model (NIF, model_build.h).
#pragma once

#include <assets/model.h>

#include "model_build.h"

#include <filesystem>

namespace assets::detail {

/// Build a Model from the glTF/GLB file at `path`, applying `scale` on top
/// of assets::gltf::kMetresToModelUnits (baked into vertex positions by
/// assets::gltf::load_cpu). Unlike build_model (NIF), there is no mesh-fix,
/// texture-replacement or decal support: ctx.texture_replacements and
/// ctx.decals are ignored here -- AssetCache::load warns once if either
/// arrives non-empty for a glTF path, before calling this. Model::source is
/// assets::hull_source_string(path, scale).
Model build_model_from_gltf(const std::filesystem::path& path, float scale,
                             const ModelBuildContext& ctx);

}  // namespace assets::detail
