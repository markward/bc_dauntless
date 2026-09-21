// native/src/renderer/include/renderer/scuff_panels.h
#pragma once

#include <cstddef>
#include <cstdint>

namespace assets { struct Model; }

namespace renderer {

/// Per-mesh buffer texture of one unit vector per TRIANGLE: the triangle's
/// longest-edge direction in the model (body) frame, node transforms
/// composed, sign canonicalised so parallel edges on neighbouring triangles
/// agree. The collision-scuff pass (opaque.frag: apply_scuffs) reads it by
/// gl_PrimitiveID to orient the crumple-panel grid along the hull's own
/// edges -- on a saucer wedge that is radial + concentric, like the plating
/// (live pass 2026-09-21, from a mockup).
///
/// Built lazily from the mesh's retained CPU data on first use and cached
/// for the process; returns 0 when the mesh kept no CPU data (then the
/// shader falls back to a body-X-aligned grid). gl_PrimitiveID counts per
/// draw call, which is per MESH, so the texture is per mesh, not per model.
std::uint32_t scuff_tri_dir_texture(const assets::Model& model,
                                    std::size_t node_index, int mesh_index);

/// Drop every cached texture (GL context teardown / tests).
void reset_scuff_tri_dir_cache();

}  // namespace renderer
