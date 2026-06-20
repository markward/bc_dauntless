// native/tests/renderer/backdrop_pass_test.cc
#include <gtest/gtest.h>
#include <vector>

#include <renderer/backdrop_pass.h>
#include <renderer/pipeline.h>
#include <renderer/window.h>
#include <scenegraph/camera.h>

#include <glad/glad.h>
#include <glm/glm.hpp>

namespace {

class BackdropPassTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> window;
    std::unique_ptr<renderer::Pipeline> pipeline;

    void SetUp() override {
        window = std::make_unique<renderer::Window>(256, 256, "backdrop_test", false);
        pipeline = std::make_unique<renderer::Pipeline>();
    }
    void TearDown() override {
        pipeline.reset();
        window.reset();
    }
};

TEST_F(BackdropPassTest, EmptyListProducesNoGLError) {
    renderer::BackdropPass pass;
    scenegraph::Camera cam;
    cam.eye = {0, 0, 1500};
    cam.target = {0, 0, 0};
    cam.aspect = 1.0f;
    pass.render({}, cam, *pipeline, /*procedural=*/false, /*now=*/0.0f);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(BackdropPassTest, SphereCacheReusesAcrossDescriptors) {
    renderer::BackdropPass pass;
    scenegraph::Camera cam;
    cam.aspect = 1.0f;

    renderer::Backdrop b1;
    b1.texture_path = "/dev/null";  // load fails; sphere still requested
    b1.target_poly_count = 256;
    renderer::Backdrop b2 = b1;  // same poly count

    pass.render({b1, b2}, cam, *pipeline, /*procedural=*/false, /*now=*/0.0f);  // both should share one sphere

    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(BackdropPassTest, TargetPolyCountSnapsToMinimum) {
    renderer::BackdropPass pass;
    scenegraph::Camera cam;
    cam.aspect = 1.0f;

    renderer::Backdrop b;
    b.target_poly_count = 1;  // below minimum
    b.texture_path = "/dev/null";

    pass.render({b}, cam, *pipeline, /*procedural=*/false, /*now=*/0.0f);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(BackdropPassTest, ProceduralRenderProducesNoGLError) {
    renderer::BackdropPass pass;
    scenegraph::Camera cam;
    cam.aspect = 1.0f;

    renderer::Backdrop b;
    b.texture_path = "/dev/null";   // texture load fails; procedural path is data-driven
    b.kind = renderer::BackdropKind::Backdrop;
    b.proc_kind = 2;                // nebula
    b.color = glm::vec3(0.6f, 0.3f, 0.7f);
    b.coverage = 0.5f;
    b.seed = 12.0f;
    b.h_span = 0.3f; b.v_span = 0.3f;

    pass.render({b}, cam, *pipeline, /*procedural=*/true, /*now=*/1.0f);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(BackdropPassTest, ProceduralNebulaPaintsItsColour) {
    renderer::BackdropPass pass;
    scenegraph::Camera cam;
    cam.eye = {0, 0, 0}; cam.target = {0, 1, 0}; cam.up = {0, 0, 1}; cam.aspect = 1.0f;

    renderer::Backdrop b;
    b.kind = renderer::BackdropKind::Backdrop;
    b.proc_kind = 2;                       // nebula
    b.color = glm::vec3(0.9f, 0.1f, 0.1f); // strongly red
    b.coverage = 0.9f; b.seed = 3.0f;
    b.h_span = 1.0f; b.v_span = 1.0f;
    // point the patch down +Y (camera looks at +Y); identity rotation maps
    // mesh (0,1,0) -> +Y, the patch centre.

    glClearColor(0, 0, 0, 1);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    pass.render({b}, cam, *pipeline, /*procedural=*/true, /*now=*/0.0f);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);

    std::vector<unsigned char> px(256 * 256 * 4);
    glReadPixels(0, 0, 256, 256, GL_RGBA, GL_UNSIGNED_BYTE, px.data());
    // accumulate channel sums over the frame
    long rsum = 0, gsum = 0, bsum = 0, lit = 0;
    for (size_t i = 0; i < px.size(); i += 4) {
        if (px[i] + px[i + 1] + px[i + 2] > 10) lit++;
        rsum += px[i]; gsum += px[i + 1]; bsum += px[i + 2];
    }
    EXPECT_GT(lit, 200);          // the nebula painted a visible patch
    EXPECT_GT(rsum, gsum * 2);    // and it reads red (its recorded colour)
    EXPECT_GT(rsum, bsum * 2);
}

TEST_F(BackdropPassTest, ToggleOffDiscardsProceduralNebula) {
    renderer::BackdropPass pass;
    scenegraph::Camera cam;
    cam.eye = {0,0,0}; cam.target = {0,1,0}; cam.up = {0,0,1}; cam.aspect = 1.0f;
    renderer::Backdrop b;
    b.kind = renderer::BackdropKind::Backdrop;
    b.texture_path = "/dev/null";  // no texture -> stock path draws nothing
    b.proc_kind = 2; b.color = glm::vec3(0.9f,0.1f,0.1f);
    b.h_span = 1.0f; b.v_span = 1.0f;

    glClearColor(0,0,0,1); glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    pass.render({b}, cam, *pipeline, /*procedural=*/false, /*now=*/0.0f);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    std::vector<unsigned char> px(256*256*4);
    glReadPixels(0,0,256,256, GL_RGBA, GL_UNSIGNED_BYTE, px.data());
    long lit = 0;
    for (size_t i=0;i<px.size();i+=4) if (px[i]+px[i+1]+px[i+2] > 10) lit++;
    EXPECT_EQ(lit, 0);  // off + no texture => stock path paints nothing
}

}  // namespace
