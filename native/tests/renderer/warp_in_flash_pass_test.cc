// native/tests/renderer/warp_in_flash_pass_test.cc
//
// GL tests for WarpInFlashPass (warp-in spec 6.3) through the REAL shaders
// (Pipeline compiles them, so a GLSL error fails here, not only at runtime):
// the flash draws additively, and a nearer depth hides it.
#include <gtest/gtest.h>
#include <renderer/warp_in_flash_pass.h>
#include <renderer/pipeline.h>
#include <renderer/window.h>
#include <scenegraph/camera.h>

#include <glad/glad.h>
#include <glm/glm.hpp>

#include <memory>
#include <stdexcept>
#include <vector>

namespace {

constexpr int kSize = 64;

class WarpInFlashPassTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window>   window;
    std::unique_ptr<renderer::Pipeline> pipeline;

    void SetUp() override {
        try {
            window = std::make_unique<renderer::Window>(kSize, kSize, "warp-in-flash-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        pipeline = std::make_unique<renderer::Pipeline>();
    }
    void TearDown() override {
        pipeline.reset();
        window.reset();
    }

    static scenegraph::Camera camera() {
        scenegraph::Camera cam;
        cam.eye    = {0.0f, 0.0f, 3.0f};
        cam.target = {0.0f, 0.0f, 0.0f};
        cam.up     = {0.0f, 1.0f, 0.0f};
        cam.aspect = 1.0f;
        return cam;
    }

    // Window depth of a point `dist` in front of the camera.
    static double window_depth_at(const scenegraph::Camera& cam, float dist) {
        const glm::vec4 clip = cam.proj_matrix() * glm::vec4(0.0f, 0.0f, -dist, 1.0f);
        return 0.5 * static_cast<double>(clip.z / clip.w) + 0.5;
    }

    static renderer::WarpInFlashDescriptor flash_at_origin() {
        renderer::WarpInFlashDescriptor f;
        f.world_center = {0.0f, 0.0f, 0.0f};
        f.forward      = {1.0f, 0.0f, 0.0f};
        f.radius       = 0.2f;
        f.age          = 0.1f;
        f.lifetime     = 1.0f;
        return f;
    }

    // Summed RGB over the frame after drawing `flashes` over a black clear
    // whose depth is `clear_depth`.
    std::vector<unsigned char> render_pixels(
            const std::vector<renderer::WarpInFlashDescriptor>& flashes,
            double clear_depth, const renderer::WarpInFlashParams& params,
            const glm::vec3& clear_rgb) {
        glViewport(0, 0, kSize, kSize);
        glClearColor(clear_rgb.r, clear_rgb.g, clear_rgb.b, 1.0f);
        glClearDepth(clear_depth);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        glClearDepth(1.0);
        renderer::WarpInFlashPass pass;
        pass.render(camera(), flashes, params, *pipeline);
        std::vector<unsigned char> px(kSize * kSize * 4);
        glReadPixels(0, 0, kSize, kSize, GL_RGBA, GL_UNSIGNED_BYTE, px.data());
        return px;
    }

    double render_sum(const std::vector<renderer::WarpInFlashDescriptor>& flashes,
                      double clear_depth,
                      const renderer::WarpInFlashParams& params = {}) {
        const std::vector<unsigned char> px =
            render_pixels(flashes, clear_depth, params, {0.0f, 0.0f, 0.0f});
        double sum = 0.0;
        for (std::size_t i = 0; i < px.size(); i += 4) {
            sum += px[i] + px[i + 1] + px[i + 2];
        }
        return sum;
    }
};

}  // namespace

TEST_F(WarpInFlashPassTest, DrawsAdditively) {
    glEnable(GL_DEPTH_TEST);
    EXPECT_GT(render_sum({flash_at_origin()}, 1.0), 0.0);
    // Over a non-black clear every channel must be >= the clear (replace
    // blending would darken the covered pixels), and some pixel brighter.
    const glm::vec3 clear{0.5f, 0.6f, 0.7f};
    const std::vector<unsigned char> px =
        render_pixels({flash_at_origin()}, 1.0, {}, clear);
    const std::vector<unsigned char> base = render_pixels({}, 1.0, {}, clear);
    const int cr = base[0], cg = base[1], cb = base[2];
    bool brighter = false;
    for (std::size_t i = 0; i < px.size(); i += 4) {
        EXPECT_GE(px[i], cr);
        EXPECT_GE(px[i + 1], cg);
        EXPECT_GE(px[i + 2], cb);
        if (px[i] > cr || px[i + 1] > cg || px[i + 2] > cb) brighter = true;
    }
    EXPECT_TRUE(brighter);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

TEST_F(WarpInFlashPassTest, HiddenByNearerDepth) {
    // Something 1 GU in front of the camera (2 GU in front of the flash).
    // The pass must enable the depth test itself: start with it off.
    glDisable(GL_DEPTH_TEST);
    EXPECT_EQ(render_sum({flash_at_origin()}, window_depth_at(camera(), 1.0f)), 0.0);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

// Ring only: core_radii 0 zeroes the core and the streak (both guard it).
static renderer::WarpInFlashParams ring_only() {
    renderer::WarpInFlashParams p;
    p.core_radii = 0.0f;
    return p;
}

static renderer::WarpInFlashDescriptor ring_flash(const glm::vec3& forward) {
    renderer::WarpInFlashDescriptor f;
    f.world_center = {0.0f, 0.0f, 0.0f};
    f.forward      = forward;
    f.radius       = 0.2f;
    f.age          = 0.3f;   // ring at 0.9 radii, well faded in
    f.lifetime     = 1.0f;
    return f;
}

// Spec 6.3: the ring lies in the plane PERPENDICULAR to forward. Viewed along
// forward it is a full circle; edge-on (forward across the view) the plane
// contains the view direction and the quad has no area.
TEST_F(WarpInFlashPassTest, RingLiesPerpendicularToForward) {
    const double face_on = render_sum({ring_flash({0.0f, 0.0f, 1.0f})}, 1.0, ring_only());
    const double edge_on = render_sum({ring_flash({1.0f, 0.0f, 0.0f})}, 1.0, ring_only());
    EXPECT_GT(face_on, 0.0);
    EXPECT_LT(edge_on, 0.05 * face_on);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

// A degenerate forward has no ring plane and no streak axis: both are
// skipped, never drawn about a camera axis.
TEST_F(WarpInFlashPassTest, DegenerateForwardSkipsRingAndStreak) {
    EXPECT_EQ(render_sum({ring_flash({0.0f, 0.0f, 0.0f})}, 1.0, ring_only()), 0.0);
    renderer::WarpInFlashDescriptor f = flash_at_origin();
    f.forward = {0.0f, 0.0f, 0.0f};
    EXPECT_GT(render_sum({f}, 1.0), 0.0);   // the core still draws
}

// The timing params reach the shader as uniforms (not its default consts).
TEST_F(WarpInFlashPassTest, TimingParamsReachTheShader) {
    // Streak: at t = 0.6 the default streak (end 0.9) is still out; with
    // streak_end 0.5 it is gone. Ring off, so only the core is common.
    renderer::WarpInFlashParams with_streak;
    with_streak.ring_radii = 0.0f;
    renderer::WarpInFlashParams retracted = with_streak;
    retracted.streak_end = 0.5f;
    renderer::WarpInFlashDescriptor f = flash_at_origin();
    f.forward = {0.0f, 1.0f, 0.0f};   // across the view, so the ribbon shows
    f.age = 0.6f;
    EXPECT_GT(render_sum({f}, 1.0, with_streak), render_sum({f}, 1.0, retracted));

    // Ring: just after birth a slow ring_rise has barely faded in.
    renderer::WarpInFlashParams slow = ring_only();
    slow.ring_rise = 0.3f;
    renderer::WarpInFlashDescriptor r = ring_flash({0.0f, 0.0f, 1.0f});
    r.age = 0.05f;
    EXPECT_LT(render_sum({r}, 1.0, slow), render_sum({r}, 1.0, ring_only()));
}

TEST_F(WarpInFlashPassTest, RestoresGlState) {
    glDisable(GL_DEPTH_TEST);
    glDisable(GL_BLEND);
    glEnable(GL_CULL_FACE);
    glDepthMask(GL_TRUE);
    glDepthFunc(GL_LESS);
    glBlendFuncSeparate(GL_SRC_COLOR, GL_ONE_MINUS_DST_ALPHA, GL_DST_COLOR, GL_ZERO);
    render_sum({flash_at_origin()}, 1.0);
    EXPECT_FALSE(glIsEnabled(GL_DEPTH_TEST));
    EXPECT_FALSE(glIsEnabled(GL_BLEND));
    EXPECT_TRUE(glIsEnabled(GL_CULL_FACE));
    GLboolean mask = GL_FALSE;
    glGetBooleanv(GL_DEPTH_WRITEMASK, &mask);
    EXPECT_EQ(mask, static_cast<GLboolean>(GL_TRUE));
    GLint func = 0;
    glGetIntegerv(GL_DEPTH_FUNC, &func);
    EXPECT_EQ(func, GL_LESS);
    GLint src_rgb = 0, dst_rgb = 0, src_a = 0, dst_a = 0;
    glGetIntegerv(GL_BLEND_SRC_RGB, &src_rgb);
    glGetIntegerv(GL_BLEND_DST_RGB, &dst_rgb);
    glGetIntegerv(GL_BLEND_SRC_ALPHA, &src_a);
    glGetIntegerv(GL_BLEND_DST_ALPHA, &dst_a);
    EXPECT_EQ(src_rgb, GL_SRC_COLOR);
    EXPECT_EQ(dst_rgb, GL_ONE_MINUS_DST_ALPHA);
    EXPECT_EQ(src_a, GL_DST_COLOR);
    EXPECT_EQ(dst_a, GL_ZERO);
}
