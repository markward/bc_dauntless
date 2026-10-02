// native/src/rockgen/include/rockgen/impostor.h
#pragma once

#include <assets/mesh.h>
#include <assets/texture.h>
#include <rockgen/surface.h>

#include <glm/glm.hpp>

#include <vector>

namespace rockgen {

/// A 4x4-grid CPU-rasterised impostor: 16 orthographic views of one rock LOD,
/// each `view_size` square, tiled into one `(4*view_size)`-square atlas.
struct Impostor {
    assets::Image albedo;   // RGBA8; alpha = coverage (0 outside the rock's silhouette)
    assets::Image normal;   // RGBA8; RGB = view-space normal * 0.5 + 0.5, alpha = coverage
    std::vector<glm::vec3> view_dirs;   // 16, fixed (the direction the camera LOOKS FROM, glTF frame)
    int grid = 4;
    int view_size = 0;
};

/// 16 Fibonacci-sphere directions, fixed regardless of the rock.
std::vector<glm::vec3> impostor_view_dirs();

/// Rasterises `mesh` (one of `generate_rock_lods`' outputs, glTF frame,
/// metres) from each of `impostor_view_dirs()`, sampling `s.base_color` by
/// the mesh's own spherical UVs (nearest texel).
Impostor bake_impostor(const assets::MeshCpu& mesh, const RockSurface& s, int view_size);

/// One mesh of a multi-part bake.
struct ImpostorPart {
    const assets::MeshCpu* mesh;     // glTF frame, metres
    const RockSurface* surface;
    glm::mat4 xform;                 // part -> collection frame (glTF, metres)
};

/// Like bake_impostor but rasterises every part into the same 16 views (one
/// shared z-buffer per view), framed on the union's bounding sphere about the
/// origin. bake_impostor(mesh, s, n) is exactly
/// bake_impostor_parts({{&mesh, &s, identity}}, n) -- one rasteriser.
Impostor bake_impostor_parts(const std::vector<ImpostorPart>& parts, int view_size);

/// Mean RGB (0..1) of the albedo atlas, each pixel weighted by its coverage
/// (alpha). Zero when nothing is covered.
glm::vec3 impostor_avg_albedo(const Impostor& imp);

}  // namespace rockgen
