// native/src/rockgen/include/rockgen/shape.h
#pragma once

#include <assets/mesh.h>
#include <rockgen/recipe.h>

#include <vector>

namespace rockgen {

/// One MeshCpu per LOD (in `spec.kind->lod_subdivisions` order), in the glTF
/// frame, metres. LOD0 is centred with bounding radius == spec.bound_radius_m;
/// every lower LOD reuses LOD0's centre and scale, so its radius is <= the
/// bound and shared directions sit at identical positions (no popping).
/// uv via spherical parameterisation with the seam split; node_index 0,
/// material_index 0. Deterministic: byte-identical output for the same spec.
std::vector<assets::MeshCpu> generate_rock_lods(const RockSpec& spec);

/// max |p| over the mesh's vertices.
float bounding_radius(const assets::MeshCpu& m);

}  // namespace rockgen
