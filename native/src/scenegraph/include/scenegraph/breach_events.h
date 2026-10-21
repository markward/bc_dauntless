#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <glm/glm.hpp>

namespace scenegraph {

// Effect lifetime constants. All consumers include this header.
inline constexpr float kDebrisLife = 10.0f; // seconds: tumbling chunks drift + fade
inline constexpr float kVentLife   = 0.5f;  // seconds: venting EMISSION window — a
                                            // short, fast gas-release burst (particles
                                            // fade ~0.4s after), not a sustained plume
inline constexpr float kRimLife    = 3.0f;  // seconds: molten rim cooling
// An event lives until all consumers have finished with it.
inline constexpr float kEventLife  = 10.0f; // max(kDebrisLife, kVentLife, kRimLife)

struct BreachEvent {
    glm::vec3     center_body   {0.0f};         // breach center in the POSED body frame
                                                 // (model units): where venting and
                                                 // debris are placed
    float         radius        = 0.0f;          // breach radius (model units)
    glm::vec3     surface_normal{0.0f, 0.0f, 1.0f};  // posed body frame, outward
    float         birth_time    = 0.0f;          // game-clock seconds at push time
    std::uint64_t seed          = 0;             // deterministic per-event hash seed
    bool          active        = false;
    // The molten rim's frame (layered damage phase 4 §2.3): the breach centre
    // in the REST frame of `node` (HullDamageRecord::node; -1 = the body,
    // where it equals center_body). The plating evaluates in each mesh's
    // rest frame, so a rim on a posed part glows on the part.
    glm::vec3     center_rest   {0.0f};
    int           node          = -1;
};

/// Fixed-capacity per-instance breach event store. Overwrites the oldest slot
/// when full (simple FIFO — no merge; every breach is distinct). Runtime-only
/// VFX, never serialized.
class BreachEventRing {
public:
    static constexpr std::size_t kMaxEvents = 24;

    /// Record a new breach event. Overwrites the slot with the smallest
    /// birth_time when all slots are occupied. `node` / `center_rest`: the
    /// record's node and its rest-frame centre (BreachEvent::center_rest);
    /// omitted, the body (-1) and center_body.
    void push(const glm::vec3& center_body, float radius,
              const glm::vec3& surface_normal,
              float birth_time, std::uint64_t seed,
              int node = -1, std::optional<glm::vec3> center_rest = std::nullopt);

    /// Deactivate events whose age exceeds kEventLife.
    void tick(float now);

    std::size_t count() const;
    const std::array<BreachEvent, kMaxEvents>& slots() const { return slots_; }

private:
    std::array<BreachEvent, kMaxEvents> slots_{};
};

} // namespace scenegraph
