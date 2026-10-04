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

    // FarPass::render_rock_puffs' uniforms and state, with the OLD shader.
    void draw_reference(const glm::vec3& offset, const rf::PuffDials& d,
                        const scenegraph::Camera& cam, const renderer::Lighting& l) {
        renderer::Shader& s = *old_shader;
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
