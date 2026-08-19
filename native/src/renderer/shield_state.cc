// native/src/renderer/shield_state.cc
#include "renderer/shield_state.h"

#include <algorithm>
#include <cmath>

namespace renderer {

namespace {
constexpr float kInactive = 0.01f;
constexpr glm::vec4 kZero(0.0f);

// GLSL smoothstep, so the CPU gate and the shader agree bit-for-shape.
float smoothstep01(float edge0, float edge1, float x) {
    if (edge1 <= edge0) return x < edge0 ? 0.0f : 1.0f;
    const float t = std::clamp((x - edge0) / (edge1 - edge0), 0.0f, 1.0f);
    return t * t * (3.0f - 2.0f * t);
}
}  // namespace

float shield_splash_intensity(float coverage, float hit_intensity) {
    return coverage * hit_intensity * kShieldSplashOpacity;
}

float shield_splash_gate(const glm::vec3& frag_dir_from_centre,
                         const glm::vec3& impact_dir) {
    return smoothstep01(0.0f, kShieldSplashGateFeather,
                        glm::dot(frag_dir_from_centre, impact_dir));
}

float shield_splash_coverage(const glm::vec3& frag_world,
                             const glm::vec3& hit_world,
                             const glm::vec3& bubble_centre,
                             const glm::vec3& bubble_semi_axes) {
    if (bubble_semi_axes.x <= 0.0f || bubble_semi_axes.y <= 0.0f ||
        bubble_semi_axes.z <= 0.0f)
        return 0.0f;

    // Into the bubble's unit-sphere space. Only the DIRECTIONS matter after
    // this, so a hull hit point (which sits 1/√3 of the way out) normalises to
    // the same direction as the bubble point above it, and Skin mode — whose
    // fragments are hull verts, not ellipsoid points — works unchanged.
    glm::vec3 n_hit = (hit_world - bubble_centre) / bubble_semi_axes;
    glm::vec3 n_frag = (frag_world - bubble_centre) / bubble_semi_axes;
    const float lh = glm::length(n_hit);
    const float lf = glm::length(n_frag);
    if (lh < 1e-4f || lf < 1e-4f) return 0.0f;
    n_hit /= lh;
    n_frag /= lf;

    const float gate = shield_splash_gate(n_frag, n_hit);
    if (gate <= 0.0f) return 0.0f;

    // Chord between two unit vectors — 2·sin(θ/2), a pure angular measure, so
    // the footprint no longer depends on the bubble's local radius.
    const float falloff =
        1.0f - smoothstep01(0.0f, kShieldSplashRadius, glm::length(n_frag - n_hit));
    if (falloff <= 0.0f) return 0.0f;
    return gate * falloff;
}

glm::vec3 shield_hit_world_point(const Hit& hit,
                                 const glm::mat4& instance_world) {
    return glm::vec3(instance_world * glm::vec4(hit.point_body, 1.0f));
}

void ShieldState::push_hit(const glm::vec3& point_body,
                           const glm::vec4& rgba,
                           float intensity,
                           double now_seconds,
                           int texture_index) {
    // Find first empty slot; if all occupied, target the dimmest.
    std::size_t target = 0;
    bool found_empty = false;
    float min_intensity = hits_[0].current_intensity;
    for (std::size_t i = 0; i < MaxHits; ++i) {
        if (hits_[i].current_intensity < kInactive) {
            target = i;
            found_empty = true;
            break;
        }
        if (hits_[i].current_intensity < min_intensity) {
            min_intensity = hits_[i].current_intensity;
            target = i;
        }
    }
    (void)found_empty;
    glm::vec4 color = (rgba == kZero) ? default_color : rgba;
    hits_[target] = Hit{
        .point_body = point_body,
        .color_rgba = color,
        .intensity_at_t0 = intensity,
        .current_intensity = intensity,
        .t0_seconds = now_seconds,
        .texture_index = texture_index,
    };
}

void ShieldState::tick(double now_seconds) {
    for (auto& h : hits_) {
        if (h.intensity_at_t0 <= 0.0f) continue;
        float dt = static_cast<float>(now_seconds - h.t0_seconds);
        h.current_intensity = h.intensity_at_t0 * std::exp(-dt / decay_seconds);
        if (h.current_intensity < kInactive) {
            h.current_intensity = 0.0f;
            h.intensity_at_t0 = 0.0f;
        }
    }
}

std::size_t ShieldState::active_count() const noexcept {
    std::size_t n = 0;
    for (const auto& h : hits_) if (h.current_intensity >= kInactive) ++n;
    return n;
}

// ── ShieldRegistry ─────────────────────────────────────────────────────────

void ShieldRegistry::register_instance(scenegraph::InstanceId id,
                                        ShieldMode mode,
                                        float decay_seconds,
                                        const glm::vec4& default_color,
                                        const glm::vec3& aabb_center,
                                        const glm::vec3& aabb_half_extents) {
    auto& s = states_[id];
    s.mode = mode;
    s.decay_seconds = decay_seconds;
    s.default_color = default_color;
    s.aabb_center = aabb_center;
    s.aabb_half_extents = aabb_half_extents;
}

void ShieldRegistry::unregister_instance(scenegraph::InstanceId id) {
    states_.erase(id);
}

ShieldState* ShieldRegistry::find(scenegraph::InstanceId id) {
    auto it = states_.find(id);
    return it == states_.end() ? nullptr : &it->second;
}

const ShieldState* ShieldRegistry::find(scenegraph::InstanceId id) const {
    auto it = states_.find(id);
    return it == states_.end() ? nullptr : &it->second;
}

void ShieldRegistry::push_hit(scenegraph::InstanceId id,
                               const glm::vec3& point_body,
                               const glm::vec4& rgba,
                               float intensity,
                               double now_seconds) {
    auto* s = find(id);
    if (!s) return;
    // texture_index from a thread-local LCG. Stateless across registry calls
    // but ticks remain deterministic (no per-frame randomization).
    static thread_local std::uint32_t rng = 0x12345678u;
    rng = rng * 1664525u + 1013904223u;
    int tex = static_cast<int>(rng >> 30);  // 0..3
    s->push_hit(point_body, rgba, intensity, now_seconds, tex);
}

void ShieldRegistry::tick_all(double now_seconds) {
    for (auto& [id, s] : states_) s.tick(now_seconds);
}

}  // namespace renderer
