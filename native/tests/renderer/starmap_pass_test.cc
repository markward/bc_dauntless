// native/tests/renderer/starmap_pass_test.cc
//
// The star map draws into a scissored SUB-RECT of FBO 0, over the live scene,
// so the game and the helm menu stay visible around the modal. That makes GL
// viewport/scissor state the pass's most dangerous side effect: leaking either
// silently clips every pass that draws afterwards (and, since ui_cef's
// composite RESTORES the scissor state it found, a leak survives into the
// START of the next frame -- the exact failure letterbox_pass.cc guards
// against). These tests pin the restore.
#include <gtest/gtest.h>

#include <renderer/starmap_pass.h>
#include <renderer/pipeline.h>
#include <renderer/window.h>
#include <scenegraph/camera.h>

#include <glad/glad.h>
#include <glm/glm.hpp>

#include <memory>

TEST(StarMapPass, DisabledSceneDrawsNothing) {
    renderer::StarMapScene scene;
    scene.enabled = false;
    EXPECT_TRUE(scene.discs.empty());
    EXPECT_TRUE(scene.points.empty());
    EXPECT_EQ(scene.viewport, glm::ivec4(0));
}

TEST(StarMapPass, SceneHoldsPrimitivesInGivenOrder) {
    renderer::StarMapScene scene;
    scene.points.push_back({{0.0f, 0.0f, 0.0f}, {1.0f, 1.0f, 1.0f}, 4.0f, false});
    scene.points.push_back({{1.0f, 0.0f, 0.0f}, {1.0f, 1.0f, 1.0f}, 4.0f, true});
    ASSERT_EQ(scene.points.size(), 2u);
    EXPECT_FALSE(scene.points[0].selected);
    EXPECT_TRUE(scene.points[1].selected);

    // core_color defaults to white — a living star's pinpoint. The four-field
    // aggregate init above predates the field, and must keep meaning that.
    EXPECT_FLOAT_EQ(scene.points[0].core_color.r, 1.0f);
    EXPECT_FLOAT_EQ(scene.points[0].core_color.g, 1.0f);
    EXPECT_FLOAT_EQ(scene.points[0].core_color.b, 1.0f);

    // A burnt-out star carries its own hue in BOTH — glow matching fill, no
    // white anywhere. Python decides this (engine/ui/star_map.DEAD_STARS);
    // the struct just has to carry the two colours independently, which is
    // what lets them differ for a living star and agree for a dead one.
    renderer::StarMapPoint dead;
    dead.color      = {0.420f, 0.267f, 0.137f};
    dead.core_color = {0.420f, 0.267f, 0.137f};
    scene.points.push_back(dead);
    EXPECT_FLOAT_EQ(scene.points[2].core_color.r, 0.420f);
    EXPECT_FLOAT_EQ(scene.points[2].color.r, 0.420f);
}

// `mark` mirrors engine/ui/star_map.py's MARK_* constants, which are the sole
// source of truth. The pass must never map `mark` to a colour or size itself:
// a renumber in Python would then silently recolour every reticle. Colour and
// pixel size therefore ride on the bracket as VALUES.
TEST(StarMapPass, BracketCarriesItsOwnColourAndSize) {
    renderer::StarMapBracket b;
    EXPECT_EQ(b.mark, 0);
    EXPECT_EQ(b.position, glm::vec3(0.0f));

    renderer::StarMapBracket here{{1.0f, 2.0f, 3.0f}, 1, {1.0f, 0.88f, 0.35f}, 20.0f};
    EXPECT_EQ(here.mark, 1);
    EXPECT_EQ(here.color, glm::vec3(1.0f, 0.88f, 0.35f));
    EXPECT_FLOAT_EQ(here.size_px, 20.0f);
}

namespace {

class StarMapPassGLTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    std::unique_ptr<renderer::Pipeline> pipeline;

    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(256, 256, "starmap-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        pipeline = std::make_unique<renderer::Pipeline>();
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
    }

    // A scene with one of every primitive kind, so the restore assertions
    // cover the full draw path rather than an early return.
    static renderer::StarMapScene populated_scene() {
        renderer::StarMapScene s;
        s.enabled  = true;
        s.viewport = glm::ivec4(40, 30, 120, 90);
        s.discs.push_back({{0.0f, 0.0f, 0.0f}, {0.4f, 0.3f, 0.8f}, 60.0f, 0.5f});
        s.lines.push_back({{-50.0f, 0.0f, 0.0f}, {50.0f, 0.0f, 0.0f},
                           {0.2f, 0.2f, 0.4f}});
        s.points.push_back({{10.0f, 5.0f, 0.0f}, {0.85f, 0.88f, 0.98f}, 7.2f, true});
        s.brackets.push_back({{10.0f, 5.0f, 0.0f}, 1,
                              {1.0f, 0.88f, 0.35f}, 20.0f});
        return s;
    }

    static scenegraph::Camera map_camera() {
        scenegraph::Camera cam;
        cam.eye    = {0.0f, -300.0f, 120.0f};
        cam.target = {0.0f, 0.0f, 0.0f};
        cam.up     = {0.0f, 0.0f, 1.0f};
        cam.aspect = 1.0f;
        return cam;
    }
};

}  // namespace

