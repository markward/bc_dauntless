// native/src/scenegraph/include/scenegraph/damage_decals.h
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <glm/glm.hpp>

namespace scenegraph {

/// Weapon class drives the decal's visual behaviour (Phase 2 shader).
/// - HeatGlow (phaser): transient emissive bloom, reclaimed when cold.
/// - Scorch  (torpedo/disruptor): persistent deposit + blackbody ember.
enum class WeaponClass : std::uint32_t {
    HeatGlow = 0,
    Scorch   = 1,
};

/// One object-space impact record, stored in the ship's body frame so it
/// tracks the hull as the ship moves and rotates.
struct DamageDecal {
    glm::vec3     point_body{0.0f};
    glm::vec3     normal_body{0.0f};
    float         radius = 0.0f;       // r_hit, game units
    float         intensity = 0.0f;    // [0,1], deposit darkness / hole threshold
    float         birth_time = 0.0f;   // seconds (game clock); drives ember cooling
    WeaponClass   weapon_class = WeaponClass::Scorch;
    bool          active = false;
    std::uint64_t seq = 0;             // FIFO insertion order (0 = never used)
};

/// Transform a world-space point into a ship's body frame.
/// Column-vector convention (CLAUDE.md): body = inverse(ship_world) * p.
glm::vec3 world_to_body(const glm::mat4& ship_world, const glm::vec3& p_world);

/// Transform a world-space direction into the ship's body frame and
/// renormalise. Returns the input length-0 vector unchanged.
glm::vec3 world_dir_to_body(const glm::mat4& ship_world, const glm::vec3& dir_world);

/// Fixed-capacity per-instance decal store with merge-then-FIFO insertion.
class DamageDecalRing {
public:
    static constexpr std::size_t kMaxDecals = 24;
    static constexpr float kMergeFactor = 0.5f;       // merge within 0.5 * radius
    static constexpr float kHeatGlowLifetime = 1.2f;  // seconds before reclaim

    /// Insert a decal (point/normal already in body frame).
    /// Merge: if a same-class active decal lies within kMergeFactor*radius,
    /// deepen its intensity and re-ignite its ember instead of allocating.
    /// Otherwise take a free slot, evicting the oldest (smallest seq) if full.
    /// `radius` is r_hit in game units and is expected to be > 0 (it comes
    /// from WeaponHitEvent); a zero radius collapses the merge window to a
    /// point, so only exactly-coincident same-class hits would merge.
    void add(const glm::vec3& point_body, const glm::vec3& normal_body,
             float radius, float intensity, WeaponClass weapon_class, float now);

    /// Reclaim cold HeatGlow decals (age beyond kHeatGlowLifetime).
    void tick(float now);

    std::size_t count() const;                      // number of active decals
    const std::array<DamageDecal, kMaxDecals>& slots() const { return slots_; }

private:
    std::array<DamageDecal, kMaxDecals> slots_{};
    std::uint64_t next_seq_ = 1;
};

}  // namespace scenegraph
