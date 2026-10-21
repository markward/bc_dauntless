// native/src/scenegraph/include/scenegraph/hull_damage.h
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <glm/glm.hpp>
#include <span>

namespace scenegraph {

/// What a record does to the hull. Values equal the shader's `c.x`.
enum class HullDamageKind : std::uint8_t {
    Surface  = 1,   // plating wear/hole from the outside, faced by a normal
    Internal = 3,   // a blast centred inside the hull; no facing
};

/// One damage record in the ship's body frame (model units).
struct HullDamageRecord {
    glm::vec3      centre_body{0.0f};
    glm::vec3      normal_body{0.0f};   // unit for Surface, zero for Internal
    float          reach = 0.0f;        // body units
    float          wear  = 0.0f;
    HullDamageKind kind  = HullDamageKind::Surface;
    bool           active = false;
};

/// Fixed-capacity per-instance damage store. Merge, never evict: a full store
/// merges its two nearest records instead of dropping the oldest, so wear and
/// holes are never lost. Runtime VFX state only -- never serialized to saves.
class HullDamageStore {
public:
    static constexpr std::size_t kCapacity = 64;
    static constexpr float kMergeFactor = 0.5f;    // centre distance <= 0.5 x the larger reach
    static constexpr float kMaxMergeGrowth = 1.5f; // a voluntary merge never grows reach past 1.5x the larger input

    /// Wear <= 0 or reach <= 0 is ignored (revision unchanged).
    void add(const glm::vec3& centre_body, const glm::vec3& normal_body,
             float reach, float wear, HullDamageKind kind);

    std::span<const HullDamageRecord> records() const { return slots_; }  // all kCapacity slots
    std::size_t count() const;
    std::uint32_t revision() const { return revision_; }  // +1 on every add that changed the store
    void clear();

private:
    std::array<HullDamageRecord, kCapacity> slots_{};
    std::uint32_t revision_ = 0;
};

}  // namespace scenegraph
