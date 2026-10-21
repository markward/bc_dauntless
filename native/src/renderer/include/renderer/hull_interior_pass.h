// native/src/renderer/include/renderer/hull_interior_pass.h
//
// SPIKE (damage redesign): the hull interior behind a plating cut. Decks and
// rooms, drawn by walking a body-frame room lattice from the cut hull surface
// (shaders/hull_interior.frag, ported from spike/breach-interior-mapping's
// ih_shade). FrameSubmitter::submit_plating_interior calls draw() right after
// it stamps a hull's cut pixels with its own stencil value, so the interior
// lands only inside that hull's holes.
#pragma once

#include <unordered_map>

#include <glm/glm.hpp>

#include <renderer/plating_damage.h>

namespace assets { struct Model; }
namespace scenegraph { struct Camera; }

namespace renderer {

class Pipeline;
struct Lighting;

class HullInteriorPass {
public:
    /// Draw `model`'s hull mesh through Pipeline::hull_interior_shader() where
    /// the stencil equals `stencil_value`. `params` = the kParamCount plating
    /// params (slot 24 deck break wear, 17 inner brightness, 19 tear noise).
    /// `fill_tex` 0 = no fill volume: rooms still draw, with no "left the
    /// ship" test. `now` = game clock (room flicker and pulse).
    ///
    /// GL state: stencil EQUAL stencil_value (mask 0, test only), cull back,
    /// depth LESS (+ polygon offset 1,1) with writes on, colour writes on,
    /// blend off; fill on unit 0, rock texture on unit 1. Leaves stencil test
    /// off, stencil mask 0xFF, depth func GL_LESS, units 0 and 1 unbound and
    /// texture unit 0 active.
    ///
    /// `mesh_mask` (optional, one byte per mesh): null = every mesh; else only
    /// meshes whose byte is non-zero are drawn. Returns the number of meshes
    /// drawn.
    ///
    /// `deck_break` (plating::deck_break_subset of `list`) is uploaded as
    /// u_db_count / u_db_idx: the walk's blown tests read only those records,
    /// while its shading (soot, room light, char edge) reads all of `list`.
    ///
    /// `rock` (Instance::surface_is_rock): no rooms. The ray marches the
    /// damage field from the cut to the crater wall and shades it with
    /// `rock_tex` (the rock's base texture, find_base_texture_id; 0 = none,
    /// a flat rock colour) under the scene's ambient and directional lights
    /// (u_interior_rock 1 / 2; 0 for a ship). `rock_tex` is bound on unit 1
    /// on every draw, 0 when unused, and unbound after.
    ///
    /// A posed instance (non-empty `node_overrides`) draws per FRAME group:
    /// the meshes sharing one posed owner get only the records in that
    /// frame (plating::records_in_frame) and that list's deck-break set --
    /// `deck_break` itself when every record is in the frame, else rebuilt
    /// (plating::deck_break_subset when `cull_deck_break`, else the full set),
    /// so no overlap sum mixes frames.
    ///
    /// `rims` (plating::build_rim_list; nullptr = none): the molten rims of
    /// fresh tears, uploaded as u_rim_* (per frame group when posed:
    /// plating::rims_in_frame). The plate char edge takes their heat.
    int draw(const assets::Model& model, const glm::mat4& world_xf,
              const scenegraph::Camera& camera, Pipeline& pipeline,
              const plating::DamageList& list, const plating::DeckBreakSet& deck_break,
              const float* params,
              unsigned int fill_tex, const glm::vec3& fill_origin,
              const glm::vec3& fill_cell, const glm::ivec3& fill_dims,
              const Lighting& lighting, float ambient_scale, float now,
              int stencil_value,
              const std::unordered_map<int, glm::mat4>* node_overrides,
              const std::vector<std::uint8_t>* mesh_mask = nullptr,
              bool rock = false, unsigned int rock_tex = 0,
              bool cull_deck_break = true,
              const plating::RimList* rims = nullptr);

    /// draw() calls since construction.
    int draw_calls() const { return draw_calls_; }

private:
    int draw_calls_ = 0;
};

}  // namespace renderer
