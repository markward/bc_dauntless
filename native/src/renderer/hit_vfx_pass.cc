// native/src/renderer/hit_vfx_pass.cc
#include "renderer/hit_vfx_pass.h"

#include "renderer/pipeline.h"

#include <assets/texture.h>
#include <scenegraph/camera.h>
#include <scenegraph/world.h>
#include <scenegraph/instance.h>

#include <glad/glad.h>
#include <glm/glm.hpp>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>

namespace renderer {

namespace {

// Per-tier visual constants (spec §6.1).
struct TierConfig {
    float peak_size;     // world-units half-size at peak expansion
    float spawn_dur;     // seconds, size eases 0→peak
    float fade_dur;      // seconds, alpha fades 1→0
    float total_life;    // seconds, descriptor pruned at this age (renderer side)
    glm::vec4 tint;
};

// Indexed by severity: 0=SHIELD (unused — never reaches renderer), 1=HULL, 2=CRITICAL.
constexpr TierConfig kTiers[3] = {
    {0.0f, 0.0f, 0.0f, 0.0f, {1.0f, 1.0f, 1.0f, 1.0f}},   // SHIELD — never used.
    {3.0f, 0.08f, 0.25f, 0.33f, {1.00f, 0.55f, 0.20f, 1.0f}},  // HULL
    {7.0f, 0.10f, 0.55f, 0.65f, {1.00f, 0.92f, 0.80f, 1.0f}},  // CRITICAL
};

// Weapon-distinct spark tints + spread tuning (spec 3.4). weapon_kind:
// 0 = phaser (cool white-blue, tight), 1 = torpedo/disruptor (hot orange, wide).
constexpr glm::vec4 kSparkTint[2] = {
    {0.78f, 0.86f, 1.00f, 1.0f},   // phaser — cool white-blue
    {1.00f, 0.55f, 0.18f, 1.0f},   // torpedo — hot orange
};
// Spread tuning per kind, fed to rotate_jitter as a degree-scaled jitter
// amplitude (NOT a literal half-angle; rotate_jitter adds sin(jitter*k)
// offsets, so 120 yields ~50 deg max spread). phaser tight, torpedo wide.
constexpr float kSparkConeDegByKind[2] = {40.0f, 120.0f};
constexpr float kSparkSpeed     = 4.0f;    // wu/s initial speed
constexpr float kSparkSizeMult  = 0.6f;    // multiplier on tier peak_size
constexpr float kSparkDamping   = 1.4f;    // velocity damping rate (SDK SetDamping analogue)

// Renderer CWD is the project root (see engine/host_loop.py:_resolve_game_texture),
// so these direct-ifstream sprite loads need the "game/" prefix — matching
// phaser_pass.cc's "game/data/phaser.tga". Without it load_sprite fails, the
// main texture stays id()==0, and render() early-returns, suppressing the WHOLE
// pass (flash + sparks).
constexpr const char* kImpactTexturePath = "game/data/Textures/Tactical/TorpedoFlares.tga";
constexpr const char* kSparkTexturePath  = "game/data/rough.tga";

constexpr float kQuadCorners[] = {
    -1.0f, -1.0f,
    +1.0f, -1.0f,
    +1.0f, +1.0f,
    -1.0f, -1.0f,
    +1.0f, +1.0f,
    -1.0f, +1.0f,
};

// Deterministic 2-float hash from (world_pos, i). xorshift on float bit
// reinterprets — cheap, no allocation. Same descriptor produces the same
// directions across frames so sparks travel continuously instead of
// teleporting; different descriptors at identical world positions still
// produce different spark patterns.
inline glm::vec2 hash3(const glm::vec3& p, int i) {
    auto bits = [](float f) -> std::uint32_t {
        std::uint32_t u;
        std::memcpy(&u, &f, sizeof(u));
        return u;
    };
    std::uint32_t h = bits(p.x) ^ (bits(p.y) * 0x9E3779B9u)
                    ^ (bits(p.z) * 0x85EBCA6Bu) ^ (std::uint32_t(i) * 0xC2B2AE35u);
    h ^= h << 13; h ^= h >> 17; h ^= h << 5;
    std::uint32_t h2 = h * 0x1B873593u;
    h2 ^= h2 << 13; h2 ^= h2 >> 17; h2 ^= h2 << 5;
    // Map to [-1, 1] floats.
    auto to_unit = [](std::uint32_t x) {
        return (float(x & 0xFFFFFF) / float(0xFFFFFF)) * 2.0f - 1.0f;
    };
    return glm::vec2{to_unit(h), to_unit(h2)};
}

// Rotate `base` toward `±cone_deg` along two perpendicular axes,
// jittered by `jitter` ∈ [-1, 1]^2. Approximation of a true cone
// rotation (Rodrigues would be exact); error is acceptable here.
glm::vec3 rotate_jitter(const glm::vec3& base, const glm::vec3& cam_up,
                          const glm::vec3& cam_right, glm::vec2 jitter,
                          float cone_deg) {
    const float k = cone_deg * 3.14159265f / 180.0f;
    glm::vec3 v = base + cam_right * std::sin(jitter.x * k)
                       + cam_up    * std::sin(jitter.y * k);
    float len = glm::length(v);
    if (len > 1e-6f) v /= len;
    return v;
}

}  // namespace

HitVfxPass::HitVfxPass() = default;

HitVfxPass::~HitVfxPass() {
    if (quad_vbo_) glDeleteBuffers(1, &quad_vbo_);
    if (quad_vao_) glDeleteVertexArrays(1, &quad_vao_);
}

void HitVfxPass::ensure_quad_mesh() {
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

namespace {

// Load a TGA sprite into `slot`. On any failure `slot` is set to an empty
// Texture (id()==0) so the caller can detect and skip rather than crash.
void load_sprite(std::unique_ptr<assets::Texture>& slot, const char* path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        std::fprintf(stderr, "[hit_vfx_pass] failed to open '%s'\n", path);
        slot = std::make_unique<assets::Texture>();
        return;
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
        slot = std::make_unique<assets::Texture>(std::move(tex));
    } catch (const std::exception& e) {
        std::fprintf(stderr, "[hit_vfx_pass] failed to decode '%s': %s\n",
                     path, e.what());
        slot = std::make_unique<assets::Texture>();
    }
}

}  // namespace

const char* HitVfxPass::impact_texture_path() { return kImpactTexturePath; }
const char* HitVfxPass::spark_texture_path()  { return kSparkTexturePath; }

void HitVfxPass::ensure_texture() {
    if (texture_) return;
    load_sprite(texture_, kImpactTexturePath);
}

void HitVfxPass::ensure_spark_texture() {
    if (spark_texture_) return;
    load_sprite(spark_texture_, kSparkTexturePath);
}

void HitVfxPass::render(const std::vector<HitVfxDescriptor>& vfx,
                        const scenegraph::World& world,
                        const scenegraph::Camera& camera,
                        Pipeline& pipeline) {
    if (vfx.empty()) return;
    ensure_quad_mesh();
    ensure_texture();
    ensure_spark_texture();
    if (!texture_ || texture_->id() == 0) return;

    auto& shader = pipeline.hit_vfx_shader();
    shader.use();

    const glm::mat4 vp = camera.proj_matrix() * camera.view_matrix();
    const glm::mat4 view = camera.view_matrix();
    const glm::vec3 cam_right = glm::vec3(view[0][0], view[1][0], view[2][0]);
    const glm::vec3 cam_up    = glm::vec3(view[0][1], view[1][1], view[2][1]);

    shader.set_mat4("u_view_proj",    vp);
    shader.set_vec3("u_camera_right", cam_right);
    shader.set_vec3("u_camera_up",    cam_up);
    shader.set_int ("u_texture",      0);

    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE);
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_FALSE);
    glDisable(GL_CULL_FACE);

    glBindVertexArray(quad_vao_);
    glActiveTexture(GL_TEXTURE0);

    for (const auto& v : vfx) {
        // Clamp severity to [1, 2]; index 0 (SHIELD) should never reach
        // the renderer but guard regardless.
        const int sev = std::max(1, std::min(2, v.severity));
        const TierConfig& tier = kTiers[sev];

        const float age = std::max(0.0f, v.age);
        if (age >= tier.total_life) continue;

        // ── Main billboard ──
        const float size_t  = std::min(1.0f, age / tier.spawn_dur);
        const float fade_t  = std::max(0.0f, std::min(1.0f,
                                  (age - tier.spawn_dur) / tier.fade_dur));
        const float size    = tier.peak_size * size_t;
        const float alpha   = 1.0f - fade_t;

        glBindTexture(GL_TEXTURE_2D, texture_->id());
        shader.set_vec4 ("u_tint",           tier.tint);
        shader.set_vec3 ("u_world_position", v.world_pos);
        shader.set_float("u_size",           size);
        shader.set_float("u_alpha",          alpha);
        glDrawArrays(GL_TRIANGLES, 0, 6);

        // Spark burst (hull-anchored, detached, weapon-distinct).
        if (v.spark_count > 0 && spark_texture_ && spark_texture_->id() != 0) {
            const scenegraph::Instance* inst = world.get(v.instance_id);
            if (inst != nullptr) {
                const glm::vec3 origin =
                    glm::vec3(inst->world * glm::vec4(v.body_point, 1.0f));
                glm::vec3 base = glm::mat3(inst->world) * v.body_normal;
                float blen = glm::length(base);
                base = (blen > 1e-6f) ? base / blen : cam_right;

                const int kind = (v.weapon_kind == 0) ? 0 : 1;
                glBindTexture(GL_TEXTURE_2D, spark_texture_->id());
                shader.set_vec4("u_tint", kSparkTint[kind]);
                const float cone = kSparkConeDegByKind[kind];
                // Damped ballistic travel: x(t) = (v0/c)(1 - e^{-c t}).
                const float travel =
                    (kSparkSpeed / kSparkDamping) * (1.0f - std::exp(-kSparkDamping * age));
                const float life_t = age / tier.total_life;
                for (int i = 0; i < v.spark_count; ++i) {
                    const glm::vec2 jitter = hash3(origin, i);
                    const glm::vec3 dir =
                        rotate_jitter(base, cam_up, cam_right, jitter, cone);
                    const glm::vec3 pos = origin + dir * travel;
                    const float spark_size =
                        kSparkSizeMult * tier.peak_size * (1.0f - life_t);
                    const float spark_alpha = 1.0f - life_t;
                    shader.set_vec3 ("u_world_position", pos);
                    shader.set_float("u_size",           spark_size);
                    shader.set_float("u_alpha",          spark_alpha);
                    glDrawArrays(GL_TRIANGLES, 0, 6);
                }
            }
        }
    }

    glBindTexture(GL_TEXTURE_2D, 0);
    glBindVertexArray(0);
    glEnable(GL_CULL_FACE);
    glDepthMask(GL_TRUE);
    glDisable(GL_BLEND);
}

}  // namespace renderer
