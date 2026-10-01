// native/src/renderer/include/renderer/speck.h
// Far tier speck instance (docs/superpowers/specs/2026-10-01-far-tier-design.md §3).
#pragma once
#include <glm/glm.hpp>

namespace renderer {

// One point-sprite rock. pos is render space; p_px the on-screen radius in
// framebuffer pixels; alpha the tier weight (speck share of the ladder).
struct SpeckGpu {
    glm::vec3 pos;
    float p_px;
    glm::vec3 albedo;
    float alpha;
};
static_assert(sizeof(SpeckGpu) == 32, "SpeckGpu is a 32-byte GPU instance");

}  // namespace renderer
