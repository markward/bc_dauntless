// native/src/renderer/torpedo_pass.cc
//
// Renders BOTH BC projectile families carried by TorpedoDescriptor --
// weapon-firing-mechanics.md §5.5 audited these as two ENTIRELY DIFFERENT
// animation architectures sharing one descriptor struct:
//
//   TORPEDO (is_disruptor == false): a controller-driven "billboard root"
//   construction -- a camera-facing quad basis that spins about the view
//   axis, carrying two additive glow quads (one scale-pulsing, one a fixed
//   clone), a flare star of `num_flares` quads at random fixed 3D rotations
//   with per-flare trapezoid alpha twinkle, and a core sprite drawn last.
//   All layers are additive (GL_SRC_ALPHA, GL_ONE), depth test on, depth
//   write off, cull off (double-sided flares come free). The underlying math
//   (glow_pulse_scale, flare_trapezoid, hash01, flare_rotation) lives in
//   renderer/torpedo_anim.h -- see that header's PROVISIONAL MAPPING banner
//   for the open RE questions (Q4/Q7) this implementation stands in for.
//
//   DISRUPTOR (is_disruptor == true): no controller, no texture, no light --
//   a procedural tapered-tube mesh (renderer::build_bolt_mesh) whose ONLY
//   animation is imperative per-frame re-orientation of the tube's +Y axis
//   onto the current velocity vector (renderer::bolt_align_rotation). Two
//   concentric uniform-color sub-draws (shell then a smaller, shorter core)
//   stand in for BC's two per-vertex bolt colors -- geometrically equivalent
//   and cheaper than authoring a two-color vertex stream; see the per-draw
//   comment in render() for the 0.5/0.8 core-scale provenance. Same additive
//   GL state as the torpedo family, drawn via the separate `disruptor_shader`
//   program (flat unlit, no texture unit).
//
// Both families are additive and share the pass's GL state block; the two
// are drawn as separate sub-loops (torpedo program bound once, then the
// disruptor program bound once) so per-entry program switching never
// happens -- see render()'s two-pass structure below.
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
    if (bolt_ebo_) glDeleteBuffers(1, &bolt_ebo_);
    if (bolt_vbo_) glDeleteBuffers(1, &bolt_vbo_);
    if (bolt_vao_) glDeleteVertexArrays(1, &bolt_vao_);
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

void TorpedoPass::ensure_bolt_mesh() {
    if (bolt_vao_ != 0) return;
    const BoltMesh mesh = build_bolt_mesh();  // default 12 segments (SWIG default, never overridden)

    glGenVertexArrays(1, &bolt_vao_);
    glBindVertexArray(bolt_vao_);

    glGenBuffers(1, &bolt_vbo_);
    glBindBuffer(GL_ARRAY_BUFFER, bolt_vbo_);
    glBufferData(GL_ARRAY_BUFFER,
                 static_cast<GLsizeiptr>(mesh.vertices.size() * sizeof(glm::vec3)),
                 mesh.vertices.data(), GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, sizeof(glm::vec3),
                          reinterpret_cast<void*>(0));

    glGenBuffers(1, &bolt_ebo_);
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, bolt_ebo_);
    glBufferData(GL_ELEMENT_ARRAY_BUFFER,
                 static_cast<GLsizeiptr>(mesh.indices.size() * sizeof(uint32_t)),
                 mesh.indices.data(), GL_STATIC_DRAW);

    glBindVertexArray(0);
    bolt_index_count_ = static_cast<int>(mesh.indices.size());
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
        if (t.is_disruptor) continue;  // drawn below, by the disruptor sub-loop

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

    // Disruptor sub-loop: a second pass over the SAME list, so the disruptor
    // program is bound at most once per frame rather than thrashing programs
    // per entry (a single sorted/interleaved loop would rebind on every
    // family transition). Skip the whole sub-loop -- including the lazy mesh
    // upload and the program bind -- when nothing needs it.
    bool has_disruptor = false;
    for (const auto& t : torpedoes) {
        if (t.is_disruptor) { has_disruptor = true; break; }
    }
    if (has_disruptor) {
        ensure_bolt_mesh();
        auto& bolt_shader = pipeline.disruptor_shader();
        bolt_shader.use();
        bolt_shader.set_mat4("u_view_proj", vp);  // set once per frame, not per bolt
        glBindVertexArray(bolt_vao_);

        for (const auto& t : torpedoes) {
            if (!t.is_disruptor) continue;
            // Defensive only -- marshal (Task 2) always sends real values for
            // disruptor entries; a non-positive length/width would otherwise
            // scale the tube to a degenerate (zero-volume or inside-out) mesh.
            if (t.bolt_length <= 0.0f || t.bolt_width <= 0.0f) continue;

            // Tube axis re-orientation is the disruptor's ONLY animation
            // (§5.5) -- no controller, computed fresh every frame from the
            // current velocity direction.
            const glm::mat4 rotate = glm::mat4(bolt_align_rotation(t.forward));
            const glm::mat4 translate = glm::translate(glm::mat4(1.0f), t.world_pos);

            // Two concentric uniform-color sub-draws stand in for BC's two
            // per-vertex bolt colors (shell + core) -- geometrically
            // equivalent under a flat-shaded, unlit tube and cheaper than a
            // two-color vertex stream. Column-vector convention: M = T * R * S.

            // Shell: full bolt_width/bolt_length, shell_color.
            const glm::mat4 shell_model = translate * rotate *
                glm::scale(glm::mat4(1.0f), glm::vec3(t.bolt_width, t.bolt_length, t.bolt_width));
            bolt_shader.set_mat4("u_model", shell_model);
            bolt_shader.set_vec4("u_color", t.shell_color);
            glDrawElements(GL_TRIANGLES, bolt_index_count_, GL_UNSIGNED_INT, nullptr);

            // Core: 0.5x width / 0.8x length, bolt_core_color. These are BC's
            // never-overridden optional SWIG defaults -- PROVISIONAL
            // interpretation by analogy with the phaser CoreScale constant
            // (RE Q5; not independently confirmed for the disruptor bolt).
            const glm::mat4 core_model = translate * rotate *
                glm::scale(glm::mat4(1.0f),
                           glm::vec3(0.5f * t.bolt_width, 0.8f * t.bolt_length, 0.5f * t.bolt_width));
            bolt_shader.set_mat4("u_model", core_model);
            bolt_shader.set_vec4("u_color", t.bolt_core_color);
            glDrawElements(GL_TRIANGLES, bolt_index_count_, GL_UNSIGNED_INT, nullptr);
        }
    }

    glBindVertexArray(0);
    glEnable(GL_CULL_FACE);
    glDepthMask(GL_TRUE);
    glDisable(GL_BLEND);
}

}  // namespace renderer
