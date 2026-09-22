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
//
// NOT the only interpreter of these floats: engine/host_loop.py's
// _build_dynamic_light_render_data ALSO reads glow_size_a/glow_size_b (light
// radius base = max(glow_size_a, glow_size_b)) to build the torpedo's
// dynamic-light descriptor. A re-pin from RE Q1/Q2 must update BOTH sites.
inline TorpedoAnimParams map_torpedo_params(const TorpedoDescriptor& d) {
    TorpedoAnimParams p;
    p.core_half_size  = d.core_size_a;    // photon 0.2
    p.spin_rate       = d.core_size_b;    // photon 1.2 rad/s
    p.pulse_rate      = d.glow_size_a;    // photon 3.0 rad/s
    p.scale_lo        = d.glow_size_b;    // photon 0.3
    p.scale_hi        = d.glow_size_c;    // photon 0.6
    p.clone_scale     = d.glow_size_c;    // second glow quad's fixed scale = hi
    // Args 13/14, verified on the exe one argument at a time (stbc-oracle
    // bible §14.2): 13 is the flare LENGTH (0.7 -> 2.5 took the streaks
    // from 291 to 514 px and GetRadius from 0.77 to 2.56), 14 the flare
    // LIFESPAN (0.4 -> 100 s made them persist and pile up). The provisional
    // mapping had these swapped and drew the streaks at ~0.16 half-size.
    p.flare_period    = d.flares_size_b;  // photon 0.4 s
    p.flare_half_size = d.flares_size_a;  // photon 0.7 GU along the streak
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
    // Top 24 bits only: (h >> 8) <= 0xFFFFFF is exactly representable in
    // float32 (24-bit mantissa), so the product is provably < 1.0. Dividing
    // the full 32-bit h by 2^32 is NOT safe — float32(h) rounds UP to 2^32
    // for h in [0xFFFFFF80, 0xFFFFFFFF], returning exactly 1.0.
    return static_cast<float>(h >> 8) * (1.0f / 16777216.0f);
}

/// A random IN-PLANE rotation, fixed per (id, flare_index): an angle in
/// [0, 2pi) from a hash01 draw, about the root's local z -- the view axis of
/// the camera-facing root frame. A flare is a streak radiating from the core
/// in the screen plane (the oracle's rotation test histograms their 2D
/// directions, bible 14.2 arg 4), so it must stay in the billboard plane.
/// This used to be a rotation about a random 3D axis: every streak then
/// tilted out of the plane and swept through edge-on as the root spun --
/// seen live as the star flickering light-to-dark while it twisted.
/// Deterministic across frames/platforms because hash01 is. Column-vector
/// convention.
inline glm::mat3 flare_rotation(uint32_t id, uint32_t flare_index) {
    const float h_angle = hash01(id, flare_index, 0x3u);
    const float angle = h_angle * torpedo_anim_detail::kTwoPi;
    return glm::mat3(glm::rotate(glm::mat4(1.0f), angle, glm::vec3(0.0f, 0.0f, 1.0f)));
}

/// Camera-facing billboard-root frame for a torpedo (the basis TorpedoPass
/// draws every layer with). Columns are (X_r, Y_r, Z_r), column-vector
/// convention: Z_r = normalize(cam_pos - world_pos) is the view axis,
/// X_r0 = normalize(cross(cam_up, Z_r)), Y_r0 = cross(Z_r, X_r0) (right-
/// handed), then X/Y are rotated about Z_r by fmod(age * spin_rate, 2pi).
/// Provisional axis choice -- spin axis = view axis (Z_r); RE Q7 may revise
/// this to a root-local Y axis instead.
///
/// Degenerate cases: cam_pos == world_pos (no view direction) returns
/// identity; cam_up (nearly) parallel to the view axis falls back to world X
/// as the up seed -- or world Y when the view axis itself is (nearly) world
/// X -- so the frame stays orthonormal and NaN-free at every camera pose.
inline glm::mat3 torpedo_root_frame(const glm::vec3& cam_pos,
                                    const glm::vec3& world_pos,
                                    const glm::vec3& cam_up,
                                    float age, float spin_rate) {
    const glm::vec3 to_cam = cam_pos - world_pos;
    const float len2 = glm::dot(to_cam, to_cam);
    if (len2 < 1e-12f) {
        return glm::mat3(1.0f);  // camera exactly at the torpedo
    }
    const glm::vec3 z_r = to_cam / std::sqrt(len2);
    glm::vec3 x_r0 = glm::cross(cam_up, z_r);
    float x_len2 = glm::dot(x_r0, x_r0);
    if (x_len2 < 1e-12f) {
        const glm::vec3 fallback_up = (std::fabs(z_r.x) < 0.9f)
            ? glm::vec3(1.0f, 0.0f, 0.0f)
            : glm::vec3(0.0f, 1.0f, 0.0f);
        x_r0 = glm::cross(fallback_up, z_r);
        x_len2 = glm::dot(x_r0, x_r0);
    }
    x_r0 /= std::sqrt(x_len2);
    const glm::vec3 y_r0 = glm::cross(z_r, x_r0);

    const float theta =
        std::fmod(age * spin_rate, torpedo_anim_detail::kTwoPi);
    const glm::mat3 spin =
        glm::mat3(glm::rotate(glm::mat4(1.0f), theta, z_r));
    return glm::mat3(spin * x_r0, spin * y_r0, z_r);
}

