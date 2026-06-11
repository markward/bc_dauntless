// native/src/renderer/particle_pass.cc
#include <renderer/particle_pass.h>

#include <renderer/particle_math.h>
#include <renderer/pipeline.h>
#include <scenegraph/world.h>
#include <scenegraph/camera.h>
#include <scenegraph/instance.h>
#include <assets/texture.h>

#include <glad/glad.h>
#include <glm/glm.hpp>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <vector>

namespace renderer {

namespace {

constexpr float kQuadCorners[] = {
    -1.0f, -1.0f,
    +1.0f, -1.0f,
    +1.0f, +1.0f,
    -1.0f, -1.0f,
    +1.0f, +1.0f,
    -1.0f, +1.0f,
};

// Deterministic 2-float hash from (world_pos, i). Maps to [0, 1)^2 for
// use in per-particle jitter and life-variance.
inline glm::vec2 hash3(const glm::vec3& p, int i) {
    auto bits = [](float f) -> std::uint32_t {
        std::uint32_t u; std::memcpy(&u, &f, sizeof(u)); return u;
    };
    std::uint32_t h = bits(p.x) ^ (bits(p.y) * 0x9E3779B9u)
                    ^ (bits(p.z) * 0x85EBCA6Bu) ^ (std::uint32_t(i) * 0xC2B2AE35u);
    h ^= h << 13; h ^= h >> 17; h ^= h << 5;
    std::uint32_t h2 = h * 0x1B873593u;
    h2 ^= h2 << 13; h2 ^= h2 >> 17; h2 ^= h2 << 5;
    auto to_unit = [](std::uint32_t x) {
        return static_cast<float>(x & 0xFFFFFFu) / static_cast<float>(0x1000000u);
    };
    return glm::vec2{to_unit(h), to_unit(h2)};
}

// Jitter `base` direction within a cone of ±cone_deg/2 using jitter ∈ [0,1)^2.
glm::vec3 cone_jitter(const glm::vec3& base, const glm::vec3& cam_up,
                      const glm::vec3& cam_right, glm::vec2 jitter, float cone_deg) {
    const float k = cone_deg * 0.0174532925f;
    glm::vec3 v = base + cam_right * std::sin((jitter.x - 0.5f) * k)
                       + cam_up    * std::sin((jitter.y - 0.5f) * k);
    const float len = glm::length(v);
    return (len > 1e-6f) ? v / len : base;
}

}  // namespace

ParticlePass::ParticlePass() = default;

ParticlePass::~ParticlePass() {
    if (quad_vbo_) glDeleteBuffers(1, &quad_vbo_);
    if (quad_vao_) glDeleteVertexArrays(1, &quad_vao_);
}

// Verbatim copy of HitVfxPass::ensure_quad_mesh — same unit quad / 6 verts / VAO layout.
void ParticlePass::ensure_quad_mesh() {
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

// Adapted from hit_vfx_pass.cc's load_sprite: loads and caches texture by path.
// Returns cached pointer (nullptr key = open/decode failure — slot holds empty Texture).
assets::Texture* ParticlePass::texture_for(const std::string& path) {
    auto it = textures_.find(path);
    if (it != textures_.end()) {
        return (it->second && it->second->id() != 0) ? it->second.get() : nullptr;
    }

    // Not yet cached — load it now.
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        std::fprintf(stderr, "[particle_pass] failed to open '%s'\n", path.c_str());
        textures_[path] = std::make_unique<assets::Texture>();
        return nullptr;
    }
    in.seekg(0, std::ios::end);
    auto size = static_cast<std::size_t>(in.tellg());
    in.seekg(0, std::ios::beg);
    std::vector<std::uint8_t> bytes(size);
    in.read(reinterpret_cast<char*>(bytes.data()),
            static_cast<std::streamsize>(size));
    try {
        assets::Image img = assets::decode_tga(bytes);
        assets::Texture tex = assets::upload_image(img, /*generate_mipmaps=*/true);
        auto slot = std::make_unique<assets::Texture>(std::move(tex));
        assets::Texture* ptr = slot.get();
        textures_[path] = std::move(slot);
        return (ptr->id() != 0) ? ptr : nullptr;
    } catch (const std::exception& e) {
        std::fprintf(stderr, "[particle_pass] failed to decode '%s': %s\n",
                     path.c_str(), e.what());
        textures_[path] = std::make_unique<assets::Texture>();
        return nullptr;
    }
}

void ParticlePass::render(const std::vector<ParticleEmitterDescriptor>& emitters,
                          const scenegraph::World& world,
                          const scenegraph::Camera& camera,
                          Pipeline& pipeline) {
    if (emitters.empty()) return;
    ensure_quad_mesh();

    auto& shader = pipeline.hit_vfx_shader();
    shader.use();

    const glm::mat4 vp   = camera.proj_matrix() * camera.view_matrix();
    const glm::mat4 view = camera.view_matrix();
    const glm::vec3 cam_right = glm::vec3(view[0][0], view[1][0], view[2][0]);
    const glm::vec3 cam_up    = glm::vec3(view[0][1], view[1][1], view[2][1]);
    shader.set_mat4("u_view_proj",    vp);
    shader.set_vec3("u_camera_right", cam_right);
    shader.set_vec3("u_camera_up",    cam_up);
    shader.set_int ("u_texture",      0);

    glEnable(GL_BLEND);
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_FALSE);
    glDisable(GL_CULL_FACE);
    glBindVertexArray(quad_vao_);
    glActiveTexture(GL_TEXTURE0);

