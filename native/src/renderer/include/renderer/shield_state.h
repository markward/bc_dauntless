// native/src/renderer/include/renderer/shield_state.h
#pragma once

#include <array>
#include <cstdint>
#include <cstddef>
#include <unordered_map>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>

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

/// Overall opacity ceiling on the impact splash — the brightness a fragment at
/// full coverage, from a hit at full intensity, contributes to the frame.
/// MUST match the constant in shaders/shield.frag.
inline constexpr float kShieldSplashOpacity = 0.75f;

// ── procedural 3D splash: reach ────────────────────────────────────────────

/// How far the ripple travels, per GU of the weapon's DamageRadiusFactor.
/// That factor is already plumbed to hit_feedback.dispatch (photon 0.13 GU,
/// phaser 0.15 GU) and is the natural "sized to the impact" basis, but against
/// a Galaxy's 1.22 GU thin semi-axis a raw 0.13 GU splash is invisible — hence
/// the multiplier.
inline constexpr float kShieldSplashReachPerRadius = 10.0f;

/// Floor on the reach, in GU. Callers with no ray — collisions, splash damage
/// — pass radius 0 and must still get a visible splash.
inline constexpr float kShieldSplashReachMin = 0.6f;

/// Ceiling on the reach, in GU. Keeps a freak DamageRadiusFactor from wrapping
/// the whole bubble.
inline constexpr float kShieldSplashReachMax = 2.0f;

/// Ripple reach in GU for a weapon whose DamageRadiusFactor is `radius_gu`.
/// MUST match shaders/shield.frag — keep in sync.
float shield_splash_reach(float radius_gu);

/// Upper bound on the reach, as a multiple of the bubble's radius in the hit
/// direction. The splash may not out-run the bubble it is drawn on.
inline constexpr float kShieldSplashReachBubbleFrac = 1.0f;

/// The reach actually used on a bubble whose radius in the hit direction is
/// `bubble_radius_gu`.
///
/// This is a CLAMP, not a proportional law — it does not resurrect "bigger
/// ships get bigger splashes", which is wrong and was rejected. On any hull
/// large enough to hold the splash it changes nothing at all; it binds only
/// when the splash would otherwise be bigger than the target.
///
/// Why it has to exist: the reach is absolute (0.6–2.0 GU) while the bubble
/// scales with the hull, so on a small target the splash stayed bright all the
/// way to the hemisphere gate's terminator. The terminator is a great circle,
/// which projects to a straight line, so the gate cut the splash into a dome
/// with a hard FLAT bottom — seen live on a small target. Measured brightness
/// at the terminator, as a fraction of the splash peak:
///
///     reach/semi   0.46    0.77    1.15    1.65    3.30
///     at terminator  0.0000  0.0014  0.0095  0.0209  0.0486
///
/// Capital ships were always fine; small targets were not. With the splash
/// bounded to the bubble it fades to well under 1% by the terminator, so the
/// gate has nothing left to cut and leaves no edge.
float shield_splash_reach_on_bubble(float reach_gu, float bubble_radius_gu);

// ── procedural 3D splash: epicentre ────────────────────────────────────────

/// The stored anchor projected onto the bubble surface, in world space.
///
/// `hit_feedback` passes the bubble ENTRY point when the shot had a ray and
/// the HULL impact point when it did not (collisions, splash damage). The
/// bubble stands √3 off the hull — 2.36 GU on a Galaxy's long axis — so a raw
/// hull anchor sits deep inside it. Projecting whatever arrives onto the
/// ellipsoid normalises both callers to one anchor, which is what makes a
/// world-space distance from it mean anything.
///
/// Returns `bubble_centre` unchanged for a degenerate hit at the centre; a NaN
/// here would reach the HDR bloom amplifier. MUST match shaders/shield.frag.
glm::vec3 shield_splash_epicentre(const glm::vec3& hit_world,
                                  const glm::vec3& bubble_centre,
                                  const glm::vec3& bubble_semi_axes);

// ── procedural 3D splash: the ripple itself ────────────────────────────────

/// How long the ripple geometry takes to run, in seconds. Deliberately much
/// shorter than the hit's own ~3.9 s intensity decay: the rings are a fast
/// water-splash event, the residual glow is the slow one. See
/// shield_splash_shape().
inline constexpr float kShieldSplashRippleLife = 0.70f;

/// Ring wavelength as a fraction of the reach — 1/3 gives about three crests.
inline constexpr float kShieldSplashRingLambda = 1.0f / 3.0f;

