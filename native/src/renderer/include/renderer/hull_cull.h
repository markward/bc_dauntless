// native/src/renderer/include/renderer/hull_cull.h
// Phase 5a: skip a hull whose bounding sphere is wholly outside the drawing
// camera's frustum (opaque submit, every camera) or the shadow light's
// (shadow casters). Plan: docs/superpowers/plans/2026-11-05-native-motion-phase5a-cheap-wins.md
#pragma once
#include <glm/glm.hpp>
#include <renderer/frustum.h>

namespace renderer {

/// Radius multiplier on the rest-pose bound. A small margin for rounding.
/// A POSED hull (node overrides) is never culled at all -- the caller passes
/// cullable=false: a posed part is a full rigid transform that may move
/// arbitrarily far from the rest-pose sphere, so no slack on it is a bound.
inline constexpr float kHullCullSlack = 1.05f;

/// DAUNTLESS_HULL_CULL, read once: on unless it is exactly "0" (the A/B
/// switch; off = every hull is submitted, as before phase 5a).
bool hull_cull_enabled();

/// False only when the hull's bounding sphere -- `center_body` / `radius_body`
/// in the model frame, through `world` (uniform scale from column 0), times
/// kHullCullSlack -- lies wholly outside a plane of `frustum`. Uncullable (a
/// mesh with no bound, a skinned model, a posed hull) is always visible.
bool hull_visible(const Frustum& frustum, const glm::mat4& world,
                  const glm::vec3& center_body, float radius_body,
                  bool cullable);

}  // namespace renderer
