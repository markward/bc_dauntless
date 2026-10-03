// native/tests/renderer/glm_exact_test.cc
// renderer/glm_exact.h: the scalar replicas must equal glm to the BIT over
// many inputs (the rock-field equivalence digests depend on it).
#include <gtest/gtest.h>
#include <cstring>
#include <random>
#include <glm/gtc/matrix_transform.hpp>
#include <renderer/glm_exact.h>

using namespace renderer;

namespace {
template <class A, class B>
bool same_bits(const A& a, const B& b) {
    static_assert(sizeof(A) == sizeof(B));
    return std::memcmp(&a, &b, sizeof(A)) == 0;
}
struct Gen {
    std::mt19937 rng{20261003u};
    float f(float lo, float hi) { return std::uniform_real_distribution<float>(lo, hi)(rng); }
    // Mostly ordinary values, sometimes exact zeros / negative zeros / units.
    float v() {
        const int pick = static_cast<int>(rng() % 10);
        if (pick == 0) return 0.0f;
        if (pick == 1) return -0.0f;
        if (pick == 2) return (rng() & 1) ? 1.0f : -1.0f;
        return f(-1000.0f, 1000.0f) * (rng() & 1 ? 1e-3f : 1.0f);
    }
    glm::vec3 vec() { return {v(), v(), v()}; }
};
}  // namespace

TEST(GlmExact, Dot3MatchesGlmDot) {
    Gen g;
    for (int n = 0; n < 200000; ++n) {
        const glm::vec3 a = g.vec(), b = g.vec();
        const float want = glm::dot(a, b);
        const float got = glm_exact::dot3(a.x, a.y, a.z, b.x, b.y, b.z);
        ASSERT_TRUE(same_bits(want, got)) << n;
        const glm::dvec3 da(a) , db(b * 1.37f);
        ASSERT_TRUE(same_bits(glm::dot(da, db), glm_exact::dot3(da.x, da.y, da.z, db.x, db.y, db.z))) << n;
    }
}

TEST(GlmExact, MatVecMatchesGlm) {
    Gen g;
    for (int n = 0; n < 100000; ++n) {
        const glm::mat3 m(g.vec(), g.vec(), g.vec());
        const glm::vec3 v = g.vec();
        ASSERT_TRUE(same_bits(m * v, glm_exact::mul(m, v))) << n;
        ASSERT_TRUE(same_bits(glm::transpose(m) * v, glm_exact::mul_transposed(m, v))) << n;
    }
}

TEST(GlmExact, RotationMatchesGlmRotate) {
    Gen g;
    for (int n = 0; n < 100000; ++n) {
        glm::vec3 axis = g.vec();
        if (n % 7 == 0) axis = glm::vec3(0.0f, 0.0f, (n & 8) ? 1.0f : -1.0f);   // axis-aligned
        if (glm::dot(axis, axis) == 0.0f) axis.x = 0.5f;
        const float angle = (n % 11 == 0) ? 0.0f : g.f(-40.0f, 40.0f);
        const glm::mat3 want(glm::rotate(glm::mat4(1.0f), angle, axis));
        ASSERT_TRUE(same_bits(want, glm_exact::rotation(angle, axis))) << n;
    }
}

#include <renderer/far_field.h>
// far::make_impostor with precomputed views (the rock-field hot loops) is
// bit-identical to the plain one for the same view directions.
TEST(GlmExact, MakeImpostorWithViewsMatchesThePlainOne) {
    const std::vector<glm::vec3> dirs = far::oct_view_dirs(8);   // rockgen's 64 views
    const far::ImpostorViews views = far::make_impostor_views(dirs);
    Gen g;
    for (int n = 0; n < 50000; ++n) {
        glm::vec3 axis = g.vec();
        if (glm::dot(axis, axis) == 0.0f) axis.z = 1.0f;
        const glm::mat3 R(glm::rotate(glm::mat4(1.0f), g.f(-7.0f, 7.0f), axis));
        const glm::vec3 c = g.vec(), eye = (n % 13 == 0) ? c : g.vec();   // eye == c: the len 0 branch
        const float r = g.f(0.01f, 600.0f), dither = g.f(-1.0f, 1.0f);
        const far::ImpostorGpu want = far::make_impostor(dirs, eye, c, R, r, dither);
        const far::ImpostorGpu got = far::make_impostor(views, eye, c, R, r, dither);
        ASSERT_TRUE(same_bits(want, got)) << n;
    }
}
