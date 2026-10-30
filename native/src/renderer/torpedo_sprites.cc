// native/src/renderer/torpedo_sprites.cc -- see renderer/torpedo_sprites.h.
#include "renderer/torpedo_sprites.h"

#include "renderer/torpedo_anim.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>

namespace renderer {

namespace {

// Frustum planes (Gribb-Hartmann) of a column-vector view-projection, each
// normalised so dot(n, p) + d is a signed world distance (inside >= 0).
std::array<glm::vec4, 6> frustum_planes(const glm::mat4& m) {
    const glm::vec4 r0(m[0][0], m[1][0], m[2][0], m[3][0]);
    const glm::vec4 r1(m[0][1], m[1][1], m[2][1], m[3][1]);
    const glm::vec4 r2(m[0][2], m[1][2], m[2][2], m[3][2]);
    const glm::vec4 r3(m[0][3], m[1][3], m[2][3], m[3][3]);
    std::array<glm::vec4, 6> planes{r3 + r0, r3 - r0, r3 + r1, r3 - r1, r3 + r2, r3 - r2};
    for (auto& p : planes) {
        const float len = glm::length(glm::vec3(p));
        if (len > 0.0f) p /= len;
    }
    return planes;
}

bool sphere_outside(const std::array<glm::vec4, 6>& planes, const glm::vec3& c, float r) {
    for (const auto& p : planes)
        if (glm::dot(glm::vec3(p), c) + p.w < -r) return true;
    return false;
}

std::size_t batch_for(std::vector<TorpedoSpriteBatch>& batches, const std::string& texture) {
    for (std::size_t i = 0; i < batches.size(); ++i)
        if (batches[i].texture == texture) return i;
    batches.push_back({texture, {}});
    return batches.size() - 1;
}

}  // namespace

void build_torpedo_sprites(const std::vector<TorpedoDescriptor>& torpedoes,
                           const glm::vec3& cam_pos,
                           const glm::vec3& cam_up_world,
                           const glm::mat4& view_proj,
                           std::vector<TorpedoSpriteBatch>& batches) {
    for (auto& b : batches) b.sprites.clear();
    const auto planes = frustum_planes(view_proj);

    // The three textures of the previous torpedo: consecutive torpedoes are
    // almost always one type, so this skips the batch lookup. An index, not a
    // pointer: a new texture's batch can reallocate `batches`.
    const std::string* last_path[3] = {nullptr, nullptr, nullptr};
    std::size_t last_batch[3] = {0, 0, 0};
    auto sprites_for = [&](int slot, const std::string& path) {
        if (last_path[slot] == nullptr || *last_path[slot] != path) {
            last_batch[slot] = batch_for(batches, path);
            last_path[slot] = &path;
        }
        return &batches[last_batch[slot]].sprites;
    };
    // A layer is skipped exactly when the old per-quad draw_layer skipped it.
    auto layer = [&](int slot, const std::string& path, const glm::vec4& color, float size,
                     const glm::vec3& pos, const glm::vec3& axis_x, const glm::vec3& axis_y,
                     float alpha) {
        if (path.empty() || size <= 0.0f) return;
        sprites_for(slot, path)->push_back({glm::vec4(pos, size), glm::vec4(axis_x, alpha),
                                            glm::vec4(axis_y, 0.0f), color});
    };

    for (const auto& t : torpedoes) {
        if (t.is_disruptor) continue;

        const auto p = map_torpedo_params(t);
        const float pulse_half_size = 0.5f * glow_pulse_scale(
            t.age, p.pulse_rate, p.scale_lo, p.scale_hi);

        // Every quad's corners lie within sqrt(2) half-sizes of the centre:
        // its axes are unit (the flare's x axis is shorter still).
        float reach = std::max({pulse_half_size, 0.5f * p.clone_scale, p.core_half_size});
        if (t.num_flares > 0) reach = std::max(reach, p.flare_half_size);
        if (sphere_outside(planes, t.world_pos, reach * 1.5f)) continue;

        const glm::mat3 root3 = torpedo_root_frame(
            cam_pos, t.world_pos, cam_up_world, t.age, p.spin_rate);
        const glm::vec3 x_r = root3[0];
        const glm::vec3 y_r = root3[1];

        // Glow quad A (animated) and B (fixed clone): alpha 1.2 is BC's two
        // emissive passes summed (see torpedo_pass.cc).
        layer(0, t.glow_texture, t.glow_color, pulse_half_size, t.world_pos, x_r, y_r, 1.2f);
        layer(0, t.glow_texture, t.glow_color, 0.5f * p.clone_scale, t.world_pos, x_r, y_r, 1.2f);

        for (int i = 0; i < t.num_flares; ++i) {
            const glm::mat3 quad_basis = flare_basis(
                root3, static_cast<uint32_t>(t.id), static_cast<uint32_t>(i));
            float alpha = 1.0f;
            if (p.flare_period > 0.0f) {
                const float phi = hash01(static_cast<uint32_t>(t.id),
                                         static_cast<uint32_t>(i), 1u);
                const float u = std::fmod(t.age / p.flare_period + phi, 1.0f);
                alpha = flare_trapezoid(u);
            }
            if (alpha <= 0.0f) continue;
            layer(1, t.flares_texture, t.flares_color, p.flare_half_size, t.world_pos,
                  quad_basis[0] * torpedo_anim_detail::kFlareAspect, quad_basis[1], alpha);
        }

        layer(2, t.core_texture, t.core_color, p.core_half_size, t.world_pos, x_r, y_r, 1.0f);
    }
}

}  // namespace renderer
