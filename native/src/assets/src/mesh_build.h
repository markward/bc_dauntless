// native/src/assets/src/mesh_build.h
#pragma once

#include <assets/mesh.h>
#include <nif/block.h>

#include <glm/glm.hpp>

namespace assets::detail {

/// Build a MeshCpu from a NiTriShape and its referenced NiTriShapeData.
/// `material_index` and `node_index` are stamped into the output.
///
/// `extra_model_transform` (SP2) is applied to vertex positions (and its
/// rotation to normals) after the node-local bake. Callers pass the parent
/// node's bind-world transform for RIGID character shapes so their verts move
/// from node-local into bind-model space (the space the GPU bone palette
/// poses). Identity (the default) leaves ships and bridges byte-identical.
MeshCpu build_mesh_cpu(
    const nif::NiTriShape& shape,
    const nif::NiTriShapeData& data,
    int material_index,
    int node_index,
    const glm::mat4& extra_model_transform = glm::mat4(1.0f));

}  // namespace assets::detail
