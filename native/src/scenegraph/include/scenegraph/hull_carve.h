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
    glm::vec3     surface_normal{0.0f, 0.0f, 1.0f};  // body-frame outward normal
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
    /// instead of allocating (keeping the existing slot's surface_normal).
    /// Otherwise take a free slot, else evict the smallest carve (tie-break:
    /// oldest). surface_normal is the body-frame outward hit normal, used by the
    /// hole-clip / scoop to offset the cap and align hole and interior.
    void add(const glm::vec3& center_body, float radius,
             const glm::vec3& surface_normal);

    std::size_t count() const;
    const std::array<HullCarve, kMaxCarves>& slots() const { return slots_; }

private:
    std::array<HullCarve, kMaxCarves> slots_{};
    std::uint64_t next_seq_ = 1;
};

}  // namespace scenegraph