TEST_F(StarMapPassGLTest, RestoresViewportAndScissorBox) {
    // The whole invariant: whatever viewport/scissor the frame was using
    // before the map drew must be byte-identical afterwards.
    glViewport(0, 0, 256, 256);
    glEnable(GL_SCISSOR_TEST);
    glScissor(7, 11, 33, 44);

    renderer::StarMapPass pass;
    pass.render(populated_scene(), map_camera(), *pipeline, 1.0f);

    GLint vp[4] = {0};
    glGetIntegerv(GL_VIEWPORT, vp);
    EXPECT_EQ(vp[0], 0);
    EXPECT_EQ(vp[1], 0);
    EXPECT_EQ(vp[2], 256);
    EXPECT_EQ(vp[3], 256);

    GLint box[4] = {0};
    glGetIntegerv(GL_SCISSOR_BOX, box);
    EXPECT_EQ(box[0], 7);
    EXPECT_EQ(box[1], 11);
    EXPECT_EQ(box[2], 33);
    EXPECT_EQ(box[3], 44);

    EXPECT_TRUE(glIsEnabled(GL_SCISSOR_TEST));
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(StarMapPassGLTest, LeavesScissorTestDisabledWhenItWasDisabled) {
    // The common case: nothing else in the frame uses scissor, so the pass
    // must hand back a DISABLED scissor test. Leaving it enabled would clip
    // the next frame's early target clears to the map rect.
    glViewport(0, 0, 256, 256);
    glDisable(GL_SCISSOR_TEST);

    renderer::StarMapPass pass;
    pass.render(populated_scene(), map_camera(), *pipeline, 1.0f);

    EXPECT_FALSE(glIsEnabled(GL_SCISSOR_TEST));
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(StarMapPassGLTest, RestoresDepthCullAndClearColour) {
    glViewport(0, 0, 256, 256);
    glEnable(GL_DEPTH_TEST);
    glDisable(GL_BLEND);
    glEnable(GL_CULL_FACE);
    glClearColor(0.25f, 0.5f, 0.75f, 1.0f);

    renderer::StarMapPass pass;
    pass.render(populated_scene(), map_camera(), *pipeline, 1.0f);

    EXPECT_TRUE(glIsEnabled(GL_DEPTH_TEST));
    EXPECT_FALSE(glIsEnabled(GL_BLEND));
    EXPECT_TRUE(glIsEnabled(GL_CULL_FACE));

    GLfloat clear[4] = {0.0f};
    glGetFloatv(GL_COLOR_CLEAR_VALUE, clear);
    EXPECT_FLOAT_EQ(clear[0], 0.25f);
    EXPECT_FLOAT_EQ(clear[1], 0.5f);
    EXPECT_FLOAT_EQ(clear[2], 0.75f);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// The pass overwrites the blend func with SRC_ALPHA/ONE_MINUS_SRC_ALPHA to
// draw. Asserting only that GL_BLEND is off again would miss a leaked FUNC
// entirely -- and a wrong blend func silently miscomposites every later pass
// rather than erroring. Set a distinctive non-default func and read all four
// factors back. (cef_composite_pass.cc restores the same four.)
TEST_F(StarMapPassGLTest, RestoresAllFourBlendFactors) {
    glViewport(0, 0, 256, 256);
    glBlendFuncSeparate(GL_ONE, GL_ZERO, GL_DST_COLOR, GL_SRC_COLOR);

    renderer::StarMapPass pass;
    pass.render(populated_scene(), map_camera(), *pipeline, 1.0f);

    GLint src_rgb = 0, dst_rgb = 0, src_a = 0, dst_a = 0;
    glGetIntegerv(GL_BLEND_SRC_RGB,   &src_rgb);
    glGetIntegerv(GL_BLEND_DST_RGB,   &dst_rgb);
    glGetIntegerv(GL_BLEND_SRC_ALPHA, &src_a);
    glGetIntegerv(GL_BLEND_DST_ALPHA, &dst_a);
    EXPECT_EQ(src_rgb, GL_ONE);
    EXPECT_EQ(dst_rgb, GL_ZERO);
    EXPECT_EQ(src_a,   GL_DST_COLOR);
    EXPECT_EQ(dst_a,   GL_SRC_COLOR);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(StarMapPassGLTest, DisabledSceneTouchesNoGLState) {
    glViewport(0, 0, 256, 256);
    glDisable(GL_SCISSOR_TEST);
    glClearColor(1.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    renderer::StarMapScene scene = populated_scene();
    scene.enabled = false;

    renderer::StarMapPass pass;
    pass.render(scene, map_camera(), *pipeline, 1.0f);

    // The framebuffer must still be the red we cleared it to: a disabled map
    // must not paint its opaque backdrop over the live scene.
    unsigned char px[4] = {0};
    glReadPixels(128, 128, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    EXPECT_EQ(px[0], 255);
    EXPECT_EQ(px[1], 0);
    EXPECT_EQ(px[2], 0);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(StarMapPassGLTest, DrawsOnlyInsideItsSubRect) {
    // Windowed, not full-screen: the live 3D scene must survive outside the
    // map rect so the game and the helm menu stay visible around the modal.
    glViewport(0, 0, 256, 256);
    glDisable(GL_SCISSOR_TEST);
    glClearColor(1.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    renderer::StarMapScene scene = populated_scene();
    scene.viewport = glm::ivec4(64, 64, 128, 128);

    renderer::StarMapPass pass;
    pass.render(scene, map_camera(), *pipeline, 1.0f);

    unsigned char inside[4] = {0};
    glReadPixels(128, 128, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, inside);
    EXPECT_LT(inside[0], 200);   // no longer pure red — the map painted here

    unsigned char outside[4] = {0};
    glReadPixels(8, 8, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, outside);
    EXPECT_EQ(outside[0], 255);  // still the scene we cleared
    EXPECT_EQ(outside[1], 0);
    EXPECT_EQ(outside[2], 0);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(StarMapPassGLTest, EmptySceneStillDrawsTheBackdropWithoutError) {
    renderer::StarMapScene scene;
    scene.enabled  = true;
    scene.viewport = glm::ivec4(0, 0, 128, 128);

    renderer::StarMapPass pass;
    pass.render(scene, map_camera(), *pipeline, 1.0f);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// The "you are here" reticle is the marker the map's whole design says the eye
// should find instantly, and it is a BRACKET -- four corner L-shapes, not four
// filled blobs. The first shader shipped `arm = 0.45` beside a hardcoded 0.55
// pair; since 1.0 - 0.45 == 0.55 the `||` clause was fully subsumed and the
// gate collapsed to `ad.x > 0.55 && ad.y > 0.55`: four solid squares, with
// `arm` a completely dead knob (editing it, reconfiguring and rebuilding
// changed nothing at all). Leg LENGTH and leg THICKNESS are now separate
// knobs, so probe the hollow inside the corner -- the one pixel that tells an
// L from a square.
TEST_F(StarMapPassGLTest, BracketDrawsLShapedCornersNotFilledSquares) {
    glViewport(0, 0, 256, 256);
    glDisable(GL_SCISSOR_TEST);

    // One bracket, at the camera target, so it projects to the exact centre
    // of the 256x256 rect. size_px is the marker's FULL width (the vertex
    // stage offsets +/- px/viewport per axis), so half-size is 50px.
    renderer::StarMapScene scene;
    scene.enabled  = true;
    scene.viewport = glm::ivec4(0, 0, 256, 256);
    scene.brackets.push_back({{0.0f, 0.0f, 0.0f}, 1, {1.0f, 1.0f, 1.0f}, 100.0f});

    renderer::StarMapPass pass;
    pass.render(scene, map_camera(), *pipeline, 1.0f);

    auto red_at = [](int x, int y) {
        unsigned char px[4] = {0};
        glReadPixels(x, y, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
        return static_cast<int>(px[0]);
    };

    // Probe pixels are DERIVED from the shader's two knobs rather than
    // hard-coded, because they depend on both. When `thick` went 0.15 -> 0.30
    // the old literals silently became wrong: the hollow probe at |d| ~ 0.71
    // fell inside the now-thicker leg, so the test failed for a reason that
    // had nothing to do with the L-shape it guards.
    //
    // These MIRROR starmap.frag. If they drift from it this test stops
    // meaning anything, so changing the shader must change them too.
    constexpr float kArm   = 0.45f;   // leg LENGTH  (fraction of half-size)
    constexpr float kThick = 0.30f;   // leg THICKNESS
    // A point on a leg lies beyond the thickness band on one axis; the hollow
    // lies inside the arm on both axes but beyond the thickness band on
    // neither. Midpoints keep both clear of the edges.
    const float on_leg  = 1.0f - kThick * 0.5f;             // 0.85
    const float in_arm  = 1.0f - (kArm + kThick) * 0.5f;    // 0.625
    auto px = [](float d) { return 128 + static_cast<int>(d * 50.0f); };

    // The top-right corner's two legs.
    EXPECT_GT(red_at(px(on_leg), px(in_arm)), 200);
    EXPECT_GT(red_at(px(in_arm), px(on_leg)), 200);

    // THE hollow, inside the corner but on neither leg. Inside the old filled
    // square; must be the backdrop, not the bracket colour.
    EXPECT_LT(red_at(px(in_arm), px(in_arm)), 128);
    // ...and the middle of the reticle stays empty, as it always did.
    EXPECT_LT(red_at(128, 128), 128);

    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(StarMapPassGLTest, ZeroSizedViewportIsANoOp) {
    glViewport(0, 0, 256, 256);
    renderer::StarMapScene scene = populated_scene();
    scene.viewport = glm::ivec4(10, 10, 0, 0);

    renderer::StarMapPass pass;
    pass.render(scene, map_camera(), *pipeline, 1.0f);

    GLint vp[4] = {0};
    glGetIntegerv(GL_VIEWPORT, vp);
    EXPECT_EQ(vp[2], 256);
    EXPECT_EQ(vp[3], 256);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}
