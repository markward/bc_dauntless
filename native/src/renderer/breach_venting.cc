#include <renderer/breach_venting.h>
#include <cmath>

namespace renderer {

std::vector<ParticleEmitterDescriptor> build_venting_descriptors(
    const scenegraph::BreachEventRing& ring,
    scenegraph::InstanceId             instance_id,
    float                              now) {

    std::vector<ParticleEmitterDescriptor> out;
    for (const auto& ev : ring.slots()) {
        if (!ev.active) continue;
        const float effect_age = now - ev.birth_time;
        if (effect_age >= scenegraph::kVentLife) continue;

        ParticleEmitterDescriptor d{};
        d.instance_id  = instance_id;
        d.emit_pos     = ev.center_body;  // body frame: breach center

        // Outward direction in body frame: use the stored surface normal, which
        // was derived from the actual hull geometry at impact (accurate for flat
        // saucer tops, fins, etc.). Fall back to the radial-from-origin direction
        // if the stored normal is degenerate (should not occur in practice).
        d.emit_dir = (glm::length(ev.surface_normal) > 1e-4f)
            ? glm::normalize(ev.surface_normal)
            : ((glm::length(ev.center_body) > 1e-4f)
               ? glm::normalize(ev.center_body)
               : glm::vec3(0.f, 1.f, 0.f));

        d.emit_vel_world = glm::vec3(0.f); // no ship-velocity inheritance for venting
        d.inherit        = 0.f;
        d.emit_velocity  = 3.5f;           // GU / s — fast outward gas blow-out
        d.angle_variance = 35.f;           // degrees: gas spreads as it escapes
        d.emit_life      = 0.4f;           // short-lived: gas disperses quickly
        d.emit_life_variance = 0.15f;
        d.emit_frequency = 0.035f;         // ~29/s over the 0.5s window ≈ a brief puff
        d.effect_age     = effect_age;
        d.stop_age       = scenegraph::kVentLife;
        d.blend_mode     = 1;              // additive: bright plasma
        d.random_velocity_cone  = 30.f;
        d.random_velocity_speed = 0.6f;    // extra outward scatter for the blow-out

        // Alpha keys: 1.0 → 0.0 over particle lifetime.
        d.num_alpha_keys = 2;
        d.alpha_keys[0] = ParticleKey{0.f,  1.f};
        d.alpha_keys[1] = ParticleKey{1.f,  0.f};

        // Colour keys: escaping plasma cooling white-blue → blue → dark, on the
        // same arc as the molten rim's blackbody ramp over kRimLife, so the whole
        // breach cools as one event. WITHOUT these, num_color_keys stays 0 and
        // curve_lerp1 returns 1.0 for n<=0 (particle_math.h) — a pure white tint,
        // which is what made the jet a featureless additive flare. The front sits
        // above 1.0 deliberately: the HDR chain blooms it. Tune-by-eye.
        // NOTE ParticleKey's member order is {t, v, r, g, b} — the second
        // initialiser is the unused `v` slot for a colour key.
        d.num_color_keys = 3;
        d.color_keys[0] = ParticleKey{0.00f, 0.f, 1.30f, 1.60f, 2.20f};
        d.color_keys[1] = ParticleKey{0.35f, 0.f, 0.30f, 0.55f, 1.00f};
        d.color_keys[2] = ParticleKey{1.00f, 0.f, 0.05f, 0.09f, 0.22f};

        // Size keys: grow then shrink (wispy). Sizes are billboard half-extents
        // in world units (GU); a breach is ~0.5-1 GU, so ~0.3 GU peak reads as
        // a visible jet without swamping the hull. Eyeball-tunable.
        d.num_size_keys = 3;
        d.size_keys[0] = ParticleKey{0.0f, 0.08f};
        d.size_keys[1] = ParticleKey{0.4f, 0.18f};
        d.size_keys[2] = ParticleKey{1.0f, 0.04f};

        // Stable seed: derived from event seed, NOT from world position.
        // Convert uint64 seed to float in [0,1) as the pass expects.
        d.seed = static_cast<float>(
            (ev.seed ^ 0x517cc1b727220a95ull) >> 11)
            * (1.f / static_cast<float>(1ull << 53));

        // Soft puff for the venting plasma (additive). Three invariants, each
        // learned from a real bug:
        //  1. MUST exist — the pass silently skips emitters whose texture fails
        //     to load, so a typo'd path means venting never draws and nothing
        //     complains ("ExplosionNoise.tga" did exactly that).
        //  2. MUST NOT be an atlas — an 8x8 sheet (ExplosionA/B) would billboard
        //     the whole grid per particle.
        //  3. MUST fade to alpha ~0 at its border. Sprite shape comes 100% from
        //     the alpha channel (hit_vfx.frag has no radial mask), so a texture
        //     whose alpha runs edge-to-edge draws a hard SQUARE. The prior value
        //     Noise3.tga is the viewscreen-static asset: alpha noise with border
        //     mean 125.8 vs centre 122.2 — no falloff, so every vent particle was
        //     a square of TV static. rough.tga measures 0.6 border / 234.3 centre.
        d.texture_path = "game/data/rough.tga";

        out.push_back(d);
    }
    return out;
}

} // namespace renderer
