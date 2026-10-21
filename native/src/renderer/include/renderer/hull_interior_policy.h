// native/src/renderer/include/renderer/hull_interior_policy.h
//
// Layered hull damage, phase 2 (spec 2026-10-21-layered-hull-damage-production
// goal 3): which hulls get rooms behind their holes in THIS render. A near
// hull's holes are cut, stencil-marked and filled with decks and rooms by
// FrameSubmitter::submit_plating_interior; a far hull's holes are painted in
// place as wreckage by the plating shader (u_plating_far), with no marking
// and no interior draw. A hole blown clear through (deck break) is cut at
// any distance.
#pragma once

#include <optional>

#include <scenegraph/instance.h>

namespace scenegraph { struct Camera; }

namespace renderer {

struct InteriorPolicy {
    float near_gu = 20.0f;                 // rooms only within this many GU of the camera
    bool viewscreen = false;               // this render is the bridge viewscreen feed
    std::optional<scenegraph::InstanceId> viewscreen_target;  // its target, if any
};

// Near = rooms for this instance in this render. Distance is from the camera
// eye to the instance's bounding sphere surface (model bounding radius x scale),
// render space. On the viewscreen only the target can be near, at any distance.
bool interior_is_near(const scenegraph::Instance& inst, float model_radius,
                      const scenegraph::Camera& camera, const InteriorPolicy& policy);

}  // namespace renderer
