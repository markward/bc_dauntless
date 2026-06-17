#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <glm/glm.hpp>

namespace scenegraph {

/// One carve sphere, body frame, model units. A carve never ages out; it only
/// grows when the same region is re-hit. Runtime VFX only — never serialized.
struct HullCarve {
    glm::vec3     center_body{0.0f};
    float         radius = 0.0f;
    std::uint64_t seq = 0;     // insertion order (0 = never used)
    bool          active = false;
};

/// Fixed-capacity per-instance carve store: merge-grow-then-evict.
class HullCarveField {
public:
    static constexpr std::size_t kMaxCarves = 24;
    static constexpr float kMergeFactor = 0.5f;   // merge within 0.5 * radius

    /// Insert a carve sphere (body frame, model units). If an active carve lies
    /// within kMergeFactor*radius, grow it (max radius) and refresh its age
    /// instead of allocating. Otherwise take a free slot, else evict the
    /// smallest carve (tie-break: oldest).
    void add(const glm::vec3& center_body, float radius);

    std::size_t count() const;
    const std::array<HullCarve, kMaxCarves>& slots() const { return slots_; }

private:
    std::array<HullCarve, kMaxCarves> slots_{};
    std::uint64_t next_seq_ = 1;
};

}  // namespace scenegraph
