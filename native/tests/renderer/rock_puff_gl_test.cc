// native/tests/renderer/rock_puff_gl_test.cc
// Rock-field puffs (rock_puffs.h): the fill cut in rock_puff.vert / .frag
// (2026-10-04) must not change the picture. The reference is the puff
// shader as it was BEFORE the cut (copied verbatim below), drawn with the
// uniforms and blend state FarPass::render_rock_puffs sets; the production
// path is FarPass::render_rock_puffs itself. Real placement (PuffField over a
// Beol 4-like tile field at the production dials), several fixed views.
#include <gtest/gtest.h>

#include <glad/glad.h>
#include <glm/glm.hpp>

#include <renderer/far_field.h>
#include <renderer/far_pass.h>
#include <renderer/frame.h>
#include <renderer/hdr_target.h>
#include <renderer/pipeline.h>
#include <renderer/rock_puffs.h>
#include <renderer/shader.h>
#include <renderer/window.h>

#include "embedded_rock_puff_fs.h"

#include <scenegraph/camera.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

namespace rf = renderer::rockfield;
namespace far = renderer::far;

constexpr int kW = 256, kH = 256;

// rock_puff.vert / rock_puff.frag before the fill cut (2026-10-04).
const char* kOldPuffVs = R"GLSL(#version 410 core
// Rock-field puffs (rock_puffs.h): a camera-facing quad of the puff's
// world radius; alpha = opacity * weight * distance fade-in * near fade-out.
layout(location = 0) in vec2 a_corner;        // (+-1, +-1)
layout(location = 7) in vec4 a_pos_r;         // xyz relative to the field origin, w radius (GU)
layout(location = 8) in vec4 a_albedo_w;      // rgb albedo, a density weight
uniform mat4 u_view;
uniform mat4 u_proj;
uniform vec3 u_offset;                        // render-space position of the field origin
uniform vec3 u_eye;                           // render-space camera position
uniform float u_opacity, u_start_gu, u_ramp_gu, u_near_fade;
out vec2 v_corner;
flat out vec3 v_centre;
flat out vec3 v_albedo;
flat out float v_alpha;
flat out vec3 v_seed;
void main() {
    vec3 c = a_pos_r.xyz + u_offset;
    float r = a_pos_r.w;
    float d = length(c - u_eye);
    float a_far = u_ramp_gu > 0.0 ? clamp((d - u_start_gu) / u_ramp_gu, 0.0, 1.0)
                                  : (d >= u_start_gu ? 1.0 : 0.0);
    float a_near = clamp((d - r) / max(u_near_fade * r - r, 1e-3), 0.0, 1.0);
    float alpha = u_opacity * a_albedo_w.a * a_far * a_near;
    // Camera-facing in view space.
    vec4 vc = u_view * vec4(c, 1.0);
    if (alpha <= 0.0 || vc.z > -1.0) {
        gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
        v_corner = vec2(0.0); v_centre = c; v_albedo = vec3(0.0); v_alpha = 0.0; v_seed = vec3(0.0);
        return;
    }
    vc.xy += a_corner * r;
    gl_Position = u_proj * vc;
    v_corner = a_corner;
    v_centre = c;
    v_albedo = a_albedo_w.rgb;
    v_alpha = alpha;
    v_seed = fract(sin(a_pos_r.xyz * vec3(12.9898, 78.233, 37.719)) * 43758.5453) * 64.0;
}
)GLSL";
const char* kOldPuffFs = R"GLSL(#version 410 core
// Rock-field puffs: a soft, noise-broken blob, lit like the speck
// band (Lambert sphere phase toward the sun). PREMULTIPLIED, blended
// GL_ONE, GL_ONE_MINUS_SRC_ALPHA, depth-tested, no depth writes.
in vec2 v_corner;
flat in vec3 v_centre;
flat in vec3 v_albedo;
flat in float v_alpha;
flat in vec3 v_seed;
uniform vec3 u_camera_pos_ws;
uniform vec3 u_ambient_light;
uniform int u_dir_light_count;
uniform vec3 u_dir_light_dir_ws[4];           // toward each light
uniform vec3 u_dir_light_color[4];
uniform float u_brightness;
out vec4 frag_color;

const float PI = 3.14159265;

float lambert_sphere_phase(float cos_alpha) {
    float c = clamp(cos_alpha, -1.0, 1.0);
    float a = acos(c);
    return (2.0 / (3.0 * PI)) * (sin(a) + (PI - a) * c);
}

