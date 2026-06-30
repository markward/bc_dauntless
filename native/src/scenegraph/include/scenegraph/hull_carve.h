#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <glm/glm.hpp>

namespace scenegraph {

// ── Strength → carve size, as a FRACTION of the ship's bounding radius ───────
// BC's DamageTool authored hull damage as an additive metaball field: strength
// accumulates spatially and a hole only appears once the summed field crosses
// an iso level. We mirror that — a carve stays invisible until accumulated
// strength (1:1 absorbed-hull) reaches kHullCarveStrengthIso, then EMERGES SMALL
// and grows with continued damage. The curve returns a FRACTION OF THE SHIP'S
// RADIUS (not an absolute size), so the same damage makes a proportionally-sized
// hole on a shuttle and a starbase; the caller multiplies by the ship radius
// (GU). The small fraction at the iso (vs a chunky pop) keeps the onset gradual,
// not all-or-nothing. See
// docs/original_game_reference/engine/damagetool-and-hull-damage-gaps.md.
inline constexpr float kHullCarveStrengthIso         = 150.0f;    // absorbed-hull before geometry starts breaking
inline constexpr float kHullCarveFractionAtIso       = 0.0075f;   // of ship radius at the iso
inline constexpr float kHullCarveFractionPerStrength = 0.000125f; // per strength above iso
inline constexpr float kHullCarveFractionMax         = 0.0625f;   // full breach = 6.25% of ship radius

/// Carve size as a fraction of the ship's bounding radius for an accumulated
/// field strength. 0 below the iso (invisible), then linear to a clamp. Pure;
/// the caller multiplies by the ship radius (GU) and divides by the instance
/// scale to get model units.
inline float hull_carve_strength_to_fraction(float strength) {
    if (strength < kHullCarveStrengthIso) return 0.0f;
    const float f = kHullCarveFractionAtIso
                  + (strength - kHullCarveStrengthIso) * kHullCarveFractionPerStrength;
    return f < kHullCarveFractionMax ? f : kHullCarveFractionMax;
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
