// native/src/renderer/hull_interior_policy.cc
#include <renderer/hull_interior_policy.h>

#include <scenegraph/camera.h>

#include <glm/glm.hpp>

namespace renderer {

bool interior_is_near(const scenegraph::Instance& inst, const glm::vec3& model_centre,
                      float model_radius, const scenegraph::Camera& camera,
                      const InteriorPolicy& policy) {
    if (policy.viewscreen)
        return policy.viewscreen_target.has_value() && *policy.viewscreen_target == inst.id;
    // Camera::view_matrix is lookAt(eye, ...), so the eye IS inverse(view)[3];
    // read it directly rather than invert a matrix per instance.
    const glm::vec3 centre = glm::vec3(inst.world * glm::vec4(model_centre, 1.0f));
    const float scale = glm::length(glm::vec3(inst.world[0]));
    const float to_surface = glm::length(centre - camera.eye) - model_radius * scale;
    return to_surface <= policy.near_gu;
}

}  // namespace renderer
