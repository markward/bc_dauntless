// native/tests/renderer/debris_pass_test.cc
//
// Tests for the debris chunk pass (hull-breach-2c Task 4).
//
// CPU tests (no GL):
//   - No active events → count() == 0 (gate check, no GL needed).
//
// GL tests (skip without a context):
//   - Push a breach event at age=0 over a solid fill: draw_events() →
//       pixel != background (chunks visible).
//   - Age past kDebrisLife: draw_events() → pixel == background (no chunks).
//   - dauntless_hull_damage::enabled() false → pixel == background (gated off).

#include <gtest/gtest.h>

#include <glad/glad.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>

#include <renderer/debris_pass.h>
#include <renderer/pipeline.h>
#include <renderer/window.h>

#include <scenegraph/camera.h>
#include <scenegraph/breach_events.h>

#include <voxel/volume.h>
#include <assets/mesh.h>

// Forward-declare the hull-damage toggle so tests can turn it on/off.
namespace dauntless_hull_damage {
    bool enabled();
    void set_enabled(bool v);
}

// cube_mesh.h is in the private renderer source tree; include directly.
#include "cube_mesh.h"
#include "debris_chunks.h"

#include <array>
#include <memory>

namespace {

constexpr int kW = 64, kH = 64;

// A small solid fill volume centered at the origin.  All 4^3 cells are solid
// (127). sample_chunk_origins will find 4^3=64 candidates inside a radius-2
// sphere centered at origin and return up to kChunkCount of them.
voxel::VoxelVolume solid_fill() {
    voxel::VoxelVolume v;
    v.dims   = {4, 4, 4};
    v.origin = {-2.f, -2.f, -2.f};
    v.cell   = {1.f, 1.f, 1.f};
    v.occ.assign(4 * 4 * 4, 127);
    return v;
}

class DebrisPassGLTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window>   w;
    std::unique_ptr<renderer::Pipeline> pipeline;

    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(kW, kH, "debris-pass-test", false);
        } catch (...) {
            GTEST_SKIP() << "no GL context";
        }
        pipeline = std::make_unique<renderer::Pipeline>();
        // Ensure the hull-damage toggle is on (default) at the start of each test.
        dauntless_hull_damage::set_enabled(true);
    }

    void TearDown() override {
        // Restore toggle to default-on so other tests are unaffected.
        dauntless_hull_damage::set_enabled(true);
    }

    std::array<unsigned char, 4> read_center() const {
        glBindFramebuffer(GL_READ_FRAMEBUFFER, 0);
        std::array<unsigned char, 4> px{};
        glReadPixels(kW/2, kH/2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px.data());
        return px;
    }

    // Sum of all RGB across the framebuffer. Robust to where the chunks land
    // (the ejection speed shifts them off the exact centre pixel), so it tests
    // "chunks visible somewhere" rather than "at the centre".
    long read_frame_sum() const {
        glBindFramebuffer(GL_READ_FRAMEBUFFER, 0);
        std::array<unsigned char, kW * kH * 4> buf{};
        glReadPixels(0, 0, kW, kH, GL_RGBA, GL_UNSIGNED_BYTE, buf.data());
        long sum = 0;
        for (int p = 0; p < kW * kH; ++p)
            sum += buf[p*4] + buf[p*4+1] + buf[p*4+2];
        return sum;
    }

    static scenegraph::Camera cam_at_z5() {
        scenegraph::Camera c;
        c.eye       = {0, 0, 5};
        c.target    = {};
        c.up        = {0, 1, 0};
        c.fov_y_rad = glm::radians(45.f);
        c.aspect    = 1.f;
        c.near      = 0.1f;
        c.far       = 50.f;
        return c;
    }

    void clear() {
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glViewport(0, 0, kW, kH);
        glClearColor(0, 0, 0, 1);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    }

    // Directly draw debris chunks bypassing the World/CarveFieldCache path.
    // Mirrors the inner draw loop from DebrisPass::render for isolated testing.
    void draw_chunks_direct(renderer::Pipeline& pl,
                            const voxel::VoxelVolume& fill,
                            const scenegraph::BreachEvent& ev,
                            float now) {
        if (!dauntless_hull_damage::enabled()) return;

        const float age = now - ev.birth_time;
        if (age >= scenegraph::kDebrisLife) return;

        const auto origins = renderer::sample_chunk_origins(
            fill, ev.center_body, ev.radius, ev.seed, renderer::kChunkCount);
        if (origins.empty()) return;

        // Build cube mesh.
        assets::Mesh cube(assets::upload_mesh(renderer::build_unit_cube()));

        glEnable(GL_DEPTH_TEST);
        glDepthMask(GL_FALSE);
        glEnable(GL_BLEND);
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
        glDisable(GL_CULL_FACE);

        const glm::vec3 light_dir = glm::normalize(glm::vec3(0.3f, 1.f, 0.2f));
        auto& shader = pl.debris_shader();
        shader.use();
        shader.set_mat4("u_model", glm::mat4(1.0f));
        shader.set_mat4("u_view",  cam_at_z5().view_matrix());
        shader.set_mat4("u_proj",  cam_at_z5().proj_matrix());
        shader.set_vec3("u_light_dir", light_dir);
        shader.set_float("u_cell_size", fill.cell.x);

        glBindVertexArray(cube.vao());

        for (int i = 0; i < static_cast<int>(origins.size()); ++i) {
            const renderer::ChunkTransform ct = renderer::chunk_transform(
                origins[static_cast<std::size_t>(i)], ev.center_body,
                age, ev.seed, i);
            if (ct.alpha <= 0.f) continue;

            const std::uint64_t ch =
                (ev.seed * 6364136223846793005ull) ^
                (static_cast<std::uint64_t>(i) * 2654435761ull);
            const float cr = 0.3f + 0.4f * static_cast<float>((ch >> 40) & 0xFFu) / 255.f;
            const float cg = 0.2f + 0.3f * static_cast<float>((ch >> 24) & 0xFFu) / 255.f;
            const float cb = 0.15f + 0.25f * static_cast<float>((ch >> 8) & 0xFFu) / 255.f;

            shader.set_vec3("u_chunk_pos",    ct.pos_body);
            shader.set_mat3("u_chunk_rot",    ct.rot);
            shader.set_vec3("u_chunk_color",  glm::vec3(cr, cg, cb));
            shader.set_float("u_chunk_alpha", ct.alpha);

            glDrawElements(GL_TRIANGLES,
                           static_cast<GLsizei>(cube.index_count()),
                           GL_UNSIGNED_INT, nullptr);
        }
        glBindVertexArray(0);
        glDepthMask(GL_TRUE);
        glDisable(GL_BLEND);
        glEnable(GL_CULL_FACE);
    }
};

} // namespace

