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

#include <cstdint>
#include <filesystem>
#include <glm/glm.hpp>
#include <string>
#include <vector>

namespace assets::gltf {

inline constexpr float kMetresToModelUnits = 1.0f / 1.75f;

/// Map a glTF-frame vector into BC's frame. No unit conversion -- callers
/// scale separately (positions by kMetresToModelUnits * scale; normals are
/// direction-only and never scaled).
glm::vec3 to_bc_frame(glm::vec3 v_gltf);

/// A material's image, either an external file (`path` set, `bytes` empty)
/// or embedded in the glTF itself -- a `.glb` binary-chunk buffer view or a
/// base64 `data:` URI (`bytes` set, `path` empty). `key` is the dedupe key
/// build_model_from_gltf uses to avoid decoding/uploading the same image
/// twice: `path.string()` for an external image, or
/// `"<gltf path>#image<N>"` (N = the image's index in the glTF) when
/// embedded.
struct CpuImage {
    std::filesystem::path path;
    std::vector<std::uint8_t> bytes;
    std::string key;
    bool empty() const { return path.empty() && bytes.empty(); }
};

struct CpuMaterial {
    glm::vec4 base_color_factor{1.0f};
    CpuImage base_color_image;
    CpuImage normal_image;
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