/// How far the ring packet trails BEHIND the wavefront, as a fraction of the
/// reach. The rings are a wave packet centred on the front, not on the impact.
///
/// They were originally enveloped by the filled disc, which is
/// `1 - smoothstep(0, front, d)` and so exactly 0 at d == front — the crest
/// riding the wavefront was multiplied by zero and the splash's brightest
/// point never left the epicentre. It read live as a static flash rather than
/// an expanding ripple.
inline constexpr float kShieldSplashRingTrail = 0.35f;

/// How far the packet leaks AHEAD of the wavefront, as a fraction of the
/// reach. Much smaller than the trail: the leading edge should be crisp, but
/// not a hard step, which would alias as the front sweeps across fragments.
inline constexpr float kShieldSplashRingLead = 0.05f;
/// Crest sharpness. Higher = thinner, harder-edged rings.
inline constexpr float kShieldSplashRingSharp = 3.0f;
/// How fast the filled disc dims outward, as a fraction of the reach.
inline constexpr float kShieldSplashDiscDecay = 0.55f;
/// Core radius as a fraction of the reach.
inline constexpr float kShieldSplashCoreFrac = 0.18f;

/// How long the hot core lasts, in seconds — its OWN timescale, much shorter
/// than the ripple's.
///
/// The core originally decayed over kShieldSplashRippleLife, so at 4x the ring
/// gain it stayed the brightest thing until ~65% through the ripple, and by
/// the time the travelling crest won it was faint. The expanding ring was
/// there and correct; the impact flash was sitting on top of it. Three
/// timescales now, each a distinct visual event: this flash, the 0.7 s ripple,
/// and the hit's own ~3.9 s intensity decay carrying the afterglow.
inline constexpr float kShieldSplashCoreLife = 0.15f;

/// Core temporal falloff exponent — how abruptly the hot centre dies.
inline constexpr float kShieldSplashCorePow = 3.0f;
/// Core peak gain. ABOVE 1 ON PURPOSE: this is the term that drives the HDR
/// bloom, which a texture sample capped at 1.0 never could.
inline constexpr float kShieldSplashCoreGain = 4.0f;
/// Afterglow radius as a fraction of the reach.
inline constexpr float kShieldSplashGlowFrac = 0.70f;
/// Afterglow gain.
inline constexpr float kShieldSplashGlowGain = 0.25f;
/// Filled-disc gain.
inline constexpr float kShieldSplashDiscGain = 0.45f;
/// Ring gain.
inline constexpr float kShieldSplashRingGain = 0.9f;

/// The splash profile: brightness at world distance `d_gu` from the epicentre,
/// `age_seconds` after the hit, for a ripple of `reach_gu`. `phase_jitter` in
/// [0,1) offsets the ring phase so repeated hits don't look rubber-stamped.
///
/// This is the whole visual. It is a function of a SCALAR DISTANCE, which is
/// the point: the previous implementation built a tangent basis at the impact
/// and projected the 3D offset onto it to sample a 2D texture, and every one
/// of its three distortions came from needing that 2D map —
///
///  * the tangent-plane projection itself;
///  * measuring the footprint in the bubble's unit-sphere space, which is
///    isotropic in ANGLE but maps back to wildly different world sizes on a
///    4.02/5.58/1.22 GU bubble — the same 18° spanned 0.43 GU toward the
///    dorsal and 1.74 GU toward the bow;
///  * and a `ref` vector that flipped from (0,0,1) to (0,1,0) at |n.z| = 0.9,
///    rotating the texture arbitrarily and POPPING as a hit tracked across.
///
/// A radially symmetric ripple needs none of it. Four additive terms:
///
///   core  hot Gaussian at the epicentre, dies within the ripple life
///   disc  soft filled cap that grows out to the expanding front
///   rings travelling wave crests, gated BY the disc so nothing rings ahead
///         of the front
///   glow  broad afterglow with NO age term — it fades on the hit's own
///         intensity decay instead, which is what gives the two timescales
///
/// Output is NOT clamped to 1: see kShieldSplashCoreGain.
/// MUST match splash_shape() in shaders/shield.frag — keep in sync.
float shield_splash_shape(float d_gu, float age_seconds, float reach_gu,
                          float phase_jitter);

