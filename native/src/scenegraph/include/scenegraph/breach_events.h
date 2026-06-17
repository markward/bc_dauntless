#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <glm/glm.hpp>

namespace scenegraph {

// Effect lifetime constants. All consumers include this header.
inline constexpr float kDebrisLife = 2.5f;  // seconds: tumbling chunks
inline constexpr float kVentLife   = 2.0f;  // seconds: venting jet emission
inline constexpr float kRimLife    = 3.0f;  // seconds: molten rim cooling
// An event lives until all consumers have finished with it.
inline constexpr float kEventLife  = 3.0f;  // max(kDebrisLife, kVentLife, kRimLife)

struct BreachEvent {
    glm::vec3     center_body   {0.0f};         // breach center in body frame (model units)
    float         radius        = 0.0f;          // carve sphere radius (model units)
    glm::vec3     surface_normal{0.0f, 0.0f, 1.0f};  // body frame, outward
    float         birth_time    = 0.0f;          // game-clock seconds at push time
    std::uint64_t seed          = 0;             // deterministic per-event hash seed
    bool          active        = false;
};

/// Fixed-capacity per-instance breach event store. Overwrites the oldest slot
/// when full (simple FIFO — no merge; every breach is distinct). Runtime-only
/// VFX, never serialized.
class BreachEventRing {
public:
    static constexpr std::size_t kMaxEvents = 24;

    /// Record a new breach event. Overwrites the slot with the smallest
    /// birth_time when all slots are occupied.
    void push(const glm::vec3& center_body, float radius,
              const glm::vec3& surface_normal,
              float birth_time, std::uint64_t seed);

    /// Deactivate events whose age exceeds kEventLife.
    void tick(float now);

    std::size_t count() const;
    const std::array<BreachEvent, kMaxEvents>& slots() const { return slots_; }

private:
    std::array<BreachEvent, kMaxEvents> slots_{};
};

} // namespace scenegraph
