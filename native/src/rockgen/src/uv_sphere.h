// native/src/rockgen/src/uv_sphere.h
#pragma once

// Shared unit-direction <-> spherical-UV mapping. shape.cc's mesh UVs and
// surface.cc/impostor.cc's texel sampling must agree exactly, so both go
// through this one pair of functions instead of two independently-derived
// copies of the same formula.
#include <glm/glm.hpp>

#include <cmath>

namespace rockgen::detail {

constexpr float kUvPi = 3.14159265358979323846f;

/// Equirectangular UV of a unit direction: u wraps around the sphere's
/// east-west (longitude) axis, v runs pole to pole (latitude).
inline glm::vec2 direction_to_uv(const glm::vec3& n) {
    return glm::vec2(std::atan2(n.z, n.x) / (2.0f * kUvPi) + 0.5f,
                     std::asin(glm::clamp(n.y, -1.0f, 1.0f)) / kUvPi + 0.5f);
}

/// Inverse of direction_to_uv: the unit direction sampled at (u, v).
inline glm::vec3 uv_to_direction(float u, float v) {
    const float lon = (u - 0.5f) * 2.0f * kUvPi;
    const float lat = (v - 0.5f) * kUvPi;
    return glm::vec3(std::cos(lat) * std::cos(lon),
                     std::sin(lat),
                     std::cos(lat) * std::sin(lon));
}

}  // namespace rockgen::detail
