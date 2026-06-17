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
/// Winding: clockwise from outside the sphere. With this project's
/// `glFrontFace(GL_CW)` convention, the exterior faces are "front" by GL's
/// definition. Both users (backdrop_pass.cc for the skybox, breach_pass.cc
/// for the scoop interior) call `glCullFace(GL_FRONT)` to draw only the inner
/// wall (back faces from outside = the face seen from inside the sphere).
///
/// UV layout: u = lon / (2π) ∈ [0,1], v = (lat + π/2) / π ∈ [0,1].
/// Texture stretching at the poles is acceptable for BC's stars.tga.
assets::MeshCpu build_uv_sphere(int target_tris);

}  // namespace renderer
