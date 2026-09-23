// native/src/renderer/include/renderer/model_draw_helpers.h
#pragma once

#include <glm/glm.hpp>

#include <unordered_map>

namespace assets { struct Model; }

namespace renderer {

class Shader;

/// Walk `model`'s node hierarchy and draw every mesh's raw geometry (POSITION
/// ONLY -- `prog`'s own `a_pos` attribute, whatever it does with it) with
/// `u_model` set to that mesh's own composed node-world transform (parent
/// local transforms chained, exactly as draw_model in frame.cc composes them
/// for the full material/lighting draw -- the two must produce IDENTICAL
/// per-mesh transforms, or a caller relying on this for stencil/geometry
/// alignment against the opaque pass's own draw would silently drift).
///
/// Sets ONLY `u_model` per mesh; `prog` must already have every other
/// uniform it needs (view/proj, and whatever else its own vertex/fragment
/// stages read) set by the caller before this runs. No material, texture,
/// skinning, decal, glow, or carve-sphere state is touched -- callers that
/// need any of that want `draw_model` (frame.cc) instead.
///
/// Shared between `submit_shadow_depth` (frame.cc, depth-only shadow-map
/// pass) and `BreachPass` (breach_pass.cc, raymarched-breach-interior Task 3
/// round 3: draws the REAL hull mesh under the carve stencil so each
/// fragment starts exactly at the surface point the carve actually touched,
/// rather than searching a proxy box for one) -- previously duplicated as
/// frame.cc's file-local `draw_model_depth_only`; promoted here specifically
/// so a second caller does not silently drift from the first.
///
/// `node_overrides` (nullptr or empty = none) replaces individual nodes' local
/// transforms, so an articulated or severed part casts the shadow it actually
/// has rather than its rest-pose one. Empty takes a walk byte-identical to the
/// static one.
void draw_model_positions_only(const assets::Model& model,
                               const glm::mat4& world,
                               Shader& prog,
                               const std::unordered_map<int, glm::mat4>*
                                   node_overrides = nullptr);

}  // namespace renderer
