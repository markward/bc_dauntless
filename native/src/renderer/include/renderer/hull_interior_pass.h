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
    /// depth LEQUAL with writes on, colour writes on, blend off; fill on unit
    /// 0. Leaves stencil test off, stencil mask 0xFF, depth func GL_LESS and
    /// texture unit 0 active.
    ///
    /// `deck_break` (plating::deck_break_subset of `list`) is uploaded as
    /// u_db_count / u_db_idx: the walk's blown tests read only those records,
    /// while its shading (soot, room light, char edge) reads all of `list`.
    void draw(const assets::Model& model, const glm::mat4& world_xf,
              const scenegraph::Camera& camera, Pipeline& pipeline,
              const plating::DamageList& list, const plating::DeckBreakSet& deck_break,
              const float* params,
              unsigned int fill_tex, const glm::vec3& fill_origin,
              const glm::vec3& fill_cell, const glm::ivec3& fill_dims,
              const Lighting& lighting, float ambient_scale, float now,
              int stencil_value,
              const std::unordered_map<int, glm::mat4>* node_overrides);

    /// draw() calls since construction.
    int draw_calls() const { return draw_calls_; }

private:
    int draw_calls_ = 0;
};

}  // namespace renderer
