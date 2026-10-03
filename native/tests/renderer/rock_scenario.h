// native/tests/renderer/rock_scenario.h
// Test-only: the "Rock Fields: inside Beol 4" load (engine/dev_missions/
// rock_fields_inside.py) rebuilt in C++ for the rock-fields perf benches and
// equivalence digests -- a tile field of radius 1,000 GU with the default
// tile_haze_* noise and edge (engine/rocks/far_dials.py), the player 300 GU
// inside its edge, flying slowly toward its centre. Not an installed header.
#pragma once
#include <cmath>
#include <cstdint>
#include <cstring>
#include <vector>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <renderer/far_field.h>
#include <renderer/minor_field.h>
#include <renderer/rock_mid.h>
#include <renderer/rock_near.h>

namespace rock_scenario {

// rockgen's impostor_view_dirs(): 16 Fibonacci-sphere directions, glTF frame.
inline std::vector<glm::vec3> view_dirs16() {
    std::vector<glm::vec3> dirs;
    for (int i = 0; i < 16; ++i) {
        const float y = 1.0f - 2.0f * (static_cast<float>(i) + 0.5f) / 16.0f;
        const float r = std::sqrt(std::max(0.0f, 1.0f - y * y));
        const float phi = static_cast<float>(i) * 2.399963229728653f;
        dirs.emplace_back(std::cos(phi) * r, y, std::sin(phi) * r);
    }
    return dirs;
}

// Beol 4's "Asteroid Field 1" as density.py pushes it: a sphere with the
// tile_haze_edge_frac / tile_haze_noise_* defaults, centred at the origin.
inline renderer::far::DiscSource beol4_field() {
    renderer::far::DiscSource s;
    s.id = 7; s.seed = 4242u;
    s.shape = renderer::far::DiscSource::Shape::Sphere;
    s.procedural = false;
    s.view_space = true;
    s.sphere_radius_gu = 1000.0f;
    s.sphere_edge_frac = 0.2f;
    s.noise_scale_gu = 250.0f; s.noise_contrast = 0.8f; s.noise_octaves = 3;
    return s;
}

inline renderer::rockfield::NearCatalogue near_catalogue() {
    renderer::rockfield::NearCatalogue c;
    c.small_rocks = {20, 21, 22, 23, 24, 25, 26, 27};
    c.small_bound_mu = {57.1f, 50.0f, 55.0f, 60.0f, 52.0f, 57.1f, 49.0f, 58.0f};
    c.large_rocks = {40, 41, 42, 43};
    c.large_bound_mu = {57.1f, 61.0f, 54.0f, 57.1f};
    c.view_dirs_gltf = view_dirs16();
    return c;
}

// 48 collections: 16 per variant (sparse, medium, dense), as the host pushes.
inline std::vector<renderer::rockfield::MidCollection> mid_collections() {
    std::vector<renderer::rockfield::MidCollection> cols;
    for (int v = 0; v < 3; ++v)
        for (int i = 0; i < 16; ++i) cols.push_back({100 + v * 16 + i, v});
    return cols;
}

// A Galaxy-sized contact box (hull AABB ~3.7 x 2 x 0.9 GU) posed at `p`,
// nose along `fwd` (render space, BC +Z up).
inline renderer::minors::PlayerBox galaxy_box(const glm::vec3& p, const glm::vec3& fwd) {
    renderer::minors::PlayerBox b;
    const glm::vec3 y = glm::normalize(fwd);
    const glm::vec3 x = glm::normalize(glm::cross(y, glm::vec3(0, 0, 1)));
    const glm::vec3 z = glm::cross(x, y);
    b.world = glm::mat4(glm::vec4(x, 0), glm::vec4(y, 0), glm::vec4(z, 0), glm::vec4(p, 1));
    b.center_mu = glm::vec3(0.0f, 0.1f, -0.05f);
    b.half_mu = glm::vec3(1.0f, 1.85f, 0.45f);
    return b;
}

// The player's pose at frame `i` (60 Hz): from 700 GU off the centre
// (300 GU inside the edge) toward the centre at `gups`, weaving gently so
// every axis crosses cell boundaries.
struct Pose { glm::dvec3 pos; glm::vec3 fwd; };
inline Pose player_pose(int i, double gups) {
    const double t = i / 60.0;
    const glm::dvec3 p(40.0 * std::sin(0.3 * t), -700.0 + gups * t, 15.0 * std::sin(0.5 * t));
    const glm::dvec3 v(40.0 * 0.3 * std::cos(0.3 * t), gups, 15.0 * 0.5 * std::cos(0.5 * t));
    return {p, glm::vec3(glm::normalize(v))};
}

// A chase camera behind and above the player, 60 degree vertical FOV.
inline void chase_camera(const Pose& pose, glm::mat4& view, glm::mat4& proj) {
    const glm::vec3 p(pose.pos);
    const glm::vec3 eye = p - pose.fwd * 12.0f + glm::vec3(0, 0, 3.0f);
    view = glm::lookAt(eye, p + pose.fwd * 20.0f, glm::vec3(0, 0, 1));
    proj = glm::perspective(glm::radians(60.0f), 16.0f / 9.0f, 0.1f, 1.0e6f);
}

// FNV-1a 64 over raw bytes: equivalence digests (byte-identical output).
struct Digest {
    std::uint64_t h = 0xcbf29ce484222325ull;
    void bytes(const void* p, std::size_t n) {
        const auto* b = static_cast<const unsigned char*>(p);
        for (std::size_t i = 0; i < n; ++i) { h ^= b[i]; h *= 0x100000001b3ull; }
    }
    template <class T> void pod(const T& v) { bytes(&v, sizeof(T)); }
};

}  // namespace rock_scenario
