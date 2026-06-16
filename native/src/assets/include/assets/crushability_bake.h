// native/src/assets/include/assets/crushability_bake.h
#pragma once

#include <glm/glm.hpp>

#include <assets/mesh.h>

namespace assets {

/// Tuning for the hull-thickness crushability bake. Defaults are starting
/// points; tuned in Plan 4 against visual results.
struct CrushabilityParams {
    /// Reference thickness as a fraction of the mesh's bounding-box diagonal.
    /// A vertex whose inward hull thickness is <= thick_fraction*diag maps
    /// toward 1 (crushable); >= it maps to 0. Scale-invariant per mesh.
    float thick_fraction = 0.25f;
    /// Crushability assigned when the inward ray finds no opposite surface
    /// (open shell / grazing edge). Mid value per spec §8.
    float no_hit_value = 0.5f;
};

/// Map a hull thickness to a crushability weight in [0,1]: 0 thickness -> 1,
/// thickness >= ref -> 0, linear between. ref <= 0 returns 0 (uncrushable).
float crushability_from_thickness(float thickness, float ref);

/// Nearest forward intersection distance of the ray (origin, dir) against the
/// mesh's own triangles, searching (kTMin, max_dist]. Returns
/// +infinity if the ray hits nothing. `dir` should be unit length.
float probe_thickness(const MeshCpu& mesh, const glm::vec3& origin,
                      const glm::vec3& dir, float max_dist);

/// Bake per-vertex crushability into `mesh.vertices[*].crushability` by casting
/// each vertex's inward (-normal) ray against the mesh's own triangles and
/// mapping the nearest-hit distance (local hull thickness) to [0,1]. Vertices
/// with a zero-length normal, or whose inward ray hits nothing, get
/// params.no_hit_value. A mesh with no triangles is left unchanged.
///
/// Per-mesh approximation (see header note in the .cc): thickness is measured
/// against the vertex's own NiTriShape, not the whole ship.
void bake_crushability(MeshCpu& mesh, const CrushabilityParams& params = {});

}  // namespace assets
