// native/src/renderer/include/renderer/shield_state.h
#pragma once

#include <array>
#include <cstdint>
#include <cstddef>
#include <unordered_map>
#include <glm/glm.hpp>

#include "scenegraph/instance.h"

namespace std {
template<> struct hash<scenegraph::InstanceId> {
    std::size_t operator()(const scenegraph::InstanceId& id) const noexcept {
        // Mix index + generation: shifting the high bits keeps both fields
        // contributing to the low bits of the hash, which is what
        // unordered_map's modulo step samples.
        return std::hash<std::uint64_t>{}(
            (static_cast<std::uint64_t>(id.generation) << 32) | id.index);
    }
};
}  // namespace std

namespace renderer {

enum class ShieldMode : std::uint8_t { Ellipsoid = 0, Skin = 1 };

struct Hit {
    glm::vec3 point_world{0.0f};
    glm::vec4 color_rgba{0.0f};
    float intensity_at_t0 = 0.0f;
    float current_intensity = 0.0f;
    double t0_seconds = 0.0;
    int texture_index = 0;
};

class ShieldState {
public:
    static constexpr std::size_t MaxHits = 8;

    ShieldMode mode = ShieldMode::Ellipsoid;
    float decay_seconds = 1.0f;
    glm::vec4 default_color{1.0f};
    glm::vec3 aabb_center{0.0f};
    glm::vec3 aabb_half_extents{0.0f};

    /// Store a new hit. Picks the first empty slot, falling back to the
    /// dimmest slot when full. If `rgba` is all-zero, substitutes
    /// `default_color`. `intensity` is preserved as `intensity_at_t0` and
    /// also seeds `current_intensity` so the slot is immediately active.
    void push_hit(const glm::vec3& point_world,
                  const glm::vec4& rgba,
                  float intensity,
                  double now_seconds,
                  int texture_index);

    /// Recompute current_intensity for every slot at `now_seconds`.
    /// Slots that fall below the inactive threshold (0.01) are zeroed.
    void tick(double now_seconds);

    std::size_t active_count() const noexcept;
    const Hit& slot(std::size_t i) const noexcept { return hits_[i]; }

private:
    std::array<Hit, MaxHits> hits_{};
};

/// Per-instance ShieldState lookup. The host pushes register/unregister
/// when ships are created/destroyed; the renderer's submit() walks the
/// registry each frame and draws the active ones.
class ShieldRegistry {
public:
    void register_instance(scenegraph::InstanceId id,
                           ShieldMode mode,
                           float decay_seconds,
                           const glm::vec4& default_color,
                           const glm::vec3& aabb_center,
                           const glm::vec3& aabb_half_extents);

    void unregister_instance(scenegraph::InstanceId id);

    /// Returns nullptr if instance is not registered.
    ShieldState* find(scenegraph::InstanceId id);
    const ShieldState* find(scenegraph::InstanceId id) const;

    /// Push a hit; silently drops if `id` was never registered.
    /// `texture_index` is picked from an internal stateless RNG.
    void push_hit(scenegraph::InstanceId id,
                  const glm::vec3& point_world,
                  const glm::vec4& rgba,
                  float intensity,
                  double now_seconds);

    /// Tick every registered state at `now_seconds`.
    void tick_all(double now_seconds);

    auto begin() { return states_.begin(); }
    auto end()   { return states_.end(); }
    auto begin() const { return states_.begin(); }
    auto end()   const { return states_.end(); }

private:
    std::unordered_map<scenegraph::InstanceId, ShieldState> states_;
};

}  // namespace renderer
