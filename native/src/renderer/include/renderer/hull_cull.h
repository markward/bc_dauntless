// native/src/renderer/include/renderer/hull_cull.h
// Phase 5a: skip a hull whose bounding sphere is wholly outside the drawing
// camera's frustum (opaque submit, every camera) or the shadow light's
// (shadow casters). Plan: docs/superpowers/plans/2026-11-05-native-motion-phase5a-cheap-wins.md
#pragma once
#include <glm/glm.hpp>
#include <renderer/frustum.h>

namespace renderer {

/// Radius multiplier on the rest-pose bound. A small margin for rounding.
inline constexpr float kHullCullSlack = 1.05f;
/// A rigged hull's parts move (articulation) and may leave the rest-pose
/// bound, so its sphere is doubled: drawing a few off-screen hulls is cheap,
/// popping a swung nacelle at the screen edge is not.
inline constexpr float kHullCullSlackRigged = 2.0f;

/// DAUNTLESS_HULL_CULL, read once: on unless it is exactly "0" (the A/B
/// switch; off = every hull is submitted, as before phase 5a).
bool hull_cull_enabled();

/// False only when the hull's bounding sphere -- `center_body` / `radius_body`
/// in the model frame, through `world` (uniform scale from column 0), times
/// the slack -- lies wholly outside a plane of `frustum`. An uncullable model
/// (a mesh with no bound) is always visible.
bool hull_visible(const Frustum& frustum, const glm::mat4& world,
                  const glm::vec3& center_body, float radius_body,
                  bool cullable, bool rigged);

}  // namespace renderer
