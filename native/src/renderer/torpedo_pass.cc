// native/src/renderer/torpedo_pass.cc
//
// Renders the TORPEDO projectile family -- every TorpedoDescriptor with
// is_disruptor == false -- as BC's audited "billboard root" construction
// (weapon-firing-mechanics.md §5.5): a camera-facing quad basis that spins
// about the view axis, carrying two additive glow quads (one scale-pulsing,
// one a fixed clone), a flare star of `num_flares` quads at random fixed 3D
// rotations with per-flare trapezoid alpha twinkle, and a core sprite drawn
// last. All layers are additive (GL_SRC_ALPHA, GL_ONE), depth test on, depth
// write off, cull off (double-sided flares come free).
//
// The underlying math (glow_pulse_scale, flare_trapezoid, hash01,
// flare_rotation) lives in renderer/torpedo_anim.h and is pinned there --
// see that header's PROVISIONAL MAPPING banner for the open RE questions
// (Q4/Q7) this implementation stands in for. Disruptor bolts
// (is_disruptor == true) are SKIPPED here entirely; they render via a
// dedicated tube-mesh pass added in Task 7 (one-commit invisibility of
// disruptor bolts is an accepted transitional state).
#include "renderer/torpedo_pass.h"

#include "renderer/pipeline.h"
#include "renderer/torpedo_anim.h"

#include <assets/texture.h>
#include <scenegraph/camera.h>

#include <glad/glad.h>
#include <glm/glm.hpp>

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <fstream>

namespace renderer {

namespace {

// Unit-quad corners: two triangles (-1,-1)→(+1,+1).
constexpr float kQuadCorners[] = {
    -1.0f, -1.0f,
    +1.0f, -1.0f,
    +1.0f, +1.0f,
    -1.0f, -1.0f,
    +1.0f, +1.0f,
    -1.0f, +1.0f,
};

}  // namespace

TorpedoPass::TorpedoPass() = default;

TorpedoPass::~TorpedoPass() {
    if (quad_vbo_) glDeleteBuffers(1, &quad_vbo_);
    if (quad_vao_) glDeleteVertexArrays(1, &quad_vao_);
}

void TorpedoPass::ensure_quad_mesh() {
    if (quad_vao_ != 0) return;
    glGenVertexArrays(1, &quad_vao_);
    glBindVertexArray(quad_vao_);
    glGenBuffers(1, &quad_vbo_);
    glBindBuffer(GL_ARRAY_BUFFER, quad_vbo_);
    glBufferData(GL_ARRAY_BUFFER, sizeof(kQuadCorners), kQuadCorners,
                 GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(float),
                          reinterpret_cast<void*>(0));
    glBindVertexArray(0);
}

assets::Texture* TorpedoPass::ensure_texture(const std::string& path) {
    auto it = texture_cache_.find(path);
    if (it != texture_cache_.end()) {
        return (it->second && it->second->id() != 0) ? it->second.get() : nullptr;
    }
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        std::fprintf(stderr, "[torpedo_pass] failed to open '%s'\n", path.c_str());
        texture_cache_.emplace(path, std::make_unique<assets::Texture>());
        return nullptr;
    }
    std::fprintf(stderr, "[torpedo_pass] loaded '%s'\n", path.c_str());
    in.seekg(0, std::ios::end);
    auto size = static_cast<std::size_t>(in.tellg());
    in.seekg(0, std::ios::beg);
    std::vector<std::uint8_t> bytes(size);
    in.read(reinterpret_cast<char*>(bytes.data()),
            static_cast<std::streamsize>(size));
    try {
        assets::Image img = assets::decode_tga(bytes);
        assets::Texture tex = assets::upload_image(img, /*generate_mipmaps=*/true);
        auto owned = std::make_unique<assets::Texture>(std::move(tex));
        auto* raw = owned.get();
        texture_cache_.emplace(path, std::move(owned));
        return raw;
    } catch (const std::exception& e) {
        std::fprintf(stderr, "[torpedo_pass] failed to decode '%s': %s\n",
                     path.c_str(), e.what());
        texture_cache_.emplace(path, std::make_unique<assets::Texture>());
        return nullptr;
    }
}

