#include <renderer/breach_debris.h>

namespace renderer {

// Per active breach event we emit TWO billboard emitters that share the breach
// origin/direction but read very differently:
//   [0] hull chunks — a few grey SQUARE bits, alpha-blended, drift+fade ~10s.
//   [1] sparks       — a few bright ORANGE glints, additive, fast, burn out ~2.5s.
// Both are fewer-element bursts (toned down from the original single dense spray).
std::vector<ParticleEmitterDescriptor> build_debris_descriptors(
    const scenegraph::BreachEventRing& ring,
    scenegraph::InstanceId             instance_id,
    float                              now) {

    std::vector<ParticleEmitterDescriptor> out;
    for (const auto& ev : ring.slots()) {
        if (!ev.active) continue;
        const float effect_age = now - ev.birth_time;
        if (effect_age >= scenegraph::kDebrisLife) continue;

        // Outward direction in body frame: stored surface normal, with fallbacks.
        const glm::vec3 dir = (glm::length(ev.surface_normal) > 1e-4f)
            ? glm::normalize(ev.surface_normal)
            : ((glm::length(ev.center_body) > 1e-4f)
               ? glm::normalize(ev.center_body)
               : glm::vec3(0.f, 1.f, 0.f));

        // Seed scaled to [0,1) from the event seed. Each emitter XORs a distinct
        // constant so chunks, sparks, and the venting jet don't co-move.
        const auto seed01 = [](std::uint64_t s) {
            return static_cast<float>(s >> 11)
                 * (1.f / static_cast<float>(1ull << 53));
        };

        // ── [0] Hull chunks (square.tga, alpha) ────────────────────────────
        {
            ParticleEmitterDescriptor d{};
            d.instance_id    = instance_id;
            d.emit_pos       = ev.center_body;
            d.emit_dir       = dir;
            d.emit_vel_world = glm::vec3(0.f);
            d.inherit        = 0.f;
            d.effect_age     = effect_age;
            // ~8 chunks over a 0.4s burst, each living ~10s.
            d.emit_life          = 10.0f;
            d.emit_life_variance = 2.0f;
            d.emit_frequency     = 0.05f;
            d.stop_age           = 0.4f;
            d.emit_velocity         = 4.0f;
            d.random_velocity_cone  = 110.f;
            d.random_velocity_speed = 3.0f;
            d.angle_variance        = 40.f;
            d.damping               = 0.6f;
            d.blend_mode = 0;  // alpha: solid chunks
            d.num_size_keys = 3;
            d.size_keys[0] = ParticleKey{0.0f,  0.07f};
            d.size_keys[1] = ParticleKey{0.15f, 0.10f};
            d.size_keys[2] = ParticleKey{1.0f,  0.03f};
            d.num_alpha_keys = 3;
            d.alpha_keys[0] = ParticleKey{0.0f,  1.0f};
            d.alpha_keys[1] = ParticleKey{0.85f, 1.0f};
            d.alpha_keys[2] = ParticleKey{1.0f,  0.0f};
            d.num_color_keys = 2;  // warm grey -> cool grey
            d.color_keys[0] = ParticleKey{0.0f, 0.f, 0.45f, 0.38f, 0.32f};
            d.color_keys[1] = ParticleKey{1.0f, 0.f, 0.22f, 0.22f, 0.24f};
            d.seed = seed01((ev.seed ^ 0x9e3779b97f4a7c15ull)
                                    ^ 0x517cc1b727220a95ull);
            d.texture_path = "game/data/square.tga";
            out.push_back(d);
        }

        // ── [1] Sparks (spark.tga, additive, bright orange) ────────────────
        {
            ParticleEmitterDescriptor d{};
            d.instance_id    = instance_id;
            d.emit_pos       = ev.center_body;
            d.emit_dir       = dir;
            d.emit_vel_world = glm::vec3(0.f);
            d.inherit        = 0.f;
            d.effect_age     = effect_age;
            // ~5 sparks in a quick burst; they burn out faster than chunks.
            d.emit_life          = 2.5f;
            d.emit_life_variance = 1.0f;
            d.emit_frequency     = 0.06f;
            d.stop_age           = 0.3f;
            d.emit_velocity         = 6.0f;   // sparks fly fast
            d.random_velocity_cone  = 130.f;
            d.random_velocity_speed = 4.0f;
            d.angle_variance        = 50.f;
            d.damping               = 0.5f;
            d.blend_mode = 1;  // additive: bright glow
            d.num_size_keys = 3;
            d.size_keys[0] = ParticleKey{0.0f, 0.05f};
            d.size_keys[1] = ParticleKey{0.2f, 0.08f};
            d.size_keys[2] = ParticleKey{1.0f, 0.01f};
            d.num_alpha_keys = 2;
            d.alpha_keys[0] = ParticleKey{0.0f, 1.0f};
            d.alpha_keys[1] = ParticleKey{1.0f, 0.0f};
            d.num_color_keys = 2;  // hot orange -> cooling red (additive = bright)
            d.color_keys[0] = ParticleKey{0.0f, 0.f, 1.0f, 0.55f, 0.12f};
            d.color_keys[1] = ParticleKey{1.0f, 0.f, 0.7f, 0.18f, 0.02f};
            d.seed = seed01((ev.seed ^ 0xa24baed4963ee407ull)
                                    ^ 0x2545f4914f6cdd1dull);
            d.texture_path = "game/data/spark.tga";
            out.push_back(d);
        }
    }
    return out;
}

} // namespace renderer
