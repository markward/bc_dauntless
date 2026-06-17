// native/tests/renderer/breach_pass_test.cc
//
// GL compile + draw + readback test for the breach pass (Task 9). Mirrors
// hull_clip_test.cc's offscreen-window scaffolding (skips cleanly without a GL
// context). The pure select_breach_voxels logic is covered by
// native/tests/voxel/select_breach_voxels_test.cc; this test confirms the pass
// actually compiles its shader and rasterizes the interior cubes.

#include <gtest/gtest.h>

#include <glad/glad.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>

#include <renderer/breach_pass.h>
#include <renderer/pipeline.h>
#include <renderer/window.h>

#include <scenegraph/camera.h>
#include <scenegraph/hull_carve.h>

#include <voxel/volume.h>

#include <array>
#include <memory>

namespace {

constexpr int kW = 64;
constexpr int kH = 64;

class BreachPassGLTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window>   w;
    std::unique_ptr<renderer::Pipeline> pipeline;

    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(kW, kH, "breach-pass-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        pipeline = std::make_unique<renderer::Pipeline>();
    }

    std::array<unsigned char, 4> read_center() const {
        glBindFramebuffer(GL_READ_FRAMEBUFFER, 0);
        std::array<unsigned char, 4> px{0, 0, 0, 0};
        glReadPixels(kW / 2, kH / 2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px.data());
        return px;
    }

    // A single solid voxel centred at the world origin, cell size 1.
    static voxel::VoxelVolume one_voxel() {
        voxel::VoxelVolume v;
        v.dims = {1, 1, 1};
        v.origin = {-0.5f, -0.5f, -0.5f};  // voxel (0) centre = origin
        v.cell = {1.f, 1.f, 1.f};
        v.occ.assign(1, 1);
        return v;
    }

    // Orthographic camera looking down -Z at the origin; the unit voxel cube
    // (±0.5) projects to roughly the centre of the viewport.
    static scenegraph::Camera ortho_cam() {
        scenegraph::Camera c;
        c.eye    = glm::vec3(0.f, 0.f, 5.f);
        c.target = glm::vec3(0.f, 0.f, 0.f);
        c.up     = glm::vec3(0.f, 1.f, 0.f);
        c.fov_y_rad = glm::radians(45.f);
        c.aspect = 1.0f;
        c.near = 0.1f;
        c.far  = 100.f;
        return c;
    }
};

}  // namespace

// With a carve sphere covering the single solid voxel, the breach pass draws a
// colored cube at the origin → centre pixel is non-background.
TEST_F(BreachPassGLTest, DrawsCubeForCoveredVoxel) {
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glViewport(0, 0, kW, kH);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    glDisable(GL_CULL_FACE);

    renderer::BreachPass pass;
    voxel::VoxelVolume vol = one_voxel();
    scenegraph::HullCarveField carve;
    carve.add(glm::vec3(0.f, 0.f, 0.f), 2.0f);  // sphere covers the voxel
    scenegraph::Camera cam = ortho_cam();

    pass.draw_instance(vol, carve, glm::mat4(1.0f), cam, *pipeline);
    glFinish();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in breach draw";

    auto px = read_center();
    EXPECT_GT(px[0] + px[1] + px[2], 32)
        << "Centre pixel is background (R=" << (int)px[0] << " G=" << (int)px[1]
        << " B=" << (int)px[2] << ") — the breach pass should have drawn a "
           "colored interior cube over the carve hole";
}

// With NO carve spheres, the pass draws nothing → centre pixel stays clear.
TEST_F(BreachPassGLTest, NoCarvesDrawsNothing) {
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glViewport(0, 0, kW, kH);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    glDisable(GL_CULL_FACE);

    renderer::BreachPass pass;
    voxel::VoxelVolume vol = one_voxel();
    scenegraph::HullCarveField carve;  // no carves
    scenegraph::Camera cam = ortho_cam();

    pass.draw_instance(vol, carve, glm::mat4(1.0f), cam, *pipeline);
    glFinish();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in empty breach draw";

    auto px = read_center();
    EXPECT_LT(px[0] + px[1] + px[2], 16)
        << "Centre pixel is lit with no carves — the pass should be a no-op";
}
