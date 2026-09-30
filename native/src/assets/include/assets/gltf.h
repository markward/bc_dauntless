// native/src/assets/include/assets/gltf.h
//
// GL-free glTF 2.0 reader (via cgltf), producing CPU-side data in BC's frame
// and BC model units. Never touches GL; callers upload via assets::upload_mesh
// / assets::Texture as usual.
//
// Conventions (see docs/superpowers/sdd/2026-09-30-rock-catalogue/constraints.md):
//   - 1 glTF unit = 1 metre.
//   - 1 BC model unit = 1.75 m, so kMetresToModelUnits = 1 / 1.75.
//   - Axis map (x, y, z)_gltf -> (-x, z, y)_BC. det +1: winding is preserved.
#pragma once

#include <assets/mesh.h>

#include <filesystem>
#include <glm/glm.hpp>
#include <vector>

namespace assets::gltf {

inline constexpr float kMetresToModelUnits = 1.0f / 1.75f;

/// Map a glTF-frame vector into BC's frame. No unit conversion -- callers
/// scale separately (positions by kMetresToModelUnits * scale; normals are
/// direction-only and never scaled).
glm::vec3 to_bc_frame(glm::vec3 v_gltf);

struct CpuMaterial {
    glm::vec4 base_color_factor{1.0f};
    std::filesystem::path base_color_image;  // absolute; empty if none
    std::filesystem::path normal_image;      // absolute; empty if none
};

struct CpuScene {
    // BC frame, model units x scale, node transforms baked; node_index = 0,
    // material_index into materials (-1 if none).
    std::vector<MeshCpu> meshes;
    std::vector<CpuMaterial> materials;
    std::filesystem::path volume;  // absolute path from asset.extras.dauntless_volume, or empty
};

/// Load `path` (a .gltf or .glb file) into CPU-side data, baking node
/// transforms and applying `scale` on top of kMetresToModelUnits. Throws
/// assets::AssetError on any parse/validate/read failure or unsupported
/// primitive.
CpuScene load_cpu(const std::filesystem::path& path, float scale = 1.0f);

}  // namespace assets::gltf
