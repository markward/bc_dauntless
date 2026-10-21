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

/// Where an add landed and that record's wear either side of it.
struct HullDamageAddResult {
    int   index = -1;          // -1: the input was ignored
    float wear_before = 0.0f;  // the slot's wear before the input (0 for a fresh slot)
    float wear_after  = 0.0f;
};

/// Fixed-capacity per-instance damage store. Merge, never evict: a full store
/// merges the same-kind pair whose merge grows reach least instead of dropping
/// the oldest, so wear and holes are never lost. Runtime VFX state only --
/// never serialized to saves.
class HullDamageStore {
public:
    static constexpr std::size_t kCapacity = 64;
    static constexpr float kMergeFactor = 0.5f;    // centre distance <= 0.5 x the larger reach
    static constexpr float kMaxMergeGrowth = 1.5f; // a voluntary merge never grows reach past 1.5x the larger input
    // kMaxMergeGrowth is INERT while kMergeFactor is 0.5: a voluntary merge
    // needs d <= 0.5 * max r, and the merged reach is at most d + max r <=
    // 1.5 * max r, so the cap can never refuse one. It is kept for when the
    // merge factor becomes a dial.

    /// Wear <= 0 or reach <= 0 is ignored (revision unchanged), as is any
    /// non-finite centre, normal, reach or wear.
    /// Returns the slot the input landed in (merged or new; a forced merge
    /// reports the slot the NEW input went into) with its wear before/after.
    HullDamageAddResult add(const glm::vec3& centre_body, const glm::vec3& normal_body,
                            float reach, float wear, HullDamageKind kind);

    std::span<const HullDamageRecord> records() const { return slots_; }  // all kCapacity slots
    std::size_t count() const;
    /// Changes on every add that changed the store and on clear(). Drawn from
    /// one process-wide monotonic counter, so a value never repeats across
    /// stores; 0 only for a store nothing has changed yet.
    std::uint32_t revision() const { return revision_; }
    void clear();

private:
    std::array<HullDamageRecord, kCapacity> slots_{};
    std::uint32_t revision_ = 0;
};

}  // namespace scenegraph
