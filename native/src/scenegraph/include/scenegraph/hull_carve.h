#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <glm/glm.hpp>

namespace scenegraph {

// ── Strength → ABSOLUTE carve radius (game units) ────────────────────────────
// BC's DamageTool authored hull damage as an additive metaball field: strength
// accumulates spatially and a hole only appears once the summed field crosses
// an iso level. We mirror that — a carve stays invisible until accumulated
// strength (1:1 absorbed-hull) reaches kHullCarveStrengthIso, then EMERGES SMALL
// and grows with continued damage. The radius is ABSOLUTE (game units), NOT a
// fraction of the ship: a weapon carves the same physical hole whether it hits a
// shuttle or a starbase (so a hole is a bigger fraction of a small hull — correct
// physically). Per-ship scaling is BC's authored `DamageRadMod` multiplier
// (default 1.0; only the big fixed structures set it), applied by the caller. See
// docs/original_game_reference/engine/damagetool-and-hull-damage-gaps.md.
inline constexpr float kHullCarveStrengthIso       = 150.0f;   // absorbed-hull before geometry starts breaking
inline constexpr float kHullCarveRadiusAtIso       = 0.03f;    // GU at the iso (emerges small)
inline constexpr float kHullCarveRadiusPerStrength = 0.0006f;  // GU per strength above iso
inline constexpr float kHullCarveRadiusMaxGu       = 0.3f;     // clamp (a heavily-worked breach)

/// Absolute carve radius (game units) for an accumulated field strength. 0 below
/// the iso (invisible), then linear to a clamp. Pure; the caller multiplies by
/// the per-ship DamageRadMod and divides by the instance scale for model units.
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
