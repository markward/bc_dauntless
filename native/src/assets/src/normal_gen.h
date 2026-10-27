// native/src/assets/src/normal_gen.h
#pragma once

#include <assets/mesh.h>
#include <nif/block.h>

#include <glm/glm.hpp>

#include <cstdint>
#include <vector>

namespace assets::detail {

/// Crease angle for generated interior-set normals (spec
/// docs/superpowers/specs/2026-10-08-bridge-lighting-baseline-design.md §3).
/// Mirrored in renderer/bridge_lighting_tuning.h's comment.
inline constexpr float kSetNormalCreaseDeg = 40.0f;

/// One shape handed to joint normal generation.
struct NormalGenShape {
    MeshCpu*               mesh = nullptr;      // edited in place
    glm::mat4              to_model{1.0f};      // shape frame -> model space
    std::vector<glm::vec4> source_colours;      // NIF float colours, parallel to mesh->vertices; may be empty
    // Blender-authored hard/soft edges (a mesh fix's smoothing record), as
    // indices into `mesh->vertices` as given. nullptr: no record, every edge
    // follows the crease. A record with no edges still makes the shape
    // "recorded" (spec 2026-10-27-bridge-authored-smoothing-design.md §3.2).
    const nif::AuthoredEdges* authored = nullptr;
};

/// What normal generation made of each authored edge, for the shape-diff
/// verifier: one row per edge, shapes in input order, each shape's hard edges
/// then its soft edges in record order. `shape` indexes the input vector.
struct SmoothingReport {
    struct Edge {
        std::uint32_t shape;
        std::uint16_t a, b;
        bool found;     // the edge (or the piece of it at each end) has exactly two faces of its shape
        bool joined_a;  // those two faces' corners at a share one normal
        bool joined_b;  // ... at b
    };
    std::vector<Edge> edges;
};

/// Remove T-junctions: wherever a vertex POSITION lies strictly inside
/// another triangle's edge, split that triangle there. The inserted vertex
/// interpolates the split triangle's own attributes along the edge (UVs,
/// colour, extra UVs, and `source_colours` when it is parallel to the
/// vertices), so its texture mapping is unchanged. Run before
/// generate_smooth_normals: an unsplit T-junction both blocks smoothing (no
/// shared edge) and kinks the shading (the long edge interpolates past a
/// vertex its neighbours light by).
void repair_t_junctions(MeshCpu& mesh, std::vector<glm::vec4>& source_colours);

/// Generate per-vertex normals for a mesh authored without any (BC's Fed
/// bridge NIFs: zero normals, zero match groups).
///
/// Rule (docs/superpowers/specs/2026-10-08-bridge-lighting-baseline-design.md §3):
///  - vertices are welded by POSITION, so edges match whether or not the
///    triangles share indices (EBridge is close to a triangle soup);
///  - faces around a welded position form one smoothing group when they are
///    chained through shared EDGES each folded less than `crease_deg`, so the
///    normal is exactly continuous across every smooth edge;
///  - winding is mixed: a neighbour that walks the shared edge in the same
///    direction is flipped, which the fold test and the sum account for;
///  - two distinct vertices at one position with IDENTICAL attributes (UV
///    sets, source float colour) are an exporter hard-edge split and are never
///    joined. A split explained by a UV or colour change says nothing about
///    smoothing and is ignored.
/// Contributions are weighted by face area, so a large face keeps its own
/// corners flat beside a small bevel. Vertices whose corners disagree are
/// split (extra_uvs duplicated alongside), so `vertices` may grow.
///
/// `source_colours`, when non-empty, holds the shape's original float vertex
/// colours (parallel to `mesh.vertices`); the hard-edge twin test compares
/// those instead of the 8-bit `Vertex::color`.
void generate_smooth_normals(MeshCpu& mesh, float crease_deg,
                             const std::vector<glm::vec4>& source_colours = {});

/// Generate normals jointly across `shapes`, in model space (each shape's
/// `to_model`), so seams between shapes smooth like any edge. T-junctions are
/// repaired across shapes too. Each shape keeps its own vertices, positions
/// (in its own frame), attributes and extra-UV channel count; only the
/// normals (rotated back into the shape's frame) and any split/inserted
/// vertices change. Generation sees only the shapes it is given — the caller
/// decides which shapes need normals.
///
/// Authored edges (spec 2026-10-27-bridge-authored-smoothing-design.md §3.3):
/// between two faces of one shape that has a record, a listed hard edge never
/// joins and a listed soft edge always joins (whatever the fold, despite a
/// twin split); pieces the T-junction repair cut from a listed edge inherit
/// its flag; unlisted edges keep the crease rule. Corners an authored hard
/// edge separates never end up in one group, whatever chain of other joins
/// reaches them. `authored_joins_hard` (§3.4) makes every edge between two
/// different shapes, at least one recorded, a hard edge. `report`, when
/// given, is overwritten with the outcome per authored edge.
void generate_normals_across_shapes(std::vector<NormalGenShape>& shapes, float crease_deg,
                                    SmoothingReport* report = nullptr,
                                    bool authored_joins_hard = false);

}  // namespace assets::detail
