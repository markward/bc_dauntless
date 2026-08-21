// native/src/renderer/include/renderer/aabb.h
#pragma once

#include <array>
#include <span>
#include <vector>
#include <glm/glm.hpp>

namespace assets { struct Model; }

namespace renderer {

struct Aabb {
    glm::vec3 center{0.0f};
    glm::vec3 half_extents{0.0f};
};

Aabb compute_aabb(std::span<const glm::vec3> positions);

inline Aabb compute_aabb(const std::vector<glm::vec3>& v) {
    return compute_aabb(std::span<const glm::vec3>(v));
}

/// AABB of every CPU-data mesh vertex in `model`, transformed into
/// model-local space via the node hierarchy (per-mesh local_transform
/// chained from root). Meshes whose nodes are unreachable or that lack
/// cpu_data are skipped.
Aabb compute_model_aabb(const assets::Model& model);

/// One hull piece, in model-local space.
struct BoundSphere {
    glm::vec3 center{0.0f};
    float radius = 0.0f;
};

/// Ceiling on the pieces one model may yield. Every piece is a sphere the
/// Python narrow phase and collision_avoidance iterate per tick, and the
/// narrow phase is a product of both hulls' counts, so this bounds a cost that
/// would otherwise scale with triangle count.
///
/// 128 is where the returns stop, measured on FedStarbase with
/// `dump_bounds -p -gu -q`: the largest piece falls 161 -> 45 -> 37 GU across
/// 1 / 64 / 128 leaves, and 256 buys another 6 GU for twice the per-tick cost.
/// The floor under it is kMinHullBoundLeafTriangles, not this.
inline constexpr int kMaxHullBoundLeaves = 128;

/// Stop splitting a leaf holding this few triangles. Below it the leaf is
/// already small enough that its sphere's slack is negligible in absolute
/// terms, which is the whole reason spheres remain viable as the primitive.
inline constexpr int kMinHullBoundLeafTriangles = 24;

/// `tris` decomposed into hull pieces by median-splitting the soup along the
/// longest axis of its centroid spread, bounding each leaf with a sphere.
/// Split order and leaf contents are a pure function of the input, so the
/// offline tool (native/tools/dump_bounds) measures exactly what ships.
std::vector<BoundSphere> compute_bounds_from_triangles(
    std::span<const std::array<glm::vec3, 3>> tris);

/// `model` decomposed into hull pieces: a spatial split of its triangle soup,
/// each leaf bounded by a sphere, in model-local space (vertices composed
/// through the node hierarchy exactly as compute_model_aabb composes them).
///
/// A single model-wide sphere or AABB cannot express a CONCAVE hull — a
/// starbase's docking bay is a void between structures, and the volume under
/// its mushroom cap is open space the player is meant to fly into. Pieces make
/// those regions empty with no special case: they are inside none of them.
///
/// The pieces are derived from TRIANGLES rather than from the authored
/// per-NiTriShapeData bounding spheres, because neither half of that data is
/// fine enough (both measured with native/tools/dump_bounds):
///   * the authored sphere is fitted about the shape's AABB centre, so on the
///     flat plates BC hulls are built from it overstates the geometry 5-22x in
///     the thin direction — Galaxy's saucer shapes are 13 units thick inside a
///     251-unit sphere;
///   * and one bound per mesh is not one bound per piece — three of
///     FedStarbase's five shapes each span the entire station.
///
/// Meshes with no cpu_data, an unreachable node, or no triangles are skipped;
/// none of them describes a volume.
std::vector<BoundSphere> compute_model_bounds(const assets::Model& model);

}  // namespace renderer
