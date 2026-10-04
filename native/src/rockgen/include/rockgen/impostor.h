// native/src/rockgen/include/rockgen/impostor.h
#pragma once

#include <assets/mesh.h>
#include <assets/texture.h>
#include <rockgen/surface.h>

#include <glm/glm.hpp>

#include <vector>

namespace rockgen {

/// Views per atlas side (rock-blend, 2026-10-03: 8x8, was 4x4 Fibonacci).
inline constexpr int kImpostorGrid = 8;

/// An 8x8-grid CPU-rasterised impostor: 64 orthographic views of one rock LOD,
/// each `view_size` square, tiled into one `(8*view_size)`-square atlas;
/// view v in cell (v % 8, v / 8).
struct Impostor {
    assets::Image albedo;   // RGBA8; alpha = coverage (0 outside the rock's silhouette)
    assets::Image normal;   // RGBA8; RGB = view-space normal * 0.5 + 0.5, alpha = coverage
    std::vector<glm::vec3> view_dirs;   // 64, fixed (the direction the camera LOOKS FROM, glTF frame)
    int grid = kImpostorGrid;
    int view_size = 0;
};

/// 64 fixed directions, regardless of the rock: the corner-sampled points of
/// an 8x8 octahedral map (glTF frame, pole axis +y), view v = j*8 + i at oct
/// ((2i-7)/7, (2j-7)/7). The border views fold onto each other in mirror
/// pairs with bit-identical directions (49 distinct), which lets the renderer
/// blend the 3 views of the grid triangle around any eye with no search
/// (renderer::far::view_blend; the layout is copied there, not linked).
std::vector<glm::vec3> impostor_view_dirs();

/// Rasterises `mesh` (one of `generate_rock_lods`' outputs, glTF frame,
/// metres) from each of `impostor_view_dirs()`, sampling `s.base_color` by
/// the mesh's own spherical UVs (nearest texel).
Impostor bake_impostor(const assets::MeshCpu& mesh, const RockSurface& s, int view_size);

/// One mesh of a multi-part bake.
struct ImpostorPart {
    const assets::MeshCpu* mesh;     // glTF frame, metres
    const RockSurface* surface;
    glm::mat4 xform;                 // part -> bake frame (glTF, metres)
};

/// Like bake_impostor but rasterises every part into the same 64 views (one
/// shared z-buffer per view), framed on the union's bounding sphere about the
/// origin. bake_impostor(mesh, s, n) is exactly
/// bake_impostor_parts({{&mesh, &s, identity}}, n) -- one rasteriser.
Impostor bake_impostor_parts(const std::vector<ImpostorPart>& parts, int view_size);

}  // namespace rockgen