/// Per-flare quad basis: the (spun) root frame composed with the fixed
/// random per-flare rotation. root * R applies R in the root frame's own
/// basis and re-expresses the result in world space (column-vector
/// convention) -- columns 0/1 of the product are the flare quad's
/// world-space axes.
inline glm::mat3 flare_basis(const glm::mat3& root, uint32_t id,
                             uint32_t flare_index) {
    return root * flare_rotation(id, flare_index);
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
// Teardrop profile. BC's disruptor bolt is a teardrop — pointed tail, widest
// near the nose, rounded nose — not a tube (the earlier 4-ring taper profile
// {0.9927, 0.9727, 0.9273, 0.7273} was an audit reading of ring radii whose
// meaning was never pinned, and drew as a near-cylinder). The full width of
// the bolt is CreateDisruptorModel's `width`: the stock 1.8 × 0.15 bolt
// measures 12.4:1 on the exe (stbc-oracle bible §14.3, 87 × 7 px), so the
// unit mesh's maximum RADIUS is 0.5, not 1.0.
//
// CALIBRATION SURFACE, not a reconstruction: these two constants shape the
// silhouette and are to be re-pinned from the oracle's stock frames
// (docs/results/vfx/pb_stock*.png) — kBoltWidestAt is the fraction of the
// length from the tail at which the bolt is widest (the SWIG call's third
// optional default, 0.8, is the one authored number in that range);
// kBoltTailPower shapes the tail's swell (1 = cone, <1 = fuller).
// A flare quad's half-width across the streak, as a fraction of its
// half-length along it: TorpedoFlares.tga is a 32 x 64 vertical streak.
inline constexpr float kFlareAspect = 0.5f;

inline constexpr int   kBoltRings     = 11;   // u = i/10: a ring sits exactly at kBoltWidestAt
inline constexpr float kBoltWidestAt  = 0.8f;
inline constexpr float kBoltTailPower = 0.6f;
inline constexpr float kBoltMaxRadius = 0.5f;
}  // namespace torpedo_anim_detail

/// Teardrop radius at `u` in [0, 1] along the bolt, 0 = tail, 1 = nose (+y,
/// the direction of travel): a power-law swell from a point at the tail to
/// kBoltMaxRadius at kBoltWidestAt, then a quarter-ellipse cap to a point at
/// the nose. Continuous, 0 at both ends, maximum exactly at kBoltWidestAt.
inline float bolt_teardrop_radius(float u) {
    using namespace torpedo_anim_detail;
    u = std::clamp(u, 0.0f, 1.0f);
    if (u <= kBoltWidestAt) {
        return kBoltMaxRadius * std::pow(u / kBoltWidestAt, kBoltTailPower);
    }
    const float t = (u - kBoltWidestAt) / (1.0f - kBoltWidestAt);   // 0 at widest, 1 at nose
    return kBoltMaxRadius * std::sqrt(std::max(0.0f, 1.0f - t * t));
}

/// Unit teardrop along +Y (y in [-0.5, +0.5]), kBoltRings rings x `segments`
/// points swept around 2pi, ring radii from bolt_teardrop_radius. Closed at
/// both ends (the end rings collapse to points). Triangulated as `segments`
/// quads per band, 2 triangles per quad, indices wound CCW as viewed from
/// outside. `segments` default is 12, the SWIG default that is never
/// overridden in the SDK.
inline BoltMesh build_bolt_mesh(int segments = 12) {
    using torpedo_anim_detail::kBoltRings;
    using torpedo_anim_detail::kTwoPi;

    BoltMesh mesh;
    mesh.vertices.reserve(static_cast<size_t>(kBoltRings) * static_cast<size_t>(segments));
    for (int ring = 0; ring < kBoltRings; ++ring) {
        const float u = static_cast<float>(ring) / static_cast<float>(kBoltRings - 1);
        const float y = u - 0.5f;
        const float radius = bolt_teardrop_radius(u);
        for (int s = 0; s < segments; ++s) {
            const float theta = kTwoPi * static_cast<float>(s) / static_cast<float>(segments);
            mesh.vertices.emplace_back(radius * std::cos(theta), y, radius * std::sin(theta));
        }
    }

    const int bands = kBoltRings - 1;
    mesh.indices.reserve(static_cast<size_t>(bands) * static_cast<size_t>(segments) * 6u);
    for (int band = 0; band < bands; ++band) {
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
