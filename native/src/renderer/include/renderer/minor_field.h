// native/src/renderer/include/renderer/minor_field.h
// Minor rocks (docs/superpowers/specs/2026-10-01-minor-rocks-design.md, §1, §2).
#pragma once

#include <cstdint>
#include <vector>

#include <glm/glm.hpp>

namespace renderer::minors {

enum class Anchor : std::uint8_t { Instance, Point, Free };

struct DebrisSpec {            // a breakup minor (Free clouds only)
    glm::vec3 offset{0.0f};    // GU, relative to the cloud anchor at t0
    glm::vec3 v0{0.0f};        // GU/s outward, decays (debris_damp_seconds)
    float radius = 0.1f;       // GU
    std::uint32_t seed = 0;
};

struct CloudDesc {
    std::uint32_t id = 0;
    Anchor anchor = Anchor::Point;
    std::uint64_t instance_key = 0;      // Anchor::Instance: (index<<32)|generation
    glm::dvec3 point{0.0};               // VIEW space: Point position / Free p0
    glm::vec3 velocity{0.0f};            // Free: GU/s
    double t0 = 0.0;                     // Free: game time of p0
    float shell_inner = 0.0f, shell_outer = 1.0f, falloff = 0.0f;
    int count = 0;
    float r_min = 0.05f, r_max = 0.5f, size_exponent = 2.5f;
    int family = 0;
    std::uint32_t seed = 0;
    float orbit_rate = 0.0f;             // rad/s
    bool fade_in = false;
    std::vector<DebrisSpec> debris;
};

struct Minor {                 // one generated instance (immutable after build)
    glm::vec3 offset{0.0f};    // cloud-local GU (orbit/halo/tile); debris: start
    glm::vec3 v0{0.0f};        // debris only
    float radius = 0.1f;       // GU
    glm::vec3 tumble_axis{0.0f, 0.0f, 1.0f};
    float tumble_u = 0.0f;     // [0,1): rate = mix(tumble_min, tumble_max, u)
    float phase = 0.0f;        // initial rotation angle, radians
    float orbit_u = 1.0f;      // [0.5,1]: orbit rate factor
    std::uint32_t mesh_u = 0;  // mesh slot = mesh_u % fragment count
    bool debris = false;
};

std::vector<Minor> generate(const CloudDesc& d);   // deterministic, pure

}  // namespace renderer::minors
