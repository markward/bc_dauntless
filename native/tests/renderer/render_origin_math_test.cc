// The world-anchored passes under a floating render origin (system-frames
// Plan 3, Task 6). The origin follows the camera eye every frame, so in
// render space the eye sits at ~(0,0,0) and the whole world slides by the
// origin's motion. Three passes read ABSOLUTE world positions or remember
// last frame's camera, and each needs the origin folded back in:
//
//   * motion blur / nebula history reproject a static world point through
//     LAST frame's view-projection -- which was in last frame's render space;
//   * the dust field and the nebula history gate measure how far the camera
//     travelled -- the eye alone no longer moves;
//   * the dust field wraps a 2R cube of particles around the camera -- the
//     wrap must be keyed to the WORLD eye or the dust rides with the ship.
#include <renderer/render_origin.h>

#include <gtest/gtest.h>
#include <glm/gtc/matrix_transform.hpp>

#include <cmath>

using renderer::render_origin::eye_travel;
using renderer::render_origin::rebase_prev_viewproj;
using renderer::render_origin::wrap_phase;

namespace {

glm::mat4 view_proj_at_render_origin(const glm::vec3& fwd) {
    const glm::mat4 proj = glm::perspective(0.6f, 1.5f, 1.0f, 1e6f);
    const glm::mat4 view = glm::lookAt(glm::vec3(0.0f), fwd, glm::vec3(0, 0, 1));
    return proj * view;
}

}  // namespace

TEST(RenderOriginMath, PrevViewProjRebasedLandsAStaticPointWhereItWas) {
    // A static world point, the camera moving 7 GU between frames with the
    // origin glued to it: last frame saw w - o1, this frame holds w - o2.
    const glm::dvec3 w(1e6 + 5.0, 30.0, -2.0);
    const glm::dvec3 o1(1e6, 0.0, 0.0);
    const glm::dvec3 o2(1e6 + 7.0, 1.0, 0.0);
    const glm::mat4 prev = view_proj_at_render_origin({0, 1, 0});
    const glm::vec4 was = prev * glm::vec4(glm::vec3(w - o1), 1.0f);
    const glm::vec4 now_p(glm::vec3(w - o2), 1.0f);
    const glm::vec4 got = rebase_prev_viewproj(prev, o1, o2) * now_p;
    EXPECT_NEAR(got.x / got.w, was.x / was.w, 1e-5f);
    EXPECT_NEAR(got.y / got.w, was.y / was.w, 1e-5f);
    EXPECT_NEAR(got.z / got.w, was.z / was.w, 1e-6f);
    // Counter-check: WITHOUT the rebase the point reprojects elsewhere.
    const glm::vec4 naive = prev * now_p;
    EXPECT_GT(std::abs(naive.x / naive.w - was.x / was.w), 1e-2f);
}

TEST(RenderOriginMath, PrevViewProjUnmovedOriginIsUntouched) {
    const glm::mat4 prev = view_proj_at_render_origin({1, 0, 0});
    const glm::dvec3 o(123.0, 4.0, 5.0);
    EXPECT_EQ(rebase_prev_viewproj(prev, o, o), prev);
}

TEST(RenderOriginMath, EyeTravelIsTheWorldEyesMotion) {
    // The eye sits at the render origin both frames; the ORIGIN carried it.
    const glm::vec3 t = eye_travel(glm::vec3(0.0f), glm::vec3(0.0f),
                                   glm::dvec3(1e6 + 3.0, 0.0, 0.5),
                                   glm::dvec3(1e6, 0.0, 0.0));
    EXPECT_FLOAT_EQ(t.x, 3.0f);
    EXPECT_FLOAT_EQ(t.y, 0.0f);
    EXPECT_FLOAT_EQ(t.z, 0.5f);
    // Origin zero: exactly eye - prev_eye, as before.
    const glm::vec3 u = eye_travel(glm::vec3(4, 5, 6), glm::vec3(1, 1, 1),
                                   glm::dvec3(0.0), glm::dvec3(0.0));
    EXPECT_EQ(u, glm::vec3(3, 4, 5));
}

TEST(RenderOriginMath, WrapPhaseMakesTheDustFieldWorldAnchored) {
    // dust.vert: local = mod(a - eye - phase + R, 2R) - R. Keyed to the world
    // eye (eye + origin), a particle's wrapped offset is the same whether the
    // camera is described in render space plus a phase or in world space.
    const double R = 150.0;
    const glm::dvec3 origin(450000.3, -1234.7, 88.25);
    const glm::vec3 phase = wrap_phase(origin, 2.0 * R);
    const glm::dvec3 eye_r(0.25, -0.5, 1.0);
    const glm::dvec3 a(17.0, -40.0, 99.0);
    auto wrap = [&](double v) {
        double m = std::fmod(v + R, 2.0 * R);
        if (m < 0.0) m += 2.0 * R;
        return m - R;
    };
    for (int i = 0; i < 3; ++i) {
        const double world = wrap(a[i] - (eye_r[i] + origin[i]));
        const double render = wrap(a[i] - eye_r[i] - double(phase[i]));
        EXPECT_NEAR(render, world, 1e-3) << "axis " << i;
        EXPECT_GE(phase[i], 0.0f);
        EXPECT_LT(phase[i], float(2.0 * R));
    }
    EXPECT_EQ(wrap_phase(glm::dvec3(0.0), 2.0 * R), glm::vec3(0.0f));
}
