// native/src/renderer/include/renderer/model_textures.h
#pragma once

namespace assets { struct Model; }

namespace renderer {

/// GL id of `model`'s first usable BASE-stage texture: walks `model.meshes`
/// in order, following `mesh.material_index() -> materials[i].stages[Base]
/// .texture_index -> textures[idx].id()`, and returns the first non-zero id.
/// Every index is range-checked; 0 when no mesh has one. A rock's crater
/// interior is painted with it (rock-class Task 7; HullInteriorPass).
unsigned int find_base_texture_id(const assets::Model& model);

}  // namespace renderer
