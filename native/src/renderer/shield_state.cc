// native/src/renderer/shield_state.cc
#include "renderer/shield_state.h"

#include <cmath>

namespace renderer {

namespace {
constexpr float kInactive = 0.01f;
constexpr glm::vec4 kZero(0.0f);
}  // namespace

void ShieldState::push_hit(const glm::vec3& point_world,
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
        .point_world = point_world,
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
                               const glm::vec3& point_world,
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
    s->push_hit(point_world, rgba, intensity, now_seconds, tex);
}

void ShieldRegistry::tick_all(double now_seconds) {
    for (auto& [id, s] : states_) s.tick(now_seconds);
}

}  // namespace renderer
