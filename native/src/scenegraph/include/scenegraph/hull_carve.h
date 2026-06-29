#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <glm/glm.hpp>

namespace scenegraph {

// ── Strength → visible carve radius (game units) ────────────────────────────
// BC's DamageTool authored hull damage as an additive metaball field: strength
// accumulates spatially and a hole only appears once the summed field crosses
// an iso level. We mirror that — a carve stays invisible until accumulated
// strength reaches kHullCarveStrengthIso, then its radius grows with strength.
// Anchored to BC's two authored tiers: strength 300 -> 0.4 GU (minor surface),
// 600 -> 1.0 GU (breach). See
// docs/original_game_reference/engine/damagetool-and-hull-damage-gaps.md.
inline constexpr float kHullCarveStrengthIso       = 300.0f;
inline constexpr float kHullCarveRadiusAtIso       = 0.4f;    // GU at the iso
inline constexpr float kHullCarveRadiusPerStrength = 0.002f;  // GU per strength above iso
inline constexpr float kHullCarveRadiusMaxGu       = 1.5f;    // clamp

/// Visible carve radius (game units) for an accumulated field strength. 0 below
/// the iso (invisible), then linear to a clamp. Pure; the caller divides by the
/// instance scale to get model units.
inline float hull_carve_strength_to_radius_gu(float strength) {
    if (strength < kHullCarveStrengthIso) return 0.0f;
    const float r = kHullCarveRadiusAtIso
                  + (strength - kHullCarveStrengthIso) * kHullCarveRadiusPerStrength;
    return r < kHullCarveRadiusMaxGu ? r : kHullCarveRadiusMaxGu;
}

/// One carve sphere, body frame, model units. A carve never ages out; it only
/// grows when the same region is re-hit (strength accumulates). Runtime VFX
/// only — never serialized.
struct HullCarve {
    glm::vec3     center_body{0.0f};
    float         influ_radius = 0.0f;  // merge proximity (model units)
    float         strength = 0.0f;      // accumulated field strength (BC damage units)
    float         radius = 0.0f;        // visible carve radius (model units); 0 below iso.
                                        // Caller-set from strength + a floor; monotonic.
    glm::vec3     surface_normal{0.0f, 0.0f, 1.0f};  // body-frame outward normal
    std::uint64_t seq = 0;     // insertion order (0 = never used)
    bool          active = false;
};

/// Fixed-capacity per-instance carve store: accumulate-merge-then-evict.
class HullCarveField {
public:
    static constexpr std::size_t kMaxCarves = 24;
    static constexpr float kMergeFactor = 0.5f;   // merge within 0.5 * influ_radius

    /// Deposit `strength` at a point (body frame, model units). If an active
    /// carve lies within kMergeFactor*influ_radius, accumulate strength into it
    /// (widening influ, moving to the freshest centre, refreshing age) instead
    /// of allocating. Otherwise take a free slot, else evict the smallest-radius
    /// carve (tie-break: oldest). Returns the receiving slot so the caller can
    /// derive + set the visible `radius` — the caller owns the instance scale
    /// and the strength→radius curve, and keeps `radius` monotonic.
    HullCarve& add(const glm::vec3& center_body, float influ_radius,
                   float strength, const glm::vec3& surface_normal);

    std::size_t count() const;
    const std::array<HullCarve, kMaxCarves>& slots() const { return slots_; }

private:
    std::array<HullCarve, kMaxCarves> slots_{};
    std::uint64_t next_seq_ = 1;
};

}  // namespace scenegraph