float hash2(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float vnoise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash2(i), hash2(i + vec2(1, 0)), u.x),
               mix(hash2(i + vec2(0, 1)), hash2(i + vec2(1, 1)), u.x), u.y);
}
float fbm2(vec2 p) {
    float s = 0.0, a = 0.5;
    for (int o = 0; o < 4; ++o) { s += a * vnoise(p); p *= 2.03; a *= 0.5; }
    return s / 0.9375;
}

void main() {
    float rr = dot(v_corner, v_corner);
    if (rr >= 1.0) discard;
    // Soft core with a noise-eaten edge: no visible card or circle.
    float n = fbm2(v_corner * 2.2 + v_seed.xy);
    float body = exp(-3.0 * rr) * smoothstep(1.0, 0.55, rr + 0.35 * (n - 0.5));
    float a = v_alpha * body * (0.55 + 0.9 * n);
    if (a <= 0.0) discard;
    vec3 to_eye = normalize(u_camera_pos_ws - v_centre);
    vec3 light = u_ambient_light;
    for (int i = 0; i < u_dir_light_count; ++i)
        light += u_dir_light_color[i]
               * lambert_sphere_phase(dot(normalize(u_dir_light_dir_ws[i]), to_eye));
    vec3 c = v_albedo * light * u_brightness;
    frag_color = vec4(c * a, a);
}
)GLSL";

// rock_puff.vert / rock_puff.frag as they were BEFORE the hash table and the
// per-puff lighting (2026-10-18, perf-register.md P-1): every fragment ran 16
// sine hashes and the Lambert phase. Copied verbatim.
const char* kInlineHashPuffVs = R"GLSL(#version 410 core
// Rock-field puffs (rock_puffs.h): a camera-facing quad of the puff's
// world radius; alpha = opacity * weight * distance fade-in * near fade-out.
//
// Fill cut (2026-10-04; the picture moves by at most 1/255, pinned by
// RockPuffGLTest): kMinAlpha is 1/255 / 8, not / 2 -- inside a field the
// image is MANY faint puffs, whose dropped rims add up (1/512 moved the
// centre view over black by 1.1/255, 1/2048 by 0.26/255). rock_puff.frag
// discards every fragment whose alpha bound
// kAlphaMax * v_alpha * exp(-3 rr) is under kMinAlpha, so (1) a puff whose
// peak bound kAlphaMax * alpha is under it is collapsed here, and (2) the
// quad shrinks to the radius where that bound reaches kMinAlpha -- every
// fragment it drops would have been discarded. v_corner scales with it, so a
// kept fragment shades exactly as before.
layout(location = 0) in vec2 a_corner;        // (+-1, +-1)
layout(location = 7) in vec4 a_pos_r;         // xyz relative to the field origin, w radius (GU)
layout(location = 8) in vec4 a_albedo_w;      // rgb albedo, a density weight
uniform mat4 u_view;
uniform mat4 u_proj;
uniform vec3 u_offset;                        // render-space position of the field origin
uniform vec3 u_eye;                           // render-space camera position
uniform float u_opacity, u_start_gu, u_ramp_gu, u_near_fade;
out vec2 v_corner;
flat out vec3 v_centre;
flat out vec3 v_albedo;
flat out float v_alpha;
flat out vec3 v_seed;
const float kMinAlpha = 1.0 / 2048.0;  // rock_puff.frag's discard threshold
const float kAlphaMax = 1.45;          // rock_puff.frag: body <= exp(-3 rr), 0.55 + 0.9 n <= 1.45
void main() {
    vec3 c = a_pos_r.xyz + u_offset;
    float r = a_pos_r.w;
    float d = length(c - u_eye);
    float a_far = u_ramp_gu > 0.0 ? clamp((d - u_start_gu) / u_ramp_gu, 0.0, 1.0)
                                  : (d >= u_start_gu ? 1.0 : 0.0);
    float a_near = clamp((d - r) / max(u_near_fade * r - r, 1e-3), 0.0, 1.0);
    float alpha = u_opacity * a_albedo_w.a * a_far * a_near;
    // Camera-facing in view space.
    vec4 vc = u_view * vec4(c, 1.0);
    if (!(kAlphaMax * alpha >= kMinAlpha) || vc.z > -1.0) {
        gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
        v_corner = vec2(0.0); v_centre = c; v_albedo = vec3(0.0); v_alpha = 0.0; v_seed = vec3(0.0);
        return;
    }
    // The bound reaches kMinAlpha at rr_max = ln(kAlphaMax * alpha / kMinAlpha) / 3
    // (>= 0 here); past rr 1 the fragment shader discards anyway. 1.001: the
    // boundary fragments stay rasterised.
    float rr_max = log(kAlphaMax * alpha / kMinAlpha) / 3.0;
    float s = rr_max < 1.0 ? min(1.0, sqrt(rr_max) * 1.001) : 1.0;
    vc.xy += a_corner * (r * s);
    gl_Position = u_proj * vc;
    v_corner = a_corner * s;
    v_centre = c;
    v_albedo = a_albedo_w.rgb;
    v_alpha = alpha;
    v_seed = fract(sin(a_pos_r.xyz * vec3(12.9898, 78.233, 37.719)) * 43758.5453) * 64.0;
}
)GLSL";
const char* kInlineHashPuffFs = R"GLSL(#version 410 core
// Rock-field puffs: a soft, noise-broken blob, lit like the speck
// band (Lambert sphere phase toward the sun). PREMULTIPLIED, blended
// GL_ONE, GL_ONE_MINUS_SRC_ALPHA, depth-tested, no depth writes.
in vec2 v_corner;
flat in vec3 v_centre;
flat in vec3 v_albedo;
flat in float v_alpha;
flat in vec3 v_seed;
uniform vec3 u_camera_pos_ws;
uniform vec3 u_ambient_light;
uniform int u_dir_light_count;
uniform vec3 u_dir_light_dir_ws[4];           // toward each light
uniform vec3 u_dir_light_color[4];
uniform float u_brightness;
out vec4 frag_color;

