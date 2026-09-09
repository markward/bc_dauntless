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
/// Winding: COUNTER-clockwise from outside the sphere (this comment
/// previously said "clockwise" under a claimed `glFrontFace(GL_CW)`
/// convention -- both wrong: `pipeline.cc` sets `glFrontFace(GL_CCW)`, and
/// a hand signed-area check of sphere_mesh.cc's own triangle (a,b,d) at
/// theta=0,phi=0 gives CCW, not CW -- see sphere_mesh.cc's own comment for
/// the derivation). Under the actual `glFrontFace(GL_CCW)`, the exterior
/// faces are "front" by GL's definition, so users call
/// `glCullFace(GL_FRONT)` to draw only the inner wall (back faces from
/// outside = the face seen from inside the sphere): backdrop_pass.cc for
/// the skybox, sun_pass.cc, shield_pass.cc, nebula_pass.cc. (breach_pass.cc
/// used this sphere pre-Task-3 for the per-carve scoop; it draws no proxy
/// geometry of its own any more -- it re-draws the REAL hull mesh via
/// renderer::draw_model_positions_only, so it neither calls this function nor
/// builds a substitute.)
///
/// UV layout: u = lon / (2π) ∈ [0,1], v = (lat + π/2) / π ∈ [0,1].
/// Texture stretching at the poles is acceptable for BC's stars.tga.
assets::MeshCpu build_uv_sphere(int target_tris);

}  // namespace renderer
