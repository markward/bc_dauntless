// native/tests/renderer/breach_pass_test.cc
//
// Tests for the breach interior-surface pass (Task 6 / hull-breach-2b). The
// pass now extracts a dual-contour interior surface from the carved fill and
// renders it triplanar-textured (replacing the 2a colored-cube splat).
//
//  * CPU test (headless OK): build_carved_fill applies every active carve
//    sphere (fill reduced where carved).
//  * GL test (skips without a context): the pass compiles its shader and
//    rasterizes a DC mesh through a hole into the default FBO, leaving a
//    non-background (Damage-toned) pixel.

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
#include <vector>

namespace {

constexpr int kW = 64;
constexpr int kH = 64;

// An 8^3 fill, solid (127) in an inner box, with axis planes bounding it — the
// same shape dual_contour_test uses, so it is known to extract a surface.
voxel::VoxelVolume box_fill() {
    voxel::VoxelVolume v;
    v.dims = {8, 8, 8};
    v.origin = {-4.f, -4.f, -4.f};   // centre the box on the world origin
    v.cell = {1.f, 1.f, 1.f};
    v.occ.assign(8 * 8 * 8, 0);
    for (int z = 2; z <= 5; ++z)
        for (int y = 2; y <= 5; ++y)
            for (int x = 2; x <= 5; ++x)
                v.occ[v.index(x, y, z)] = 127;
    return v;
}

std::vector<glm::vec4> box_palette() {
    // 6 axis planes bounding the solid box (in this fill's body frame).
    return {{1, 0, 0, -1.5f},  {-1, 0, 0, -1.5f},
            {0, 1, 0, -1.5f},  {0, -1, 0, -1.5f},
            {0, 0, 1, -1.5f},  {0, 0, -1, -1.5f}};
}

}  // namespace

// build_carved_fill copies the source fill then applies every active carve
// sphere. Fill must be REDUCED at the carve centre. No GL needed.
TEST(BreachPassCpu, CarvedFillAppliesAllCarves) {
    voxel::VoxelVolume src = box_fill();
    // Centre voxel of the solid box: body coords ~ (0,0,0) (origin -4 + 3.5).
    const std::size_t centre = src.index(3, 3, 3);
    ASSERT_EQ(src.occ[centre], 127);

    scenegraph::HullCarveField carve;
    carve.add(glm::vec3(-0.5f, -0.5f, -0.5f), 2.0f);  // covers box centre

    voxel::VoxelVolume carved = renderer::BreachPass::build_carved_fill(src, carve);
    EXPECT_EQ(carved.dims, src.dims);
    EXPECT_LT(carved.occ[centre], src.occ[centre])
        << "carve sphere should reduce the fill at its centre";

    // A second carve in a different corner reduces a different voxel too.
    scenegraph::HullCarveField carve2;
    carve2.add(glm::vec3(-0.5f, -0.5f, -0.5f), 1.0f);
    carve2.add(glm::vec3(1.5f, 1.5f, 1.5f), 1.5f);  // covers a far corner voxel
    voxel::VoxelVolume carved2 = renderer::BreachPass::build_carved_fill(src, carve2);
    const std::size_t corner = src.index(5, 5, 5);
    ASSERT_EQ(src.occ[corner], 127);
    EXPECT_LT(carved2.occ[corner], src.occ[corner])
        << "second carve sphere should also reduce fill";
}

namespace {

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

    // Orthographic-ish camera looking down -Z at the origin; the box surface
    // projects to roughly the centre of the viewport.
    static scenegraph::Camera cam_looking_at_box() {
        scenegraph::Camera c;
        c.eye    = glm::vec3(0.f, 0.f, 12.f);
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

// With a carve sphere over the box, the pass extracts a DC surface and draws it
// triplanar-textured → the centre pixel is non-background.
TEST_F(BreachPassGLTest, DrawsInteriorSurfaceForCarvedFill) {
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glViewport(0, 0, kW, kH);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    glDisable(GL_CULL_FACE);

    renderer::BreachPass pass;
    voxel::VoxelVolume fill = box_fill();
    std::vector<glm::vec4> palette = box_palette();
    scenegraph::HullCarveField carve;
    carve.add(glm::vec3(0.f, 0.f, 0.f), 1.5f);  // a hole near the surface
    scenegraph::Camera cam = cam_looking_at_box();

    pass.draw_instance(/*instance_key=*/1, fill, palette, carve,
                       glm::mat4(1.0f), cam, *pipeline);
    glFinish();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in breach draw";

    auto px = read_center();
    EXPECT_GT(px[0] + px[1] + px[2], 24)
        << "Centre pixel is background (R=" << (int)px[0] << " G=" << (int)px[1]
        << " B=" << (int)px[2] << ") — the breach pass should have drawn the "
           "textured interior surface over the carve hole";
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
    voxel::VoxelVolume fill = box_fill();
    std::vector<glm::vec4> palette = box_palette();
    scenegraph::HullCarveField carve;  // no carves
    scenegraph::Camera cam = cam_looking_at_box();

    pass.draw_instance(/*instance_key=*/2, fill, palette, carve,
                       glm::mat4(1.0f), cam, *pipeline);
    glFinish();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in empty breach draw";

    auto px = read_center();
    EXPECT_LT(px[0] + px[1] + px[2], 16)
        << "Centre pixel is lit with no carves — the pass should be a no-op";
}