// Fill cut (2026-10-04, see rock_puff.vert): a fragment whose alpha cannot
// reach kMinAlpha is discarded BEFORE the noise. alpha = v_alpha * body *
// (0.55 + 0.9 n) with body <= exp(-3 rr) and n <= 1, so kAlphaMax * v_alpha *
// exp(-3 rr) bounds it. Keep both constants identical with rock_puff.vert.
const float kMinAlpha = 1.0 / 2048.0;
const float kAlphaMax = 1.45;

const float PI = 3.14159265;

float lambert_sphere_phase(float cos_alpha) {
    float c = clamp(cos_alpha, -1.0, 1.0);
    float a = acos(c);
    return (2.0 / (3.0 * PI)) * (sin(a) + (PI - a) * c);
}

float hash2(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float vnoise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash2(i), hash2(i + vec2(1, 0)), u.x),
               mix(hash2(i + vec2(0, 1)), hash2(i + vec2(1, 1)), u.x), u.y);
}
float fbm2(vec2 p) {
    float s = 0.0, a = 0.5;
    for (int o = 0; o < 4; ++o) { s += a * vnoise(p); p *= 2.03; a *= 0.5; }
    return s / 0.9375;
}

void main() {
    float rr = dot(v_corner, v_corner);
    if (rr >= 1.0) discard;
    if (kAlphaMax * v_alpha * exp(-3.0 * rr) < kMinAlpha) discard;
    // Soft core with a noise-eaten edge: no visible card or circle.
    float n = fbm2(v_corner * 2.2 + v_seed.xy);
    float body = exp(-3.0 * rr) * smoothstep(1.0, 0.55, rr + 0.35 * (n - 0.5));
    float a = v_alpha * body * (0.55 + 0.9 * n);
    if (a <= 0.0) discard;
    vec3 to_eye = normalize(u_camera_pos_ws - v_centre);
    vec3 light = u_ambient_light;
    for (int i = 0; i < u_dir_light_count; ++i)
        light += u_dir_light_color[i]
               * lambert_sphere_phase(dot(normalize(u_dir_light_dir_ws[i]), to_eye));
    vec3 c = v_albedo * light * u_brightness;
    frag_color = vec4(c * a, a);
}
)GLSL";

// Beol 4's "Asteroid Field 1" as density.py pushes it at the production
// tile dials (tile_noise_*, tile_noise_sharpness 2.5, tile_shape_warp 0.35
// at 0.6 x the radius), centred at the origin.
far::DiscSource beol4_field() {
    far::DiscSource s;
    s.id = 7; s.seed = 4242u;
    s.shape = far::DiscSource::Shape::Sphere;
    s.procedural = false;
    s.view_space = true;
    s.sphere_radius_gu = 1000.0f;
    s.sphere_edge_frac = 0.2f;
    s.noise_scale_gu = 250.0f; s.noise_contrast = 0.8f; s.noise_octaves = 3;
    s.noise_sharpness = 2.5f;
    s.shape_warp = 0.35f; s.shape_warp_scale_gu = 600.0f;
    far::Population p;
    p.albedo = glm::vec3(0.44f, 0.41f, 0.38f);
    s.pops = {p};
    return s;
}

