// native/tests/renderer/viewscreen_brightness_test.cc
//
// Verifies that BridgePass::set_viewscreen_brightness scales the sampled
// colour of the viewscreen RTT feed. Uses the same offscreen-render +
// readback pattern as comm_pass_test.cc. Skips cleanly when no GL context
// is available (headless CI).
#include <gtest/gtest.h>

#include <renderer/bridge_pass.h>
#include <renderer/frame.h>
#include <renderer/pipeline.h>
#include <renderer/window.h>
#include <scenegraph/camera.h>
#include <scenegraph/instance.h>
#include <scenegraph/world.h>

#include <assets/material.h>
#include <assets/mesh.h>
#include <assets/model.h>

#include <glad/glad.h>
#include <glm/gtc/matrix_transform.hpp>

#include <memory>
#include <vector>

namespace {

constexpr int kW = 64;
constexpr int kH = 64;

// Build a minimal in-memory Model: a single quad mesh that will be used as
// the "viewscreen" surface. No real NIF asset needed — we just need a VAO
// with two triangles and a non-lightmap material so draw_mesh reaches the
// base_override path.
static std::unique_ptr<assets::Model> make_quad_model() {
    // Vertices: position(3) + normal(3) + uv(2) + uv1(2) = 10 floats each
    // Two triangles forming a [-1,1] quad in XY, at Z=0.
    // Layout must match the bridge shader's attribute layout.
    // We build the VAO manually here to avoid NIF I/O.
    struct Vert { float x, y, z, nx, ny, nz, u, v, u1, v1; };
    const Vert verts[4] = {
        {-1.f, -1.f, 0.f,  0,0,1,  0.f, 0.f, 0.f, 0.f},
        { 1.f, -1.f, 0.f,  0,0,1,  1.f, 0.f, 1.f, 0.f},
        { 1.f,  1.f, 0.f,  0,0,1,  1.f, 1.f, 1.f, 1.f},
        {-1.f,  1.f, 0.f,  0,0,1,  0.f, 1.f, 0.f, 1.f},
    };
    const unsigned int idx[6] = {0,1,2, 0,2,3};

    GLuint vao = 0, vbo = 0, ebo = 0;
    glGenVertexArrays(1, &vao);
    glGenBuffers(1, &vbo);
    glGenBuffers(1, &ebo);
    glBindVertexArray(vao);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ebo);
    glBufferData(GL_ELEMENT_ARRAY_BUFFER, sizeof(idx), idx, GL_STATIC_DRAW);
    constexpr GLsizei stride = sizeof(Vert);
    // attrib 0: position
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride,
                          reinterpret_cast<void*>(offsetof(Vert, x)));
    // attrib 1: normal
    glEnableVertexAttribArray(1);
    glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride,
                          reinterpret_cast<void*>(offsetof(Vert, nx)));
    // attrib 2: uv (UV set 0)
    glEnableVertexAttribArray(2);
    glVertexAttribPointer(2, 2, GL_FLOAT, GL_FALSE, stride,
                          reinterpret_cast<void*>(offsetof(Vert, u)));
    // attrib 3: uv1 (UV set 1 — dark map)
    glEnableVertexAttribArray(3);
    glVertexAttribPointer(3, 2, GL_FLOAT, GL_FALSE, stride,
                          reinterpret_cast<void*>(offsetof(Vert, u1)));
    glBindVertexArray(0);

    auto model = std::make_unique<assets::Model>();
    model->meshes.push_back(
        assets::Mesh(vao, vbo, ebo, /*index_count=*/6, /*material_index=*/0,
                     /*node_index=*/0));
    model->materials.push_back(assets::Material{});  // base pass, no lightmap

    assets::Node root_node;
    root_node.parent_index = -1;
    root_node.local_transform = glm::mat4(1.0f);
    root_node.meshes = {0};
    model->nodes.push_back(std::move(root_node));
    model->root_node = 0;

    return model;
}

// Create a 1×1 solid-colour texture to use as the viewscreen feed.
static GLuint make_solid_texture(unsigned char r, unsigned char g,
                                 unsigned char b, unsigned char a) {
    GLuint tex = 0;
    glGenTextures(1, &tex);
    glBindTexture(GL_TEXTURE_2D, tex);
    const unsigned char px[4] = {r, g, b, a};
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, 1, 1, 0, GL_RGBA,
                 GL_UNSIGNED_BYTE, px);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glBindTexture(GL_TEXTURE_2D, 0);
    return tex;
}

