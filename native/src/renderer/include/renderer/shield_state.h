// native/src/renderer/include/renderer/shield_state.h
#pragma once

#include <array>
#include <cstdint>
#include <cstddef>
#include <unordered_map>
#include <glm/glm.hpp>

#include "scenegraph/instance.h"

namespace std {
template<> struct hash<scenegraph::InstanceId> {
    std::size_t operator()(const scenegraph::InstanceId& id) const noexcept {
        // Mix index + generation: shifting the high bits keeps both fields
        // contributing to the low bits of the hash, which is what
        // unordered_map's modulo step samples.
        return std::hash<std::uint64_t>{}(
            (static_cast<std::uint64_t>(id.generation) << 32) | id.index);
    }
};
}  // namespace std

namespace renderer {

enum class ShieldMode : std::uint8_t { Ellipsoid = 0, Skin = 1 };

/// BC's bubble sizing (producer at 0x005ABAC0): ellipsoid semi-axis =
/// AABB half-extent × √3, the minimal factor that puts every corner of the
/// vertex-swept bounding box exactly on the ellipsoid surface — the whole
/// hull fits by construction, no per-ship tuning. Same single-precision
/// literal as the binary (0x3FDDB3D7).
inline constexpr float kShieldEllipsoidAxisScale = 1.7320508f;

/// Splash size, as a CHORD on the bubble's unit-sphere space (positions
/// divided component-wise by the semi-axes). Dimensionless and ship-independent
/// — the splash is a fixed angular cap on every hull, which is what makes it
/// the same shape wherever it lands. chord = 2·sin(θ/2), so 0.35 ≈ a 20°
/// half-width. Tune-by-eye; changing it needs a rebuild.
///
/// It replaced a world-space radius keyed to the smallest half-extent. That
/// measured the falloff as a world chord to a splash centre recomputed at each
/// FRAGMENT's own distance from the bubble centre — so walking from a bow hit
/// toward the dorsal pole, where a Galaxy's radius collapses 558 → 121, the
/// splash centre chased the fragment inward and the falloff never bit. Bow and
/// flank hits smeared into ribbons reaching 3.5× further toward the poles than
/// across (measured on the real Galaxy AABB), which renders as an arc draped
/// over the ship rather than an impact patch.
inline constexpr float kShieldSplashRadius = 0.35f;

/// Width of the smooth terminator on the hemisphere gate, in units of
/// cos(angle) away from the terminator plane. Small enough to stay a localised
/// splash, wide enough that the cutoff is not a hard seam.
inline constexpr float kShieldSplashGateFeather = 0.25f;

/// Coverage of one impact splash at a point on the bubble, in [0, 1] — the
/// product of the hemisphere gate and the radial falloff, i.e. everything
/// `splash_sample` in shaders/shield.frag scales the texture by.
///
/// All vectors are WORLD space; `frag_world` is expected to lie on the bubble
/// surface (the pass draws a unit sphere scaled to `bubble_semi_axes`). The
/// measure itself is taken in the bubble's unit-sphere space — the same space
/// BC's own facing chooser works in (`ShipClass::TestHit`, stbc_reference
/// spec/ShieldFacingDamage.md §2.3 step 4) — so the footprint does not depend
/// on where it lands.
///
/// This is the shared source of truth for the splash footprint. MUST match
/// splash_sample() in shaders/shield.frag — keep in sync.
float shield_splash_coverage(const glm::vec3& frag_world,
                             const glm::vec3& hit_world,
                             const glm::vec3& bubble_centre,
                             const glm::vec3& bubble_semi_axes);

/// Near/far hemisphere gate for the impact splash: 1 on the hit-facing side of
/// the bubble, 0 on the far side, with a smooth terminator between.
///
/// Without it, `splash_sample` in shaders/shield.frag paints the texture's
/// CENTRE on the point diametrically opposite the hit (its UV projection along
/// `impact_dir` has no sign), so a ventral hit grows a full-brightness splash
/// on the DORSAL face. The shield pass runs after the opaque hull with depth
/// test on, so the hull hides the true splash and leaves the mirror visible —
/// the player sees the impact centred on the wrong face.
///
/// Both arguments must be unit length. MUST match the expression in
/// shaders/shield.frag — keep in sync.
float shield_splash_gate(const glm::vec3& frag_dir_from_centre,
                         const glm::vec3& impact_dir);

struct Hit {
    glm::vec3 point_world{0.0f};
    glm::vec4 color_rgba{0.0f};
    float intensity_at_t0 = 0.0f;
    float current_intensity = 0.0f;
    double t0_seconds = 0.0;
    int texture_index = 0;
};

class ShieldState {
public:
    static constexpr std::size_t MaxHits = 8;

    ShieldMode mode = ShieldMode::Ellipsoid;
    float decay_seconds = 1.0f;
    glm::vec4 default_color{1.0f};
    glm::vec3 aabb_center{0.0f};
    glm::vec3 aabb_half_extents{0.0f};

    /// Store a new hit. Picks the first empty slot, falling back to the
    /// dimmest slot when full. If `rgba` is all-zero, substitutes
    /// `default_color`. `intensity` is preserved as `intensity_at_t0` and
    /// also seeds `current_intensity` so the slot is immediately active.
    void push_hit(const glm::vec3& point_world,
                  const glm::vec4& rgba,
                  float intensity,
                  double now_seconds,
                  int texture_index);

    /// Recompute current_intensity for every slot at `now_seconds`.
    /// Slots that fall below the inactive threshold (0.01) are zeroed.
    void tick(double now_seconds);

    std::size_t active_count() const noexcept;
    const Hit& slot(std::size_t i) const noexcept { return hits_[i]; }

private:
    std::array<Hit, MaxHits> hits_{};
};

/// Per-instance ShieldState lookup. The host pushes register/unregister
/// when ships are created/destroyed; the renderer's submit() walks the
/// registry each frame and draws the active ones.
class ShieldRegistry {
public:
    void register_instance(scenegraph::InstanceId id,
                           ShieldMode mode,
                           float decay_seconds,
                           const glm::vec4& default_color,
                           const glm::vec3& aabb_center,
                           const glm::vec3& aabb_half_extents);

    void unregister_instance(scenegraph::InstanceId id);

    /// Returns nullptr if instance is not registered.
    ShieldState* find(scenegraph::InstanceId id);
    const ShieldState* find(scenegraph::InstanceId id) const;

    /// Push a hit; silently drops if `id` was never registered.
    /// `texture_index` is picked from an internal stateless RNG.
    void push_hit(scenegraph::InstanceId id,
                  const glm::vec3& point_world,
                  const glm::vec4& rgba,
                  float intensity,
                  double now_seconds);

    /// Tick every registered state at `now_seconds`.
    void tick_all(double now_seconds);

    auto begin() { return states_.begin(); }
    auto end()   { return states_.end(); }
    auto begin() const { return states_.begin(); }
    auto end()   const { return states_.end(); }

private:
    std::unordered_map<scenegraph::InstanceId, ShieldState> states_;
};

}  // namespace renderer