renderer::Lighting puff_lighting() {
    renderer::Lighting l;
    l.ambient = glm::vec3(0.1f);
    l.directional_count = 2;
    l.directional_dir_ws[0] = glm::normalize(glm::vec3(-0.29f, -0.96f, 0.0f));
    l.directional_color[0] = glm::vec3(0.44f, 0.49f, 0.59f);
    l.directional_dir_ws[1] = glm::normalize(glm::vec3(0.64f, 0.17f, 0.75f));
    l.directional_color[1] = glm::vec3(0.14f, 0.14f, 0.10f);
    return l;
}

scenegraph::Camera camera_at(const glm::vec3& eye, const glm::vec3& target, float fov_deg) {
    scenegraph::Camera c;
    c.eye = eye;
    c.target = target;
    c.up = glm::vec3(0.0f, 0.0f, 1.0f);
    c.fov_y_rad = glm::radians(fov_deg);
    c.aspect = 1.0f;
    c.near = 0.5f;
    c.far = 1.0e6f;
    return c;
}

class RockPuffGLTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    std::unique_ptr<renderer::Pipeline> pipeline;
    std::unique_ptr<renderer::Shader> old_shader;
    std::unique_ptr<renderer::Shader> inline_hash_shader;
    GLuint vao = 0, corner_vbo = 0, inst_vbo = 0;
    GLsizei count = 0;

    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(kW, kH, "rock-puff-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        pipeline = std::make_unique<renderer::Pipeline>();
        old_shader = std::make_unique<renderer::Shader>(kOldPuffVs, kOldPuffFs);
        inline_hash_shader = std::make_unique<renderer::Shader>(kInlineHashPuffVs,
                                                                kInlineHashPuffFs);
    }
    void TearDown() override {
        if (vao != 0) glDeleteVertexArrays(1, &vao);
        if (corner_vbo != 0) glDeleteBuffers(1, &corner_vbo);
        if (inst_vbo != 0) glDeleteBuffers(1, &inst_vbo);
    }

    // The reference draw's own instance stream: FarPass's layout (corner
    // strip at 0; pos_r, albedo_w at 7, 8, divisor 1).
    void upload_reference(const std::vector<rf::PuffGpu>& puffs) {
        if (vao == 0) {
            const float corners[8] = {-1.0f, -1.0f, -1.0f, 1.0f, 1.0f, -1.0f, 1.0f, 1.0f};
            glGenVertexArrays(1, &vao);
            glGenBuffers(1, &corner_vbo);
            glGenBuffers(1, &inst_vbo);
            glBindVertexArray(vao);
            glBindBuffer(GL_ARRAY_BUFFER, corner_vbo);
            glBufferData(GL_ARRAY_BUFFER, sizeof(corners), corners, GL_STATIC_DRAW);
            glEnableVertexAttribArray(0);
            glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(float), nullptr);
            glBindBuffer(GL_ARRAY_BUFFER, inst_vbo);
            for (GLuint k = 0; k < 2; ++k) {
                glEnableVertexAttribArray(7 + k);
                glVertexAttribPointer(7 + k, 4, GL_FLOAT, GL_FALSE, sizeof(rf::PuffGpu),
                                      reinterpret_cast<void*>(static_cast<std::uintptr_t>(k * 16)));
                glVertexAttribDivisor(7 + k, 1);
            }
            glBindVertexArray(0);
        }
        glBindBuffer(GL_ARRAY_BUFFER, inst_vbo);
        glBufferData(GL_ARRAY_BUFFER, static_cast<GLsizeiptr>(puffs.size() * sizeof(rf::PuffGpu)),
                     puffs.data(), GL_STATIC_DRAW);
        glBindBuffer(GL_ARRAY_BUFFER, 0);
        count = static_cast<GLsizei>(puffs.size());
    }

    // FarPass::render_rock_puffs' uniforms and state, with the OLD shader
    // (or `shader`, another reference with the same interface).
    void draw_reference(const glm::vec3& offset, const rf::PuffDials& d,
                        const scenegraph::Camera& cam, const renderer::Lighting& l,
                        renderer::Shader* shader = nullptr) {
        renderer::Shader& s = shader != nullptr ? *shader : *old_shader;
        s.use();
        s.set_mat4("u_view", cam.view_matrix());
        s.set_mat4("u_proj", cam.proj_matrix());
        const glm::vec3 eye = glm::vec3(glm::inverse(cam.view_matrix())[3]);
        s.set_vec3("u_camera_pos_ws", eye);
        s.set_vec3("u_eye", eye);
        s.set_vec3("u_offset", offset);
        s.set_float("u_opacity", d.opacity);
        s.set_float("u_start_gu", d.start_gu);
        s.set_float("u_ramp_gu", d.ramp_gu);
        s.set_float("u_near_fade", d.near_fade);
        s.set_float("u_brightness", d.brightness);
        renderer::set_ambient_uniforms(s, l, 1.0f);
        s.set_int("u_dir_light_count", l.directional_count);
        s.set_vec3_array("u_dir_light_dir_ws", l.directional_dir_ws, l.directional_count);
        s.set_vec3_array("u_dir_light_color", l.directional_color, l.directional_count);
        glEnable(GL_BLEND);
        glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA);
        glEnable(GL_DEPTH_TEST);
        glDepthMask(GL_FALSE);
        glDisable(GL_CULL_FACE);
        glBindVertexArray(vao);
        glDrawArraysInstanced(GL_TRIANGLE_STRIP, 0, 4, count);
        glBindVertexArray(0);
        glEnable(GL_CULL_FACE);
        glDepthMask(GL_TRUE);
        glDisable(GL_BLEND);
    }

    // Clear `t` to a grey level `sky` (black space; a mid grey shows the
    // puffs' 1 - alpha too).
    static void clear(renderer::HdrTarget& t, float sky = 0.0f) {
        t.bind();
        glClearColor(sky, sky, sky, 1.0f);
        glEnable(GL_DEPTH_TEST);
        glDepthMask(GL_TRUE);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    }
    static std::vector<float> read(const renderer::HdrTarget& t) {
        std::vector<float> px(static_cast<std::size_t>(kW) * kH * 4);
        glBindFramebuffer(GL_READ_FRAMEBUFFER, t.fbo());
        glReadPixels(0, 0, kW, kH, GL_RGBA, GL_FLOAT, px.data());
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        return px;
    }
};

}  // namespace

