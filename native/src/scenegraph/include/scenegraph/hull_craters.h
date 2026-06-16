// native/src/scenegraph/include/scenegraph/hull_craters.h
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <glm/glm.hpp>

namespace scenegraph {

/// One persistent hull-deformation crater, stored in the ship's body frame so
/// it tracks the hull as the ship moves. POD and self-contained: a future save
/// implementation can serialize the slot array directly (spec §9). Unlike a
/// damage decal, a crater has no weapon class and no birth time — it never ages
/// out; it only deepens when the same region is hit again. `kind` (dent vs
/// gouge) is NOT stored: it is derived at shade time from `depth` (spec).
struct HullCrater {
    glm::vec3     point_body{0.0f};       // impact location, body frame, model units
    glm::vec3     impact_dir_body{0.0f};  // unit impact/shove direction, body frame
    glm::vec3     normal_body{0.0f};      // outward surface normal, body frame
    float         radius = 0.0f;          // crater radius, model units
    float         depth = 0.0f;           // accumulated displacement depth, model units
    std::uint64_t seq = 0;                // insertion order (0 = never used)
    bool          active = false;
};

/// Fixed-capacity per-instance crater store: merge-accumulate-then-evict.
class HullCraterField {
public:
    static constexpr std::size_t kMaxCraters = 24;
    static constexpr float kMergeFactor = 0.5f;  // merge within 0.5 * radius
    /// Maximum accumulated depth (model units). Default cap; tuned in Plan 4
    /// against visual results. Caps runaway deepening from repeated hits.
    static constexpr float kMaxDepth = 1.0f;

    /// Insert a crater (point/dir/normal already in body frame, radius/depth in
    /// model units). If an active crater lies within kMergeFactor*radius, deepen
    /// it (accumulation, capped at kMaxDepth) and refresh its direction/normal/
    /// age instead of allocating. Otherwise take a free slot, else evict the
    /// shallowest crater (tie-break: oldest). `depth` is clamped to
    /// [0, kMaxDepth]; negative input floors to 0.
    /// `impact_dir_body` must be unit length; add() does not renormalise it.
    void add(const glm::vec3& point_body, const glm::vec3& impact_dir_body,
             const glm::vec3& normal_body, float radius, float depth);

    std::size_t count() const;  // number of active craters
    const std::array<HullCrater, kMaxCraters>& slots() const { return slots_; }

private:
    std::array<HullCrater, kMaxCraters> slots_{};
    std::uint64_t next_seq_ = 1;
};

}  // namespace scenegraph