/// Brightness one splash contributes to the frame, given its `coverage`
/// (shield_splash_coverage × the texture's alpha) and the hit's current
/// `intensity`. LINEAR in both — that is the whole point.
///
/// shield.frag used to fold coverage, intensity and the texture into BOTH the
/// colour and the alpha, and shield_pass blended with
/// glBlendFunc(GL_SRC_ALPHA, GL_ONE), which multiplies rgb by alpha — so every
/// term reached the framebuffer SQUARED. Against the real shieldhit01.TGA
/// radial profile that put peak output at 0.64% of full brightness, which read
/// in game as "the impacts are there but very faint". Applied once it is 6.93%.
/// The pass now blends GL_ONE, GL_ONE with a premultiplied colour.
float shield_splash_intensity(float coverage, float hit_intensity);

/// Width of the smooth terminator on the hemisphere gate, in units of
/// cos(angle) away from the terminator plane. Small enough to stay a localised
/// splash, wide enough that the cutoff is not a hard seam.
inline constexpr float kShieldSplashGateFeather = 0.25f;

/// Coverage of one impact splash at a point on the bubble — the hemisphere
/// gate times the ripple profile at that point's WORLD distance from the
/// epicentre.
///
/// NOT capped at 1: the hot core exceeds it on purpose, which is how the
/// splash reaches the HDR bloom. See kShieldSplashCoreGain.
///
/// All vectors are WORLD space, in GU; `frag_world` is expected to lie on the
/// bubble surface (the pass draws a unit sphere scaled to `bubble_semi_axes`).
/// `age_seconds` is measured from the hit, `reach_gu` comes from
/// shield_splash_reach(), and `phase_jitter` in [0,1) varies the ring phase
/// per hit.
///
/// The gate stays in the bubble's unit-sphere space because it is an
/// orientation question, not a distance one. Everything else is a plain
/// Euclidean distance, which is what makes the splash the same size wherever
/// it lands — see the block comment on shield_splash_shape().
///
/// This is the shared source of truth for the splash. MUST match
/// splash_sample() in shaders/shield.frag — keep in sync.
float shield_splash_coverage(const glm::vec3& frag_world,
                             const glm::vec3& hit_world,
                             const glm::vec3& bubble_centre,
                             const glm::vec3& bubble_semi_axes,
                             float age_seconds,
                             float reach_gu,
                             float phase_jitter);

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
    /// Impact point in the ship's BODY (model) frame. Stored in body space and
    /// re-transformed by the live instance matrix every frame — the same thing
    /// hit_vfx_pass.cc does for spark bursts — so the splash rides the hull.
    ///
    /// It was a WORLD point, handed to the shader verbatim while
    /// u_bubble_center tracked the ship, so `hit - centre` swung as the ship
    /// flew and eventually inverted: the splash slid across the bubble and
    /// reappeared on the far face. On a Galaxy the hit sits ~1.83 GU from the
    /// bubble centre, so at 6.3 GU/s the direction passed 90 degrees after
    /// 0.29 s, while the splash lives 3.9 s (ShieldGlowDecay 1.0, seed
    /// intensity 0.5, inactive at 0.01).
    glm::vec3 point_body{0.0f};
    glm::vec4 color_rgba{0.0f};
    float intensity_at_t0 = 0.0f;
    float current_intensity = 0.0f;
    double t0_seconds = 0.0;

    /// The weapon's DamageRadiusFactor in GU (photon 0.13, phaser 0.15), which
    /// sizes the splash via shield_splash_reach(). 0 for callers with no
    /// weapon — collisions, splash damage — which clamps to the reach floor.
    float radius_gu = 0.0f;

    /// Was an index into the four shieldhit0*.TGA variants; those are gone and
    /// it now seeds the ring-phase jitter, serving the same "per-hit variety"
    /// purpose procedurally.
    int texture_index = 0;
};

/// Where a stored hit is right now, in world space: its body-frame point
/// carried through the instance's live world matrix. The shader compares this
/// against v_world_pos, so it must be recomputed every frame rather than
/// cached at push time.
glm::vec3 shield_hit_world_point(const Hit& hit,
                                 const glm::mat4& instance_world);

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
    void push_hit(const glm::vec3& point_body,
                  const glm::vec4& rgba,
                  float intensity,
                  double now_seconds,
                  int texture_index,
                  float radius_gu = 0.0f);

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
                  const glm::vec3& point_body,
                  const glm::vec4& rgba,
                  float intensity,
                  double now_seconds,
                  float radius_gu = 0.0f);

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