TEST_F(RockPuffGLTest, TheFillCutKeepsThePictureWithinOneLevel) {
    rf::PuffField field;
    field.set_dials(rf::PuffDials{});   // the production puff dials
    field.set_sources({beol4_field()});
    const auto& puffs = field.instances();
    ASSERT_GT(puffs.size(), 100u);
    const glm::vec3 offset = glm::vec3(field.origin_sys());   // render == system here
    const rf::PuffDials d = field.dials();
    const renderer::Lighting l = puff_lighting();

    renderer::FarPass pass;
    pass.upload_rock_puffs(puffs);
    upload_reference(puffs);
    renderer::HdrTarget t;
    t.resize(kW, kH);

    const glm::vec3 c(0.0f);
    const glm::vec3 side = glm::normalize(glm::vec3(-0.59f, 0.84f, -0.27f));
    struct View { const char* name; glm::vec3 eye, target; float fov; };
    const View views[] = {
        {"outside 6000", c + side * 6000.0f, c, 30.0f},
        {"outside 2000", c + side * 2000.0f, c, 30.0f},
        {"edge 1100", c + side * 1100.0f, c, 60.0f},
        {"inside 700", c + side * 700.0f, c, 60.0f},
        {"centre", c, c + glm::vec3(0.0f, 1.0f, 0.1f), 60.0f},
    };
    for (const float sky : {0.0f, 0.3f})
        for (const View& v : views) {
            const scenegraph::Camera cam = camera_at(v.eye, v.target, v.fov);
            clear(t, sky);
            draw_reference(offset, d, cam, l);
            const auto ref = read(t);
            clear(t, sky);
            pass.render_rock_puffs(offset, d, cam, *pipeline, l, 1.0f);
            const auto now = read(t);
            ASSERT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
            float worst = 0.0f, covered = 0.0f;
            for (std::size_t i = 0; i < ref.size(); i += 4)
                for (int k = 0; k < 3; ++k) {
                    worst = std::max(worst, std::fabs(now[i + k] - ref[i + k]));
                    covered = std::max(covered, std::fabs(ref[i + k] - sky));
                }
            std::printf("[puff fill cut] sky %.1f, %s: worst |diff| %.5f (%.3f/255), puffs change "
                        "the sky by up to %.3f\n", sky, v.name, worst, worst * 255.0f, covered);
            EXPECT_GT(covered, 2.0f / 255.0f) << v.name << ": precondition -- the puffs must show";
            EXPECT_LE(worst, 1.0f / 255.0f) << v.name << " over sky " << sky;
        }
}

