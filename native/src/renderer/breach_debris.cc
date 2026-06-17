#include <renderer/breach_debris.h>
#include <cmath>

namespace renderer {

std::vector<ParticleEmitterDescriptor> build_debris_descriptors(
    const scenegraph::BreachEventRing& ring,
    scenegraph::InstanceId             instance_id,
    float                              now) {

    std::vector<ParticleEmitterDescriptor> out;
    for (const auto& ev : ring.slots()) {
        if (!ev.active) continue;
        const float effect_age = now - ev.birth_time;
        if (effect_age >= scenegraph::kDebrisLife) continue;

        ParticleEmitterDescriptor d{};
        d.instance_id  = instance_id;
        d.emit_pos     = ev.center_body;  // body frame: breach center

        // Outward direction in body frame: use the stored surface normal.
        // Fall back to radial-from-origin, then +Y, if degenerate.
        d.emit_dir = (glm::length(ev.surface_normal) > 1e-4f)
            ? glm::normalize(ev.surface_normal)
            : ((glm::length(ev.center_body) > 1e-4f)
               ? glm::normalize(ev.center_body)
               : glm::vec3(0.f, 1.f, 0.f));

        d.emit_vel_world = glm::vec3(0.f);
        d.inherit        = 0.f;

        // Burst + long drift: emit densely for 0.6s, particles live 10s
        d.emit_life          = 10.0f;
        d.emit_life_variance = 2.0f;
        d.emit_frequency     = 0.02f;
        d.effect_age         = effect_age;
        d.stop_age           = 0.6f;

        // Explosive scatter
        d.emit_velocity         = 4.0f;
        d.random_velocity_cone  = 110.f;
        d.random_velocity_speed = 3.0f;
        d.angle_variance        = 40.f;
        d.damping               = 0.6f;

        // Tiny solid bits (alpha blend)
        d.blend_mode = 0;

        // Size: tiny -> slightly larger -> tiny again (solid chunk feel)
        d.num_size_keys = 3;
        d.size_keys[0] = ParticleKey{0.0f,  0.07f};
        d.size_keys[1] = ParticleKey{0.15f, 0.10f};
        d.size_keys[2] = ParticleKey{1.0f,  0.03f};

        // Alpha: hold solid then taper out
        d.num_alpha_keys = 3;
        d.alpha_keys[0] = ParticleKey{0.0f,  1.0f};
        d.alpha_keys[1] = ParticleKey{0.85f, 1.0f};
        d.alpha_keys[2] = ParticleKey{1.0f,  0.0f};

        // Color: hull-grey cooling from warm to cool grey
        // ParticleKey fields: {t, v, r, g, b} — v unused for colour keys
        d.num_color_keys = 2;
        d.color_keys[0] = ParticleKey{0.0f, 0.f, 0.45f, 0.38f, 0.32f};
        d.color_keys[1] = ParticleKey{1.0f, 0.f, 0.22f, 0.22f, 0.24f};

        // Stable seed: same derivation as venting but XOR'd differently so
        // debris and venting from the same event have distinct per-particle hashes.
        d.seed = static_cast<float>(
            ((ev.seed ^ 0x9e3779b97f4a7c15ull) ^ 0x517cc1b727220a95ull) >> 11)
            * (1.f / static_cast<float>(1ull << 53));

        d.texture_path = "game/data/square.tga";

        out.push_back(d);
    }
    return out;
}

} // namespace renderer
