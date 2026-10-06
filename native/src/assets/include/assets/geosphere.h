// native/src/assets/include/assets/geosphere.h
//
// Planet geosphere (spec docs/superpowers/specs/2026-10-06-planet-geosphere-design.md).
// Pure, GL-free: the icosphere LOD meshes that replace BC's 673-vertex planet
// sphere, BC's measured equirectangular mapping, and the per-camera LOD pick.
#pragma once

#include <array>
#include <functional>

#include <glm/glm.hpp>

#include <assets/mesh.h>
#include <assets/model.h>

namespace assets {

/// Subdivision levels of the four LODs, coarse to fine. Level 3 (1,280 tris)
/// matches BC's planet mesh, so the coarsest LOD is never worse than today.
inline constexpr std::array<int, 4> kGeosphereLevels{3, 4, 5, 6};

/// Icosphere of 20*4^level triangles, CCW seen from outside, every vertex at
/// `radius` from `center`. Normal = unit direction from center; uv =
/// sphere_uv(normal) (a fallback for programs that ignore u_sphere_map --
/// it wraps across the seam, which is why opaque.frag never reads it).
MeshCpu build_geosphere(int level, float radius, glm::vec3 center = glm::vec3(0.0f));

/// BC's planet mapping, measured on all 31 stock planet NIFs (spec §2):
/// u = fract(atan2(y,x)/2pi + 0.75), v = 0.5 - asin(z)/pi, Z-up, seam at +Y.
/// Finite at the poles (u = 0.75 there).
glm::vec2 sphere_uv(glm::vec3 unit_dir);

/// Index into kGeosphereLevels: the coarsest level whose silhouette sagitta,
/// R*theta^2/8 projected at the silhouette distance sqrt(d^2-R^2), is under
/// max_err_px. theta = 63.435deg / 2^level (icosphere mean edge angle).
/// d <= R, or no level meeting the bound, gives the finest index (3).
int pick_geosphere_level(float world_radius, float center_distance,
                         float focal_px, float max_err_px = 0.5f);

/// Build `model.sphere_map` from its single mesh, if that mesh passes the
/// sphere gate (spec §4.2): a UV set, and every vertex within 0.5% of the
/// mean distance from the centroid, measured in the mesh's own vertex
/// frame. `upload` builds each LOD's GPU mesh (production: upload_mesh;
/// tests: a stub uploader); `keep_cpu_data` mirrors AssetCache::Config and
/// controls whether each LOD's Mesh retains its MeshCpu for inspection.
/// Mutates `model` only on success; returns whether the gate passed. Must
/// run on a non-const Model during construction, before it is published as
/// shared_ptr<const Model> (see Model::trace_accel's construction-time
/// mutation contract, model.h).
bool apply_geosphere(Model& model, const std::function<Mesh(MeshCpu)>& upload,
                     bool keep_cpu_data);

}  // namespace assets