void TorpedoPass::render(const std::vector<TorpedoDescriptor>& torpedoes,
                          const scenegraph::Camera& camera,
                          Pipeline& pipeline) {
    if (torpedoes.empty()) return;
    ensure_quad_mesh();

    auto& shader = pipeline.torpedo_shader();
    shader.use();

    const glm::mat4 vp = camera.proj_matrix() * camera.view_matrix();
    // Camera basis vectors in world space are the rows of the view matrix's
    // upper-left 3x3 (unchanged from the old code) -- cam_up_world seeds the
    // spinning billboard-root frame below.
    const glm::mat4 view = camera.view_matrix();
    const glm::vec3 cam_up_world = glm::vec3(view[0][1], view[1][1], view[2][1]);
    const glm::vec3 cam_pos = camera.eye;

    shader.set_mat4("u_view_proj", vp);
    shader.set_int ("u_texture",   0);

    // Additive blend, depth-test against scene, depth-write off, cull off
    // (double-sided flares come free).
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE);
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_FALSE);
    glDisable(GL_CULL_FACE);

    glBindVertexArray(quad_vao_);
    glActiveTexture(GL_TEXTURE0);

    // A single quad layer: world-space unit axes (axis_x/axis_y) replace the
    // old camera-billboard + in-plane-rotation uniforms so every layer
    // (root-spin glow/core, per-flare random 3D rotation) shares one vertex
    // shader interface (torpedo.vert).
    auto draw_layer = [&](const std::string& path,
                          const glm::vec4& color,
                          float size,
                          const glm::vec3& world_pos,
                          const glm::vec3& axis_x,
                          const glm::vec3& axis_y,
                          float alpha) {
        if (path.empty() || size <= 0.0f) return;
        assets::Texture* tex = ensure_texture(path);
        if (!tex) return;
        glBindTexture(GL_TEXTURE_2D, tex->id());
        shader.set_vec3 ("u_world_position", world_pos);
        shader.set_vec3 ("u_axis_x",         axis_x);
        shader.set_vec3 ("u_axis_y",         axis_y);
        shader.set_float("u_size",           size);
        shader.set_vec4 ("u_tint",           color);
        shader.set_float("u_alpha",          alpha);
        glDrawArrays(GL_TRIANGLES, 0, 6);
    };

    for (const auto& t : torpedoes) {
        if (t.is_disruptor) continue;  // Task 7: disruptor bolts render via a dedicated tube-mesh pass

        const auto p = map_torpedo_params(t);

        // Root frame: a camera-facing basis that spins about the view axis.
        // Axis math (incl. degenerate-pose guards and the provisional
        // spin-axis choice, RE Q7) lives in torpedo_anim.h so it's testable
        // without a GL context; columns are (X_r, Y_r, Z_r).
        const glm::mat3 root3 = torpedo_root_frame(
            cam_pos, t.world_pos, cam_up_world, t.age, p.spin_rate);
        const glm::vec3 x_r = root3[0];
        const glm::vec3 y_r = root3[1];

        // Glow quad A (animated): one draw at alpha 1.2 is exactly BC's two
        // emissive passes (0.8 + 0.4) summed under additive blending. The
        // 1.2 survives to the GL_SRC_ALPHA blend factor because torpedo.frag
        // scales only frag_color.a by u_alpha (no alpha-squared error) and
        // the pass renders into the RGBA16F HDR target -- float attachments
        // don't clamp fragment outputs before blending. On a normalized
        // (UNORM) target this would clamp to 1.0 and lose the extra 0.2.
        const float pulse_half_size = 0.5f * glow_pulse_scale(
            t.age, p.pulse_rate, p.scale_lo, p.scale_hi);
        draw_layer(t.glow_texture, t.glow_color, pulse_half_size, t.world_pos,
                   x_r, y_r, 1.2f);

        // Glow quad B (fixed clone) -- same axes, fixed size, same alpha.
        draw_layer(t.glow_texture, t.glow_color, 0.5f * p.clone_scale,
                   t.world_pos, x_r, y_r, 1.2f);

        // Flare star: num_flares quads, each at a random fixed 3D rotation
        // (per id + flare index) composed onto the spun root frame, with a
        // per-flare de-phased trapezoid alpha twinkle. Composition order
        // (root * R, column-vector convention) is documented and lock-tested
        // at flare_basis in torpedo_anim.h.
        for (int i = 0; i < t.num_flares; ++i) {
            const glm::mat3 quad_basis = flare_basis(
                root3, static_cast<uint32_t>(t.id), static_cast<uint32_t>(i));

            float alpha = 1.0f;
            if (p.flare_period > 0.0f) {
                // Strictly periodic with a random per-flare phase offset is a
                // provisional stand-in for BC's respawn-with-fresh-random-
                // start (RE Q4).
                const float phi = hash01(static_cast<uint32_t>(t.id),
                                          static_cast<uint32_t>(i), 1u);
                const float u = std::fmod(t.age / p.flare_period + phi, 1.0f);
                alpha = flare_trapezoid(u);
            }
            if (alpha <= 0.0f) continue;

            draw_layer(t.flares_texture, t.flares_color, p.flare_half_size,
                       t.world_pos, quad_basis[0], quad_basis[1], alpha);
        }

        // Core sprite, drawn last -- order is cosmetic under additive blend
        // (kept for readability, matching the old code's convention).
        draw_layer(t.core_texture, t.core_color, p.core_half_size,
                   t.world_pos, x_r, y_r, 1.0f);
    }

    glBindVertexArray(0);
    glEnable(GL_CULL_FACE);
    glDepthMask(GL_TRUE);
    glDisable(GL_BLEND);
}

}  // namespace renderer
