// native/src/renderer/sphere_mesh.h
#pragma once

#include <assets/mesh.h>

namespace renderer {

/// Build an inside-facing UV sphere with approximately `target_tris`
/// triangles. The sphere's vertices lie on the unit sphere (radius 1);
/// callers scale via the world matrix or simply rely on the skybox-depth
/// idiom in the vertex shader, which makes radius cosmetic.
///
/// Triangulation: lat × lon segments split 1:2 so target_tris=256
/// produces 8 lat × 16 lon segments = 128 quads = 256 tris.
///
/// Winding: clockwise from outside the sphere. Combined with this
/// project's `glFrontFace(GL_CW)` convention and back-face culling, the
/// sphere's *interior* renders front-facing — which is what we want for
/// a skybox seen from inside.
///
/// UV layout: u = lon / (2π) ∈ [0,1], v = (lat + π/2) / π ∈ [0,1].
/// Texture stretching at the poles is acceptable for BC's stars.tga.
assets::MeshCpu build_uv_sphere(int target_tris);

}  // namespace renderer
