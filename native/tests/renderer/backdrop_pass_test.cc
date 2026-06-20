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

// Fixture used by the bake/sample fidelity test: skips when there is no GL
// context but does NOT skip on missing BC assets (the test is procedural-only).
class BackdropPassFixture : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window>   w;
    std::unique_ptr<renderer::Pipeline> p;

    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(256, 256, "backdrop-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        p = std::make_unique<renderer::Pipeline>();
    }
    void TearDown() override {
        p.reset();
        w.reset();
    }
};

// Helper: a column-major mat3 [right, fwd, up] pointing `fwd` at +Z.
// BC convention: right = forward × up = (0,0,1)×(0,1,0) = (-1,0,0).
// Using the correct det=+1 rotation so bake winding is preserved.
static std::vector<float> rot_forward_pz() {
    // right=-X (from forward×up), forward=+Z, up=+Y  (columns)
    return {-1,0,0,  0,0,1,  0,1,0};
}

TEST_F(BackdropPassFixture, BakeCapturesDirectionalContentAndSamplesBack) {
    // One always-on base starfield + one bright nebula pointing at +Z.
    renderer::Backdrop base;
    base.texture_path = "";
    base.kind = renderer::BackdropKind::Star;
    base.proc_kind = 0;
    base.seed = 1.0f;

    renderer::Backdrop neb;
    neb.texture_path = "";
    neb.kind = renderer::BackdropKind::Backdrop;
    neb.proc_kind = 2;                       // nebula
    neb.h_span = neb.v_span = 8.0f;          // large cap so it dominates +Z
    neb.color = glm::vec3(0.8f, 0.3f, 0.9f);
    neb.coverage = 0.9f;
    neb.seed = 5.0f;
    {
        auto m = rot_forward_pz();
        neb.world_rotation = glm::mat3(m[0],m[1],m[2], m[3],m[4],m[5], m[6],m[7],m[8]);
    }
    std::vector<renderer::Backdrop> sky = {base, neb};

    renderer::BackdropPass pass;
    ASSERT_TRUE(pass.bake(sky, *p, 0.0f));
    EXPECT_TRUE(pass.has_cubemap());
    EXPECT_EQ(pass.bakes_count(), 1);

    auto mean_center = [&](glm::vec3 look_dir) -> double {
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glViewport(0, 0, 256, 256);
        glClearColor(0, 0, 0, 1);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        scenegraph::Camera cam;
        cam.eye = glm::vec3(0.0f);
        cam.target = look_dir;
        cam.up = glm::vec3(0, 1, 0);
        cam.aspect = 1.0f;
        pass.render_cubemap(cam, *p);
        unsigned char buf[16 * 16 * 4];
        glReadPixels(120, 120, 16, 16, GL_RGBA, GL_UNSIGNED_BYTE, buf);
        double sum = 0;
        for (int i = 0; i < 16 * 16; ++i)
            sum += buf[i*4] + buf[i*4+1] + buf[i*4+2];
        return sum / (16 * 16);
    };

    const double toward = mean_center(glm::vec3(0, 0, 1));   // at the nebula
    const double away   = mean_center(glm::vec3(0, 0, -1));  // opposite
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
    EXPECT_GT(toward, away * 1.3)
        << "baked nebula should make the +Z view brighter than -Z (toward="
        << toward << " away=" << away << ")";
}

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

static renderer::Backdrop make_proc(int proc_kind, float span) {
    renderer::Backdrop b;
    b.texture_path = "";
    b.kind = renderer::BackdropKind::Backdrop;
    b.proc_kind = proc_kind;
    b.h_span = b.v_span = span;
    return b;
}

TEST(BackdropHelpers, AreProceduralRequiresAllEmptyTexturePaths) {
    std::vector<renderer::Backdrop> proc = {make_proc(0, 1.0f), make_proc(2, 1.5f)};
    EXPECT_TRUE(renderer::backdrops_are_procedural(proc));

    std::vector<renderer::Backdrop> empty;
    EXPECT_FALSE(renderer::backdrops_are_procedural(empty));

    auto mixed = proc;
    mixed[1].texture_path = "stars.tga";   // authored entry present
    EXPECT_FALSE(renderer::backdrops_are_procedural(mixed));
}

TEST(BackdropHelpers, EqualDetectsAnyFieldChange) {
    std::vector<renderer::Backdrop> a = {make_proc(0, 1.0f), make_proc(2, 1.5f)};
    auto b = a;
    EXPECT_TRUE(renderer::backdrops_equal(a, b));

    b[1].h_span = 1.6f;                    // changed span
    EXPECT_FALSE(renderer::backdrops_equal(a, b));

    auto c = a;
    c.pop_back();                          // changed size
    EXPECT_FALSE(renderer::backdrops_equal(a, c));
}

}  // namespace
