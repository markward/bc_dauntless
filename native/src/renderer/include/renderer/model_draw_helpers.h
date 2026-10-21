// native/src/renderer/include/renderer/model_draw_helpers.h
#pragma once

#include <glm/glm.hpp>

#include <cstdint>
#include <unordered_map>
#include <vector>

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
/// skinning, decal or glow state is touched -- callers that need any of
/// that want `draw_model` (frame.cc) instead.
///
/// Shared between `submit_shadow_depth` (frame.cc, depth-only shadow-map
/// pass) and `HullInteriorPass` (hull_interior_pass.cc: draws the REAL hull
/// mesh under the plating mark's stencil, so each fragment starts exactly at
/// the cut surface point) -- previously duplicated as frame.cc's file-local
/// `draw_model_depth_only`; promoted here specifically so a second caller
/// does not silently drift from the first.
///
/// `node_overrides` (nullptr or empty = none) replaces individual nodes' local
/// transforms, so an articulated or severed part casts the shadow it actually
/// has rather than its rest-pose one. Empty takes a walk byte-identical to the
/// static one.
///
/// `mesh_mask` (nullptr = every mesh): one entry per model.meshes; a mesh
/// whose entry is 0 is not drawn (an index past the end is drawn). Returns
/// how many meshes were drawn.
///
/// `rest_fix`: also set `u_node_rest_fix` per mesh -- node_anim.h's
/// rest_corrections for `node_overrides`, identity on every mesh without
/// overrides -- for a program that works in the REST frame (the hull
/// interior: its damage records and fill are rest-frame data). Set on every
/// mesh, identity included, so no value leaks between draws.
int draw_model_positions_only(const assets::Model& model,
                              const glm::mat4& world,
                              Shader& prog,
                              const std::unordered_map<int, glm::mat4>*
                                  node_overrides = nullptr,
                              const std::vector<std::uint8_t>* mesh_mask = nullptr,
                              bool rest_fix = false);

}  // namespace renderer