// A puff whose peak alpha is under the threshold draws no fragment at all
// (rock_puff.vert collapses it): the target is untouched.
TEST_F(RockPuffGLTest, APuffUnderTheThresholdDrawsNothing) {
    rf::PuffGpu g;
    g.pos = glm::vec3(0.0f, 2000.0f, 0.0f);
    g.radius = 400.0f;
    g.albedo = glm::vec3(0.5f);
    g.weight = 1.0f;
    rf::PuffDials d;
    d.start_gu = 0.0f; d.ramp_gu = 0.0f;
    renderer::FarPass pass;
    pass.upload_rock_puffs({g});
    renderer::HdrTarget t;
    t.resize(kW, kH);
    const scenegraph::Camera cam = camera_at(glm::vec3(0.0f), glm::vec3(0.0f, 1.0f, 0.0f), 60.0f);
    const renderer::Lighting l = puff_lighting();
    // Just over the threshold it draws (the precondition), just under it nothing.
    for (const float opacity : {2.0f / 2048.0f, 0.5f / 2048.0f}) {
        d.opacity = opacity;
        clear(t);
        const auto before = read(t);
        clear(t);
        pass.render_rock_puffs(glm::vec3(0.0f), d, cam, *pipeline, l, 1.0f);
        const auto after = read(t);
        int changed = 0;
        for (std::size_t i = 0; i < after.size(); ++i) changed += after[i] != before[i];
        if (opacity > 1.0f / 2048.0f) EXPECT_GT(changed, 0) << "precondition: a visible puff draws";
        else EXPECT_EQ(changed, 0) << "a puff under the threshold drew";
    }
}