// CPU: with no active events, ring count is 0 (gate check — no GL needed).
TEST(DebrisPassCpu, NoEventsDrawsNothing) {
    scenegraph::BreachEventRing ring;
    EXPECT_EQ(ring.count(), 0u);
}

// GL: fresh event at age=0 over solid fill → chunks appear → pixel != background.
TEST_F(DebrisPassGLTest, FreshEventDrawsChunks) {
    clear();

    scenegraph::BreachEvent ev;
    ev.center_body = {0.f, 0.f, 0.f};
    ev.radius      = 2.f;
    ev.birth_time  = 0.f;
    ev.seed        = 42;
    ev.active      = true;

    draw_chunks_direct(*pipeline, solid_fill(), ev, /*now=*/0.01f);
    glFinish();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in fresh-event draw";
    EXPECT_GT(read_frame_sum(), 100L)
        << "Frame is empty — a fresh event over a solid fill should draw "
           "visible chunks somewhere in the view";
}

// GL: event aged past kDebrisLife → draw_chunks_direct skips → pixel == background.
TEST_F(DebrisPassGLTest, ExpiredEventDrawsNothing) {
    clear();

    scenegraph::BreachEvent ev;
    ev.center_body = {0.f, 0.f, 0.f};
    ev.radius      = 2.f;
    ev.birth_time  = 0.f;
    ev.seed        = 42;
    ev.active      = true;

    // Age well past kDebrisLife.
    const float now = scenegraph::kDebrisLife + 1.f;
    draw_chunks_direct(*pipeline, solid_fill(), ev, now);
    glFinish();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in expired-event draw";
    auto px = read_center();
    EXPECT_LT(px[0] + px[1] + px[2], 16)
        << "Centre pixel is lit but event is expired — should be background";
}

// GL: hull-damage toggle off → draw skipped → pixel == background.
TEST_F(DebrisPassGLTest, ToggleOffDrawsNothing) {
    clear();
    dauntless_hull_damage::set_enabled(false);

    scenegraph::BreachEvent ev;
    ev.center_body = {0.f, 0.f, 0.f};
    ev.radius      = 2.f;
    ev.birth_time  = 0.f;
    ev.seed        = 42;
    ev.active      = true;

    draw_chunks_direct(*pipeline, solid_fill(), ev, /*now=*/0.01f);
    glFinish();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error with toggle off";
    auto px = read_center();
    EXPECT_LT(px[0] + px[1] + px[2], 16)
        << "Centre pixel is lit but hull-damage toggle is off — should be background";
}
