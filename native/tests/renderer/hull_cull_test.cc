// native/tests/renderer/hull_cull_test.cc
// Phase 5a Task 2: the hull frustum test, pure math (no GL).
#include <gtest/gtest.h>

#include <renderer/frustum.h>
#include <renderer/hull_cull.h>

#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>

namespace {

using renderer::Frustum;
using renderer::hull_visible;

// Eye at the origin looking down -Z, 60 degree square view.
Frustum view() {
    const glm::mat4 proj = glm::perspective(glm::radians(60.0f), 1.0f, 0.1f, 100000.0f);
    const glm::mat4 v = glm::lookAt(glm::vec3(0.0f), glm::vec3(0, 0, -1), glm::vec3(0, 1, 0));
    return Frustum(proj * v);
}

// A world centre whose signed distance from the LEFT plane is -outside
// (outside it), starting from a point well inside at z = -100.
glm::vec3 outside_left(const Frustum& f, float outside) {
    const glm::vec4 pl = f.planes[0];
    const glm::vec3 n(pl);
    glm::vec3 c(0.0f, 0.0f, -100.0f);
    const float s = glm::dot(n, c) + pl.w;
    return c - n * (s + outside);
}

glm::mat4 at(const glm::vec3& c, float scale = 1.0f) {
    return glm::scale(glm::translate(glm::mat4(1.0f), c), glm::vec3(scale));
}

constexpr float kR = 10.0f;

TEST(HullCull, InFrontIsVisible) {
    EXPECT_TRUE(hull_visible(view(), at({0, 0, -100}), glm::vec3(0), kR, true));
}

TEST(HullCull, BehindCameraIsCulled) {
    EXPECT_FALSE(hull_visible(view(), at({0, 0, 100}), glm::vec3(0), kR, true));
}

TEST(HullCull, JustOutsideEdgeWithinSlackIsVisible) {
    const Frustum f = view();
    // Surface 3% of the radius outside: kHullCullSlack (1.05) keeps it.
    EXPECT_TRUE(hull_visible(f, at(outside_left(f, 1.03f * kR)), glm::vec3(0), kR, true));
    // Well outside: gone.
    EXPECT_FALSE(hull_visible(f, at(outside_left(f, 1.2f * kR)), glm::vec3(0), kR, true));
}

TEST(HullCull, UncullableIsAlwaysVisible) {
    EXPECT_TRUE(hull_visible(view(), at({0, 0, 100}), glm::vec3(0), kR, /*cullable=*/false));
}

TEST(HullCull, ScaleGrowsTheRadius) {
    const Frustum f = view();
    const glm::vec3 c = outside_left(f, 2.5f * kR);
    EXPECT_TRUE(hull_visible(f, at(c, 3.0f), glm::vec3(0), kR, true));
    EXPECT_FALSE(hull_visible(f, at(c, 1.0f), glm::vec3(0), kR, true));
}

TEST(HullCull, OffCentreBodyBoundMovesWithTheHull) {
    const Frustum f = view();
    // Bound centred 100 units along body +Z: with the hull origin at z=-40
    // the bound sits at z=+60, wholly behind the eye; along -Z, in front.
    EXPECT_FALSE(hull_visible(f, at({0, 0, -40}), glm::vec3(0, 0, 100), kR, true));
    EXPECT_TRUE(hull_visible(f, at({0, 0, -40}), glm::vec3(0, 0, -100), kR, true));
}

}  // namespace
