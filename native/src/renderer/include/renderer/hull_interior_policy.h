// native/src/renderer/include/renderer/hull_interior_policy.h
//
// Layered hull damage, phase 2 (spec 2026-10-21-layered-hull-damage-production
// goal 3): which hulls get rooms behind their holes in THIS render. A near
// hull's holes are cut, stencil-marked and filled with decks and rooms by
// FrameSubmitter::submit_plating_interior; a far hull's holes are painted in
// place as wreckage by the plating shader (u_plating_far), with no marking
// and no interior draw. A far hull is never see-through: even a hole blown
// clear through (deck break) is painted, not cut (Mark, 2026-10-22).
#pragma once

#include <optional>

#include <glm/glm.hpp>

#include <scenegraph/instance.h>

namespace scenegraph { struct Camera; }

namespace renderer {

struct InteriorPolicy {
    float near_gu = 20.0f;                 // rooms only within this many GU of the camera
    bool viewscreen = false;               // this render is the bridge viewscreen feed
    std::optional<scenegraph::InstanceId> viewscreen_target;  // its target, if any
};

// Near = rooms for this instance in this render. Distance is from the camera
// eye to the instance's bounding sphere surface, render space: the sphere is
// centred on `model_centre` (the model's box centre, body frame) carried
// through inst.world, radius `model_radius` (the box half-diagonal) x scale.
// On the viewscreen only the target can be near, at any distance.
bool interior_is_near(const scenegraph::Instance& inst, const glm::vec3& model_centre,
                      float model_radius, const scenegraph::Camera& camera,
                      const InteriorPolicy& policy);

}  // namespace renderer
