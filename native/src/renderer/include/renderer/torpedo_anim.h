// native/src/renderer/include/renderer/torpedo_anim.h
//
// Pure-math support for BC's torpedo-model animation controller: a constant
// root spin, a pi-wrapped sine scale pulse on the first glow quad, per-flare
// trapezoid alpha twinkle, and (for disruptors) a tapered bolt tube mesh.
// Header-only, no GL, no state — Task 6 (TorpedoPass rewrite) and Task 7
// (tube-mesh builder) consume this directly.
#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <vector>

#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>

#include "renderer/frame.h"

namespace renderer {

namespace torpedo_anim_detail {
inline constexpr float kPi = 3.14159265358979323846f;
inline constexpr float kTwoPi = 2.0f * kPi;
}  // namespace torpedo_anim_detail

/// Resolved per-instance animation parameters for a torpedo/disruptor model
/// (see map_torpedo_params below for how these are derived).
struct TorpedoAnimParams {
    float core_half_size  = 0.0f;
    float spin_rate       = 0.0f;
    float pulse_rate      = 0.0f;
    float scale_lo        = 0.0f;
    float scale_hi        = 0.0f;
    float clone_scale     = 0.0f;
    float flare_period    = 0.0f;
    float flare_half_size = 0.0f;
};

// PROVISIONAL MAPPING — pending RE Q&A (see weapon-firing-mechanics.md §5.5).
// The audit pinned the controller's storage slots (+0x30 spinRate, +0x3C/+0x40
// scale lo/hi, +0x48 pulseRate, +0x50 flare period) but NOT which Python float
// feeds which. This function is the ENTIRE re-pin surface.
inline TorpedoAnimParams map_torpedo_params(const TorpedoDescriptor& d) {
    TorpedoAnimParams p;
    p.core_half_size  = d.core_size_a;    // photon 0.2
    p.spin_rate       = d.core_size_b;    // photon 1.2 rad/s
    p.pulse_rate      = d.glow_size_a;    // photon 3.0 rad/s
    p.scale_lo        = d.glow_size_b;    // photon 0.3
    p.scale_hi        = d.glow_size_c;    // photon 0.6
    p.clone_scale     = d.glow_size_c;    // second glow quad's fixed scale = hi
    p.flare_period    = d.flares_size_a;  // photon 0.7 s
    // 0.4 = byte-verified flare quad half-size constant at 0x0088C5AC;
    // flares_size_b (=0.4 in all 9 SDK modules) treated as a scale on it.
    p.flare_half_size = 0.4f * d.flares_size_b;
    return p;
}

/// Pi-wrapped sine scale pulse: phase sweeps [0, pi) so sin() stays
/// non-negative and the scale ramps lo -> hi -> lo without ever inverting.
/// `fabs` is BC's winding-order guard (also keeps the result non-negative
/// when the caller passes lo > hi). Negative age is clamped to 0.
inline float glow_pulse_scale(float age, float rate, float lo, float hi) {
    const float clamped_age = std::max(age, 0.0f);
    const float phase = std::fmod(clamped_age * rate, torpedo_anim_detail::kPi);
    return std::fabs(lo + std::sin(phase) * (hi - lo));
}

/// Per-flare alpha trapezoid: linear rise over [0, 0.3), plateau at 1.0 over
/// [0.3, 0.7), linear fall over [0.7, 1.0), 0 outside. `u` is expected in
/// [0, 1) but u == 1.0 is handled (falls through to the else branch -> 0).
/// Audit-confirmed constants: 0.3 / 0.7 / 3.3333333 (== 1/0.3).
inline float flare_trapezoid(float u) {
    if (u < 0.30f) return u * (1.0f / 0.3f);
    if (u < 0.70f) return 1.0f;
    if (u < 1.0f)  return 1.0f - (u - 0.70f) * (1.0f / 0.3f);
    return 0.0f;
}

/// Deterministic integer hash -> float in [0, 1). Pure, stateless, no
/// <random>/rand() — same (id, index, salt) always produces the same value,
/// on every frame and every platform. Murmur3-style finalizer mix.
inline float hash01(uint32_t id, uint32_t index, uint32_t salt) {
    uint32_t h = id * 0x9E3779B1u ^ index * 0x85EBCA77u ^ salt * 0xC2B2AE3Du;
    h ^= h >> 15;
    h *= 0x2C1B3C6Du;
    h ^= h >> 12;
    h *= 0x297A2D39u;
    h ^= h >> 15;
    // 2^32 as a float; result is strictly < 1.0 since h <= 0xFFFFFFFF.
    return static_cast<float>(h) / 4294967296.0f;
}

/// A random 3D rotation, fixed per (id, flare_index): a uniform-ish random
/// unit axis (from two hash01 draws, spherical) plus a random angle in
/// [0, 2pi) (a third hash01 draw), built via Rodrigues rotation. Deterministic
/// across frames/platforms because hash01 is. Column-vector convention.
inline glm::mat3 flare_rotation(uint32_t id, uint32_t flare_index) {
    const float h_theta = hash01(id, flare_index, 0x1u);
    const float h_z     = hash01(id, flare_index, 0x2u);
    const float h_angle = hash01(id, flare_index, 0x3u);

    const float theta = h_theta * torpedo_anim_detail::kTwoPi;
    const float z = h_z * 2.0f - 1.0f;
    const float r = std::sqrt(std::max(0.0f, 1.0f - z * z));
    const glm::vec3 axis(r * std::cos(theta), r * std::sin(theta), z);
    const float angle = h_angle * torpedo_anim_detail::kTwoPi;

    return glm::mat3(glm::rotate(glm::mat4(1.0f), angle, axis));
}

/// Rotation taking model +Y to `forward` (unit input): tube-local +Y maps to
/// the world velocity direction, i.e. world = R * local. Column-vector,
/// right-handed. Degenerate cases: forward ~= +Y -> identity; forward ~= -Y
/// -> pi rotation about X (no unique axis when forward is exactly -Y, so an
/// arbitrary perpendicular axis is used).
inline glm::mat3 bolt_align_rotation(const glm::vec3& forward) {
    const glm::vec3 y_hat(0.0f, 1.0f, 0.0f);
    const float d = std::clamp(glm::dot(y_hat, forward), -1.0f, 1.0f);
    if (d > 0.9999f) {
        return glm::mat3(1.0f);
    }
    if (d < -0.9999f) {
        return glm::mat3(glm::rotate(glm::mat4(1.0f), torpedo_anim_detail::kPi,
                                     glm::vec3(1.0f, 0.0f, 0.0f)));
    }
    const glm::vec3 axis = glm::normalize(glm::cross(y_hat, forward));
    const float angle = std::acos(d);
    return glm::mat3(glm::rotate(glm::mat4(1.0f), angle, axis));
}

/// Unlit, uniform-colored tube mesh: positions only, no normals/UVs/colors.
struct BoltMesh {
    std::vector<glm::vec3> vertices;
    std::vector<uint32_t>  indices;
};

namespace torpedo_anim_detail {
// 4 rings evenly spaced along y in [-0.5, +0.5].
inline constexpr float kBoltRingY[4] = {-0.5f, -1.0f / 6.0f, 1.0f / 6.0f, 0.5f};

// Audited cross-section taper profile (4 ring radii). PROVISIONAL
// INTERPRETATION: which end is "forward" was not pinned by the audit — this
// ordering puts the narrow end (0.7273) at +y (direction of travel). One
// profile-reverse (index the array as kBoltTaperProfile[3 - ring]) flips it.
inline constexpr float kBoltTaperProfile[4] = {0.9927f, 0.9727f, 0.9273f, 0.7273f};
}  // namespace torpedo_anim_detail

/// Unit tube along +Y (y in [-0.5, +0.5]), 4 rings x `segments` points swept
/// around 2pi, ring radii = the audited taper profile (narrow end forward,
/// see kBoltTaperProfile). Open tube — NO end caps (interpretation; BC's
/// original geometry was not traced for cap presence). Triangulated as
/// `segments` quads per band across 3 bands, 2 triangles per quad, indices
/// wound CCW as viewed from outside the tube. `segments` default is 12, the
/// SWIG default that is never overridden in the SDK.
inline BoltMesh build_bolt_mesh(int segments = 12) {
    using torpedo_anim_detail::kBoltRingY;
    using torpedo_anim_detail::kBoltTaperProfile;
    using torpedo_anim_detail::kTwoPi;

    BoltMesh mesh;
    constexpr int kRings = 4;
    mesh.vertices.reserve(static_cast<size_t>(kRings) * static_cast<size_t>(segments));
    for (int ring = 0; ring < kRings; ++ring) {
        const float y = kBoltRingY[ring];
        const float radius = kBoltTaperProfile[ring];
        for (int s = 0; s < segments; ++s) {
            const float theta = kTwoPi * static_cast<float>(s) / static_cast<float>(segments);
            mesh.vertices.emplace_back(radius * std::cos(theta), y, radius * std::sin(theta));
        }
    }

    constexpr int kBands = kRings - 1;
    mesh.indices.reserve(static_cast<size_t>(kBands) * static_cast<size_t>(segments) * 6u);
    for (int band = 0; band < kBands; ++band) {
        for (int s = 0; s < segments; ++s) {
            const uint32_t s_next = static_cast<uint32_t>((s + 1) % segments);
            const uint32_t a = static_cast<uint32_t>(band * segments + s);
            const uint32_t b = static_cast<uint32_t>(band * segments) + s_next;
            const uint32_t c = static_cast<uint32_t>((band + 1) * segments + s);
            const uint32_t d = static_cast<uint32_t>((band + 1) * segments) + s_next;
            // Two triangles per quad, CCW viewed from outside (radially
            // outward normal): (a, c, b) then (b, c, d).
            mesh.indices.push_back(a);
            mesh.indices.push_back(c);
            mesh.indices.push_back(b);

            mesh.indices.push_back(b);
            mesh.indices.push_back(c);
            mesh.indices.push_back(d);
        }
    }
    return mesh;
}

}  // namespace renderer
