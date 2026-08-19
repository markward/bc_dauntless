// native/src/renderer/shield_state.cc
#include "renderer/shield_state.h"

#include <algorithm>
#include <cmath>

namespace renderer {

namespace {
constexpr float kInactive = 0.01f;
constexpr glm::vec4 kZero(0.0f);

// GLSL smoothstep, so the CPU gate and the shader agree bit-for-shape.
float smoothstep01(float edge0, float edge1, float x) {
    if (edge1 <= edge0) return x < edge0 ? 0.0f : 1.0f;
    const float t = std::clamp((x - edge0) / (edge1 - edge0), 0.0f, 1.0f);
    return t * t * (3.0f - 2.0f * t);
}
}  // namespace

float shield_splash_intensity(float coverage, float hit_intensity) {
    return coverage * hit_intensity * kShieldSplashOpacity;
}

float shield_splash_reach(float radius_gu) {
    return std::clamp(radius_gu * kShieldSplashReachPerRadius,
                      kShieldSplashReachMin, kShieldSplashReachMax);
}

float shield_splash_reach_on_bubble(float reach_gu, float bubble_radius_gu) {
    if (bubble_radius_gu <= 0.0f) return reach_gu;
    return std::min(reach_gu, kShieldSplashReachBubbleFrac * bubble_radius_gu);
}

glm::vec3 shield_splash_epicentre(const glm::vec3& hit_world,
                                  const glm::vec3& bubble_centre,
                                  const glm::vec3& bubble_semi_axes) {
    if (bubble_semi_axes.x <= 0.0f || bubble_semi_axes.y <= 0.0f ||
        bubble_semi_axes.z <= 0.0f)
        return bubble_centre;
    // Into unit-sphere space, normalise, back out. Only the DIRECTION of the
    // anchor survives, which is exactly what makes a hull point and a bubble
    // entry point resolve to the same epicentre.
    const glm::vec3 n = (hit_world - bubble_centre) / bubble_semi_axes;
    const float len = glm::length(n);
    if (len < 1e-6f) return bubble_centre;   // hit at the centre: no direction
    return bubble_centre + (n / len) * bubble_semi_axes;
}

float shield_splash_shape(float d_gu, float age_seconds, float reach_gu,
                          float phase_jitter) {
    if (reach_gu <= 0.0f) return 0.0f;
    const float d = std::max(d_gu, 0.0f);
    const float a = std::clamp(age_seconds / kShieldSplashRippleLife, 0.0f, 1.0f);

    // Wavefront radius. sqrt(a) so it bursts outward and then slows, the way a
    // real surface wave does — a linear front reads as a mechanical sweep.
    const float front = reach_gu * std::sqrt(a);

    // Filled disc out to the front, dimming with distance and with age.
    // max() on the edge because smoothstep with edge0 == edge1 is undefined in
    // GLSL, and at a == 0 the front IS zero.
    float disc = 1.0f - smoothstep01(0.0f, std::max(front, 1e-4f), d);
    disc *= std::exp(-d / (reach_gu * kShieldSplashDiscDecay));
    disc *= (1.0f - a);

    // Travelling crests, enveloped as a wave PACKET centred on the front.
    //
    // They used to be enveloped by `disc` instead, which is
    // `1 - smoothstep(0, front, d)` and therefore exactly 0 at d == front: the
    // crest riding the wavefront — the whole thing that reads as motion — was
    // multiplied by zero, and the splash's peak never left the epicentre. It
    // rendered as a static flash with some texture on it.
    //
    // The packet is ASYMMETRIC: a long trailing decay behind the front, and a
    // very short one ahead, so the leading edge stays crisp without being a
    // hard step that would alias.
    const float behind = front - d;              // > 0 behind the front
    const float width = (behind >= 0.0f) ? kShieldSplashRingTrail
                                         : kShieldSplashRingLead;
    const float bt = behind / (reach_gu * width);
    const float band = std::exp(-bt * bt);

    const float phase = (front - d) / (reach_gu * kShieldSplashRingLambda)
                        + phase_jitter;
    const float crest = std::max(std::cos(6.2831853f * phase), 0.0f);
    const float rings =
        std::pow(crest, kShieldSplashRingSharp) * band * (1.0f - a);

    // Hot core. Exceeds 1 on purpose — this is what the bloom sees. Decays on
    // its OWN short life, not the ripple's: sharing the ripple's clock left
    // the flash brighter than the travelling crest for two thirds of the
    // ripple, hiding the very motion the rings exist to convey.
    const float ca = std::clamp(age_seconds / kShieldSplashCoreLife, 0.0f, 1.0f);
    const float cr = d / (reach_gu * kShieldSplashCoreFrac);
    const float core = std::exp(-cr * cr)
                     * std::pow(1.0f - ca, kShieldSplashCorePow)
                     * kShieldSplashCoreGain;

    // Afterglow. NO age term: it fades on the hit's own intensity decay, which
    // the caller applies. That split is the two timescales.
    const float gr = d / (reach_gu * kShieldSplashGlowFrac);
    const float glow = std::exp(-gr * gr);

    return core
         + disc * kShieldSplashDiscGain
         + rings * kShieldSplashRingGain
         + glow * kShieldSplashGlowGain;
}

float shield_splash_gate(const glm::vec3& frag_dir_from_centre,
                         const glm::vec3& impact_dir) {
    return smoothstep01(0.0f, kShieldSplashGateFeather,
                        glm::dot(frag_dir_from_centre, impact_dir));
}

float shield_splash_coverage(const glm::vec3& frag_world,
                             const glm::vec3& hit_world,
                             const glm::vec3& bubble_centre,
                             const glm::vec3& bubble_semi_axes,
                             float age_seconds,
                             float reach_gu,
                             float phase_jitter) {
    if (bubble_semi_axes.x <= 0.0f || bubble_semi_axes.y <= 0.0f ||
        bubble_semi_axes.z <= 0.0f)
        return 0.0f;

    // The gate is an ORIENTATION question — near side or far side — so it
    // stays in unit-sphere space, where the bubble is a sphere and "same
    // hemisphere" is just a dot product. It survives the rebuild because a
    // world distance is a straight chord: on a hull whose bubble is thinner
    // than the reach, the far side is genuinely within range.
    glm::vec3 n_hit = (hit_world - bubble_centre) / bubble_semi_axes;
    glm::vec3 n_frag = (frag_world - bubble_centre) / bubble_semi_axes;
    const float lh = glm::length(n_hit);
    const float lf = glm::length(n_frag);
    if (lh < 1e-4f || lf < 1e-4f) return 0.0f;
    n_hit /= lh;
    n_frag /= lf;

    const float gate = shield_splash_gate(n_frag, n_hit);
    if (gate <= 0.0f) return 0.0f;

    // Everything else is a plain world distance from the epicentre. No basis,
    // no uv, no projection — which is the whole reason the splash is now the
    // same size and shape wherever it lands.
    // BOTH endpoints go onto the bubble before the distance is measured.
    //
    // Projecting only the hit assumes the fragment is already on the ellipsoid,
    // which holds in Ellipsoid mode but NOT in Skin mode, where the fragments
    // are the ship's own hull verts at roughly 1/√3 of the bubble's radius. On
    // a Sovereign that left every hull fragment 2.56 GU from its own epicentre
    // — beyond even the maximum reach — so skin-shielded ships (Akira,
    // Sovereign) showed no splash at all. The old angular measure compared pure
    // directions and never cared how far out the fragment was.
    //
    // In Ellipsoid mode the fragment is already on the surface, so projecting
    // it is a no-op and the behaviour is unchanged.
    const glm::vec3 epi_hit =
        shield_splash_epicentre(hit_world, bubble_centre, bubble_semi_axes);
    const glm::vec3 epi_frag =
        shield_splash_epicentre(frag_world, bubble_centre, bubble_semi_axes);

    // Bound the reach to the bubble's radius in the hit direction, so the
    // splash always fades out before the gate's terminator and never gets cut
    // into a hard-edged dome. Binds only on targets smaller than the splash.
    const float reach = shield_splash_reach_on_bubble(
        reach_gu, glm::length(epi_hit - bubble_centre));
    const float d = glm::length(epi_frag - epi_hit);
    return shield_splash_shape(d, age_seconds, reach, phase_jitter) * gate;
}

glm::vec3 shield_hit_world_point(const Hit& hit,
                                 const glm::mat4& instance_world) {
    return glm::vec3(instance_world * glm::vec4(hit.point_body, 1.0f));
}

void ShieldState::push_hit(const glm::vec3& point_body,
                           const glm::vec4& rgba,
                           float intensity,
                           double now_seconds,
                           int texture_index,
                           float radius_gu) {
    // Find first empty slot; if all occupied, target the dimmest.
    std::size_t target = 0;
    bool found_empty = false;
    float min_intensity = hits_[0].current_intensity;
    for (std::size_t i = 0; i < MaxHits; ++i) {
        if (hits_[i].current_intensity < kInactive) {
            target = i;
            found_empty = true;
            break;
        }
        if (hits_[i].current_intensity < min_intensity) {
            min_intensity = hits_[i].current_intensity;
            target = i;
        }
    }
    (void)found_empty;
    glm::vec4 color = (rgba == kZero) ? default_color : rgba;
    hits_[target] = Hit{
        .point_body = point_body,
        .color_rgba = color,
        .intensity_at_t0 = intensity,
        .current_intensity = intensity,
        .t0_seconds = now_seconds,
        .radius_gu = radius_gu,
        .texture_index = texture_index,
    };
}

void ShieldState::tick(double now_seconds) {
    for (auto& h : hits_) {
        if (h.intensity_at_t0 <= 0.0f) continue;
        float dt = static_cast<float>(now_seconds - h.t0_seconds);
        h.current_intensity = h.intensity_at_t0 * std::exp(-dt / decay_seconds);
        if (h.current_intensity < kInactive) {
            h.current_intensity = 0.0f;
            h.intensity_at_t0 = 0.0f;
        }
    }
}

std::size_t ShieldState::active_count() const noexcept {
    std::size_t n = 0;
    for (const auto& h : hits_) if (h.current_intensity >= kInactive) ++n;
    return n;
}

// ── ShieldRegistry ─────────────────────────────────────────────────────────

void ShieldRegistry::register_instance(scenegraph::InstanceId id,
                                        ShieldMode mode,
                                        float decay_seconds,
                                        const glm::vec4& default_color,
                                        const glm::vec3& aabb_center,
                                        const glm::vec3& aabb_half_extents) {
    auto& s = states_[id];
    s.mode = mode;
    s.decay_seconds = decay_seconds;
    s.default_color = default_color;
    s.aabb_center = aabb_center;
    s.aabb_half_extents = aabb_half_extents;
}

void ShieldRegistry::unregister_instance(scenegraph::InstanceId id) {
    states_.erase(id);
}

ShieldState* ShieldRegistry::find(scenegraph::InstanceId id) {
    auto it = states_.find(id);
    return it == states_.end() ? nullptr : &it->second;
}

const ShieldState* ShieldRegistry::find(scenegraph::InstanceId id) const {
    auto it = states_.find(id);
    return it == states_.end() ? nullptr : &it->second;
}

void ShieldRegistry::push_hit(scenegraph::InstanceId id,
                               const glm::vec3& point_body,
                               const glm::vec4& rgba,
                               float intensity,
                               double now_seconds,
                               float radius_gu) {
    auto* s = find(id);
    if (!s) return;
    // Ring-phase jitter seed from a thread-local LCG. Stateless across registry
    // calls but ticks remain deterministic (no per-frame randomization).
    static thread_local std::uint32_t rng = 0x12345678u;
    rng = rng * 1664525u + 1013904223u;
    int tex = static_cast<int>(rng >> 30);  // 0..3
    s->push_hit(point_body, rgba, intensity, now_seconds, tex, radius_gu);
}

void ShieldRegistry::tick_all(double now_seconds) {
    for (auto& [id, s] : states_) s.tick(now_seconds);
}

}  // namespace renderer