// REPORTS the GPU+driver time of the puff draw before and after the fill cut
// (glFinish around 20 draws per view, 1920x1080 RGBA16F, no MSAA) on the
// views above. Asserts nothing about time: the frame profiler's GPU column
// is dead on this Mac, so this is the only headless measure of the fill.
TEST_F(RockPuffGLTest, FillCutCostReport) {
    rf::PuffField field;
    field.set_dials(rf::PuffDials{});
    field.set_sources({beol4_field()});
    const auto& puffs = field.instances();
    const glm::vec3 offset = glm::vec3(field.origin_sys());
    const rf::PuffDials d = field.dials();
    const renderer::Lighting l = puff_lighting();
    renderer::FarPass pass;
    pass.upload_rock_puffs(puffs);
    upload_reference(puffs);
    renderer::HdrTarget t;
    t.resize(1920, 1080);
    const glm::vec3 side = glm::normalize(glm::vec3(-0.59f, 0.84f, -0.27f));
    for (const float dist : {6000.0f, 2000.0f, 1100.0f, 700.0f}) {
        scenegraph::Camera cam = camera_at(side * dist, glm::vec3(0.0f), 60.0f);
        cam.aspect = 16.0f / 9.0f;
        t.bind();   // warm both programs up first (first-use compile/link work)
        draw_reference(offset, d, cam, l);
        pass.render_rock_puffs(offset, d, cam, *pipeline, l, 1.0f);
        glFinish();
        double ms[2] = {0.0, 0.0};
        for (int which = 0; which < 2; ++which) {
            t.bind();
            glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
            glFinish();
            const auto t0 = std::chrono::steady_clock::now();
            for (int i = 0; i < 20; ++i) {
                if (which == 0) draw_reference(offset, d, cam, l);
                else pass.render_rock_puffs(offset, d, cam, *pipeline, l, 1.0f);
            }
            glFinish();
            ms[which] = std::chrono::duration<double, std::milli>(
                std::chrono::steady_clock::now() - t0).count() / 20.0;
        }
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        std::printf("[puff fill cut] %.0f GU: %.3f ms per draw before, %.3f ms after (%zu puffs)\n",
                    dist, ms[0], ms[1], puffs.size());
    }
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

// ── Hash table + per-puff lighting (2026-10-18, perf-register.md P-1) ──────
// The puffs were the largest GPU cost at Vesuvi (SIG-06x). Their fragment
// shader spent ~65% of its time in 16 sine hashes and ~22% in the Lambert
// phase, which is the same for every fragment of a puff. The phase now runs
// per puff in the vertex shader and the hashes come from a table FarPass
// bakes on the GPU with the identical expression. Neither may move the
// picture.

namespace {
// The hash table must cover every lattice point the noise reads:
// p = v_corner * 2.2 + seed, |v_corner| <= 1, seed in [0, 64), and four
// octaves each 2.03x the last; vnoise reads floor(p) and floor(p) + 1.
int puff_noise_lattice_min() {
    return static_cast<int>(std::floor(-2.2 * std::pow(2.03, 3)));
}
int puff_noise_lattice_max() {
    return static_cast<int>(std::floor((2.2 + 64.0) * std::pow(2.03, 3))) + 1;
}
}  // namespace

TEST(RockPuffHashTable, CoversEveryLatticePointTheNoiseReads) {
    EXPECT_GE(puff_noise_lattice_min() + rf::kPuffHashOffset, 0);
    EXPECT_LT(puff_noise_lattice_max() + rf::kPuffHashOffset, rf::kPuffHashSize);
}

TEST(RockPuffHashTable, TheShaderUsesTheSameTableLayout) {
    const std::string fs = renderer::shader_src::rock_puff_fs;
    EXPECT_NE(fs.find("const int kHashOffset = " + std::to_string(rf::kPuffHashOffset) + ";"),
              std::string::npos);
    EXPECT_NE(fs.find("const int kHashSize = " + std::to_string(rf::kPuffHashSize) + ";"),
              std::string::npos);
}

// The cost this change removes, guarded: no sine hash and no Lambert phase
// per fragment.
TEST(RockPuffHashTable, TheFragmentShaderRunsNoTrigonometry) {
    const std::string fs = renderer::shader_src::rock_puff_fs;
    EXPECT_EQ(fs.find("sin("), std::string::npos);
    EXPECT_EQ(fs.find("acos("), std::string::npos);
}

TEST_F(RockPuffGLTest, TheBakedHashTableMatchesTheInlineHashExactly) {
    renderer::FarPass pass;
    rf::PuffGpu g;
    g.pos = glm::vec3(0.0f, 2000.0f, 0.0f);
    g.radius = 400.0f;
    g.albedo = glm::vec3(0.5f);
    g.weight = 1.0f;
    pass.upload_rock_puffs({g});
    renderer::HdrTarget t;
    t.resize(kW, kH);
    clear(t);
    rf::PuffDials d;
    d.start_gu = 0.0f; d.ramp_gu = 0.0f;
    pass.render_rock_puffs(glm::vec3(0.0f), d,
                           camera_at(glm::vec3(0.0f), glm::vec3(0.0f, 1.0f, 0.0f), 60.0f),
                           *pipeline, puff_lighting(), 1.0f);
    ASSERT_NE(pass.rock_puff_hash_texture(), 0u) << "the table is baked on first draw";
    const int n = rf::kPuffHashSize;
    std::vector<float> table(static_cast<std::size_t>(n) * n);
    glBindTexture(GL_TEXTURE_2D, pass.rock_puff_hash_texture());
    glGetTexImage(GL_TEXTURE_2D, 0, GL_RED, GL_FLOAT, table.data());

    // The inline expression, evaluated on the GPU at every lattice point.
    const char* vs = "#version 410 core\nvoid main() {\n"
        "    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);\n"
        "    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);\n}\n";
    const std::string fs = "#version 410 core\nout float h;\n"
        "float hash2(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }\n"
        "void main() { h = hash2(vec2(ivec2(gl_FragCoord.xy) - " +
        std::to_string(rf::kPuffHashOffset) + ")); }\n";
    renderer::Shader inline_hash(vs, fs);
    GLuint tex = 0, fbo = 0, vao = 0;
    glGenTextures(1, &tex);
    glBindTexture(GL_TEXTURE_2D, tex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_R32F, n, n, 0, GL_RED, GL_FLOAT, nullptr);
    glGenFramebuffers(1, &fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, tex, 0);
    glViewport(0, 0, n, n);
    glDisable(GL_DEPTH_TEST);
    glDisable(GL_BLEND);
    glGenVertexArrays(1, &vao);
    inline_hash.use();
    glBindVertexArray(vao);
    glDrawArrays(GL_TRIANGLES, 0, 3);
    glBindVertexArray(0);
    std::vector<float> expect(table.size());
    glReadPixels(0, 0, n, n, GL_RED, GL_FLOAT, expect.data());
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glDeleteVertexArrays(1, &vao);
    glDeleteFramebuffers(1, &fbo);
    glDeleteTextures(1, &tex);
    ASSERT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
    int differ = 0;
    for (std::size_t i = 0; i < table.size(); ++i) differ += table[i] != expect[i];
    EXPECT_EQ(differ, 0) << "of " << table.size() << " lattice points";
}

TEST_F(RockPuffGLTest, TheHashTableKeepsThePictureOfTheInlineHash) {
    rf::PuffField field;
    field.set_dials(rf::PuffDials{});
    field.set_sources({beol4_field()});
    const auto& puffs = field.instances();
    ASSERT_GT(puffs.size(), 100u);
    const glm::vec3 offset = glm::vec3(field.origin_sys());
    const rf::PuffDials d = field.dials();
    const renderer::Lighting l = puff_lighting();
    renderer::FarPass pass;
    pass.upload_rock_puffs(puffs);
    upload_reference(puffs);
    renderer::HdrTarget t;
    t.resize(kW, kH);
    const glm::vec3 c(0.0f);
    const glm::vec3 side = glm::normalize(glm::vec3(-0.59f, 0.84f, -0.27f));
    struct View { const char* name; glm::vec3 eye, target; float fov; };
    const View views[] = {
        {"outside 2000", c + side * 2000.0f, c, 30.0f},
        {"edge 1100", c + side * 1100.0f, c, 60.0f},
        {"inside 700", c + side * 700.0f, c, 60.0f},
        {"centre", c, c + glm::vec3(0.0f, 1.0f, 0.1f), 60.0f},
    };
    for (const float sky : {0.0f, 0.3f})
        for (const View& v : views) {
            const scenegraph::Camera cam = camera_at(v.eye, v.target, v.fov);
            clear(t, sky);
            draw_reference(offset, d, cam, l, inline_hash_shader.get());
            const auto ref = read(t);
            clear(t, sky);
            pass.render_rock_puffs(offset, d, cam, *pipeline, l, 1.0f);
            const auto now = read(t);
            ASSERT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
            float worst = 0.0f, covered = 0.0f;
            for (std::size_t i = 0; i < ref.size(); i += 4)
                for (int k = 0; k < 3; ++k) {
                    worst = std::max(worst, std::fabs(now[i + k] - ref[i + k]));
                    covered = std::max(covered, std::fabs(ref[i + k] - sky));
                }
            std::printf("[puff hash table] sky %.1f, %s: worst |diff| %.5f (%.3f/255), puffs "
                        "change the sky by up to %.3f\n", sky, v.name, worst, worst * 255.0f,
                        covered);
            EXPECT_GT(covered, 2.0f / 255.0f) << v.name << ": precondition -- the puffs must show";
            // Measured 0.06/255 (half-float rounding in a few hundred pixels).
            EXPECT_LE(worst, 0.25f / 255.0f) << v.name << " over sky " << sky;
        }
}

// REPORTS the draw's GPU+driver time with the inline hash and with the table
// (glFinish around 20 draws, 1920x1080 RGBA16F, no MSAA). Asserts nothing
// about time.
TEST_F(RockPuffGLTest, HashTableCostReport) {
    rf::PuffField field;
    field.set_dials(rf::PuffDials{});
    field.set_sources({beol4_field()});
    const auto& puffs = field.instances();
    const glm::vec3 offset = glm::vec3(field.origin_sys());
    const rf::PuffDials d = field.dials();
    const renderer::Lighting l = puff_lighting();
    renderer::FarPass pass;
    pass.upload_rock_puffs(puffs);
    upload_reference(puffs);
    renderer::HdrTarget t;
    t.resize(1920, 1080);
    const glm::vec3 side = glm::normalize(glm::vec3(-0.59f, 0.84f, -0.27f));
    for (const float dist : {2000.0f, 1100.0f, 700.0f}) {
        scenegraph::Camera cam = camera_at(side * dist, glm::vec3(0.0f), 60.0f);
        cam.aspect = 16.0f / 9.0f;
        t.bind();
        draw_reference(offset, d, cam, l, inline_hash_shader.get());
        pass.render_rock_puffs(offset, d, cam, *pipeline, l, 1.0f);
        glFinish();
        double ms[2] = {1e9, 1e9};
        for (int rep = 0; rep < 3; ++rep)
            for (int which = 0; which < 2; ++which) {
                t.bind();
                glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
                glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
                glFinish();
                const auto t0 = std::chrono::steady_clock::now();
                for (int i = 0; i < 20; ++i) {
                    if (which == 0) draw_reference(offset, d, cam, l, inline_hash_shader.get());
                    else pass.render_rock_puffs(offset, d, cam, *pipeline, l, 1.0f);
                }
                glFinish();
                ms[which] = std::min(ms[which], std::chrono::duration<double, std::milli>(
                    std::chrono::steady_clock::now() - t0).count() / 20.0);
            }
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        std::printf("[puff hash table] %.0f GU: %.3f ms per draw inline, %.3f ms table "
                    "(%zu puffs)\n", dist, ms[0], ms[1], puffs.size());
    }
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}
