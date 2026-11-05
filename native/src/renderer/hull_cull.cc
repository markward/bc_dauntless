// native/src/renderer/hull_cull.cc
#include <renderer/hull_cull.h>

#include <cstdlib>
#include <cstring>

namespace renderer {

bool hull_cull_enabled() {
    static const bool on = [] {
        const char* v = std::getenv("DAUNTLESS_HULL_CULL");
        return !(v != nullptr && std::strcmp(v, "0") == 0);
    }();
    return on;
}

bool hull_visible(const Frustum& frustum, const glm::mat4& world,
                  const glm::vec3& center_body, float radius_body,
                  bool cullable) {
    if (!cullable) return true;
    const glm::vec3 center_ws = glm::vec3(world * glm::vec4(center_body, 1.0f));
    const float scale = glm::length(glm::vec3(world[0]));
    const float r = radius_body * scale * kHullCullSlack;
    return frustum.sphere(center_ws, r);
}

}  // namespace renderer
