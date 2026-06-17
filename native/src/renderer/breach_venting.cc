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
        d.emit_velocity  = 1.5f;           // GU / s (decorative; body-frame scale)
        d.angle_variance = 25.f;           // degrees: wispy jet spread
        d.emit_life      = 0.6f;           // each particle lives 0.6 s
        d.emit_life_variance = 0.2f;
        d.emit_frequency = 0.02f;          // 50 particles/s at start
        d.effect_age     = effect_age;
        d.stop_age       = scenegraph::kVentLife;
        d.blend_mode     = 1;              // additive: bright plasma
        d.random_velocity_cone  = 20.f;
        d.random_velocity_speed = 0.3f;

        // Alpha keys: 1.0 → 0.0 over particle lifetime.
        d.num_alpha_keys = 2;
        d.alpha_keys[0] = ParticleKey{0.f,  1.f};
        d.alpha_keys[1] = ParticleKey{1.f,  0.f};

        // Size keys: grow then shrink (wispy). Sizes are billboard half-extents
        // in world units (GU); a breach is ~0.5-1 GU, so ~0.3 GU peak reads as
        // a visible jet without swamping the hull. Eyeball-tunable.
        d.num_size_keys = 3;
        d.size_keys[0] = ParticleKey{0.0f, 0.10f};
        d.size_keys[1] = ParticleKey{0.4f, 0.30f};
        d.size_keys[2] = ParticleKey{1.0f, 0.06f};

        // Stable seed: derived from event seed, NOT from world position.
        // Convert uint64 seed to float in [0,1) as the pass expects.
        d.seed = static_cast<float>(
            (ev.seed ^ 0x517cc1b727220a95ull) >> 11)
            * (1.f / static_cast<float>(1ull << 53));

        // Soft noise puff for the venting plasma (additive). MUST be an existing,
        // non-atlas texture: the pass skips emitters whose texture fails to load,
        // and an 8x8 atlas (ExplosionA/B) would draw the whole sheet per particle.
        // (Prior value "ExplosionNoise.tga" did not exist → venting never drew.)
        d.texture_path = "game/data/Textures/Effects/Noise3.tga";

        out.push_back(d);
    }
    return out;
}

} // namespace renderer
