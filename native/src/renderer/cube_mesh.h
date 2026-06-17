// native/src/renderer/cube_mesh.h
#pragma once
#include <assets/mesh.h>

namespace renderer {

/// Build a unit cube with 24 unique vertices (4 per face, distinct normals per
/// face). Positions in [-0.5, 0.5]. Matches assets::MeshCpu::Vertex layout
/// (position, normal, uv, color=white, bone fields=0).
assets::MeshCpu build_unit_cube();

} // namespace renderer