// Read a single RGBA pixel from the centre of the current framebuffer.
static std::array<unsigned char, 4> read_center_pixel() {
    std::array<unsigned char, 4> px{};
    glReadPixels(kW / 2, kH / 2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px.data());
    return px;
}

}  // namespace

TEST(ViewscreenBrightness, ScalesSampledFeed) {
    // ── 1. Try to acquire an offscreen GL context ──────────────────────────
    std::unique_ptr<renderer::Window> win;
    try {
        win = std::make_unique<renderer::Window>(kW, kH, "vs-brightness", false);
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context: " << e.what();
    }

    // ── 2. Build GPU objects: quad model + 1×1 white feed texture ──────────
    auto model = make_quad_model();
    GLuint feed_tex = make_solid_texture(255, 255, 255, 255);

    // ── 3. Scenegraph: one Bridge-pass instance using the quad model ────────
    scenegraph::World world;
    auto model_handle = reinterpret_cast<scenegraph::ModelHandle>(model.get());
    auto iid = world.create_instance(model_handle);
    world.set_world_transform(iid, glm::mat4(1.0f));
    world.set_pass(iid, scenegraph::Pass::Bridge);

    renderer::BridgePass::ModelLookup lookup =
        [&](unsigned long long h) -> const assets::Model* {
            return reinterpret_cast<const assets::Model*>(h);
        };

    renderer::Lighting lighting;
    lighting.ambient      = glm::vec3(1.0f);  // full ambient so any dimming is from brightness
    lighting.directional_count = 0;

    // Orthographic camera looking straight at the quad: the quad fills
    // [-1,1] in XY at Z=0; camera is at Z=5, ortho proj covers [-2,2].
    scenegraph::Camera cam;
    cam.eye    = glm::vec3(0.0f, 0.0f, 5.0f);
    cam.target = glm::vec3(0.0f, 0.0f, 0.0f);
    cam.up     = glm::vec3(0.0f, 1.0f, 0.0f);
    cam.aspect = 1.0f;
    cam.fov_y_rad = 0.5f;  // small FOV — perspective is fine for this test

    // ── 4. Pipeline ─────────────────────────────────────────────────────────
    renderer::Pipeline pipeline;

    // ── 5. Register the quad model as the viewscreen; attach the white feed ─
    const auto raw_handle = reinterpret_cast<unsigned long long>(model.get());

    // Helper: render once at a given brightness and return the centre pixel.
    auto render_at = [&](float brightness) -> std::array<unsigned char, 4> {
        renderer::BridgePass pass;
        pass.set_viewscreen_model(raw_handle);
        pass.set_viewscreen_texture(feed_tex);
        pass.set_viewscreen_brightness(brightness);

        glViewport(0, 0, kW, kH);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

        pass.render(world, cam, pipeline, lookup, lighting,
                    scenegraph::Pass::Bridge, /*comm_set_id=*/0);

        EXPECT_EQ(glGetError(), GL_NO_ERROR);
        return read_center_pixel();
    };

    // ── 6. Render at brightness 1.0 ─────────────────────────────────────────
    auto px1 = render_at(1.0f);
    // The centre pixel must be non-zero (quad covers the viewport centre).
    ASSERT_GT(static_cast<int>(px1[0]) + px1[1] + px1[2], 0)
        << "brightness=1.0 produced a black centre pixel — viewscreen override not reached";

    // ── 7. Render at brightness 0.5 ─────────────────────────────────────────
    auto px05 = render_at(0.5f);

    // ── 8. Assert that 0.5 render is roughly half of 1.0 render ────────────
    // Feed texture is white (255,255,255) and ambient is (1,1,1), so the
    // result at brightness=1.0 should be ~255 and at 0.5 should be ~127.
    // Use R channel (the feed is achromatic so all channels are identical).
    const float r1   = static_cast<float>(px1[0]);
    const float r05  = static_cast<float>(px05[0]);
    // Allow ±8 tolerance for rounding in GPU fixed-point conversion.
    EXPECT_NEAR(r05, r1 * 0.5f, 8.0f)
        << "brightness=0.5 pixel (" << static_cast<int>(px05[0])
        << ") is not ~half of brightness=1.0 pixel (" << static_cast<int>(px1[0]) << ")";

    // ── 9. Cleanup ──────────────────────────────────────────────────────────
    glDeleteTextures(1, &feed_tex);
}