    // Flat arrays for curve_lerp1 (avoids alloc in inner loop).
    float kt[8], kr[8], kg[8], kb[8];
    float at[8], av[8], st[8], sv[8];

    const scenegraph::InstanceId null_id{};
    int active_blend_mode = -1;  // force first set
    for (const auto& e : emitters) {
        assets::Texture* tex = texture_for(e.texture_path);
        if (!tex || tex->id() == 0) continue;

        // Set blend mode per emitter (A2). Only update GL state when it changes.
        if (e.blend_mode != active_blend_mode) {
            active_blend_mode = e.blend_mode;
            if (e.blend_mode == 1) {
                glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA);  // additive
            } else {
                glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);  // alpha (A1 default)
            }
        }

        // Resolve emitter origin to world space.
        glm::vec3 emit_pos_world = e.emit_pos;
        glm::vec3 emit_dir_world = e.emit_dir;
        if (!(e.instance_id == null_id)) {
            const scenegraph::Instance* inst = world.get(e.instance_id);
            if (inst == nullptr) continue;
            emit_pos_world = glm::vec3(inst->world * glm::vec4(e.emit_pos, 1.0f));
            emit_dir_world = glm::mat3(inst->world) * e.emit_dir;
        }
        const float dlen = glm::length(emit_dir_world);
        emit_dir_world = (dlen > 1e-6f) ? emit_dir_world / dlen : glm::vec3(0.0f, -1.0f, 0.0f);

        // Unpack keyframe arrays for curve_lerp1.
        for (int i = 0; i < e.num_color_keys && i < 8; ++i) {
            kt[i] = e.color_keys[i].t; kr[i] = e.color_keys[i].r;
            kg[i] = e.color_keys[i].g; kb[i] = e.color_keys[i].b;
        }
        for (int i = 0; i < e.num_alpha_keys && i < 8; ++i) {
            at[i] = e.alpha_keys[i].t; av[i] = e.alpha_keys[i].v;
        }
        for (int i = 0; i < e.num_size_keys  && i < 8; ++i) {
            st[i] = e.size_keys[i].t;  sv[i] = e.size_keys[i].v;
        }

        const int n = particle_max_count(e.emit_life, e.emit_life_variance,
                                         e.emit_frequency);
        // Defensive default: emitters with tail_length==0 never hit the
        // per-particle branch below, so pre-zero the uniform once here.
        shader.set_float("u_streak_length", 0.0f);
        glBindTexture(GL_TEXTURE_2D, tex->id());

        for (int i = 0; i < n; ++i) {
            const float b   = slot_birth_age(e.effect_age, i, n, e.emit_frequency);
            const float tau = e.effect_age - b;
            const glm::vec2 jit = hash3(emit_pos_world, i);
            const float life_i  = e.emit_life + jit.x * std::max(0.0f, e.emit_life_variance);
            if (tau < 0.0f || tau > life_i) continue;
            if (b < 0.0f || b > e.stop_age) continue;

            const glm::vec3 dir = cone_jitter(emit_dir_world, cam_up, cam_right,
                                              jit, e.angle_variance);

            // A3: damped directed travel (identical to A1/A2 when damping==0).
            const float directed = damped_travel(e.emit_velocity, e.damping, tau);
            glm::vec3 pos = emit_pos_world + dir * directed
                          - e.emit_vel_world * ((1.0f - e.inherit) * tau);

            // A2 extension: emit-radius birth offset (zero when emit_radius==0).
            pos += emit_radius_offset(e.emit_radius, jit, i);

            // A2 extension: 3D random velocity (zero when random_velocity_speed==0).
            // A3: random travel also uses damped_travel (linear when damping==0).
            if (e.random_velocity_speed > 0.0f) {
                const glm::vec2 rv_hash = hash3(emit_pos_world, i + 7919);
                const glm::vec3 rv_dir  = random_cone_dir(emit_dir_world,
                                                          e.random_velocity_cone,
                                                          rv_hash);
                pos += rv_dir * damped_travel(e.random_velocity_speed, e.damping, tau);
            }

            const float t     = (life_i > 1e-6f) ? (tau / life_i) : 0.0f;
            const float size  = curve_lerp1(st, sv, e.num_size_keys,  t);
            const float alpha = curve_lerp1(at, av, e.num_alpha_keys, t);
            const float r     = curve_lerp1(kt, kr, e.num_color_keys, t);
            const float g     = curve_lerp1(kt, kg, e.num_color_keys, t);
            const float bl    = curve_lerp1(kt, kb, e.num_color_keys, t);

            shader.set_vec4 ("u_tint",           glm::vec4(r, g, bl, 1.0f));
            shader.set_vec3 ("u_world_position", pos);
            shader.set_float("u_size",           size);
            shader.set_float("u_alpha",          alpha);
            // A3: streak uniforms. tail_length==0 => camera-facing billboard (A1/A2 path).
            if (e.tail_length > 0.0f) {
                const float speed = e.emit_velocity * std::exp(-e.damping * tau);
                shader.set_vec3 ("u_streak_axis",   dir);
                shader.set_float("u_streak_length", e.tail_length * speed);
            } else {
                shader.set_float("u_streak_length", 0.0f);
            }
            glDrawArrays(GL_TRIANGLES, 0, 6);
        }
    }

    glBindTexture(GL_TEXTURE_2D, 0);
    glBindVertexArray(0);
    glEnable(GL_CULL_FACE);
    glDepthMask(GL_TRUE);
    glDisable(GL_BLEND);
}

}  // namespace renderer
