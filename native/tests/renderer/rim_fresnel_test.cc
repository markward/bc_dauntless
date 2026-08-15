// native/tests/renderer/rim_fresnel_test.cc
//
// Regression test for the Fresnel rim NaN — the source of the HDR black-square
// bug (see bloom_prefilter.frag and nonfinite_probe.h for the other half).
//
// opaque.frag computed
//     f = pow(1.0 - max(dot(n, V), 0.0), RIM_POWER)
// with n and V both normalize()d. dot() of two unit vectors can land a single
// ulp ABOVE 1.0 when a surface normal points exactly at the camera, which makes
// the base a tiny NEGATIVE number. GLSL leaves pow(x, y) undefined for x < 0,
// and implementations evaluate it as exp2(y * log2(x)) -- log2 of a negative is
// NaN. max() guards only the dot < 0 end; nothing guarded dot > 1.
//
// WHY THIS TEST DRIVES THE EXPRESSION DIRECTLY rather than rendering a ship:
// the real bug fires on roughly one pixel per few thousand frames, because it
// needs a normal within ~3e-4 rad of the view vector AND the rounding to fall
// the wrong way. A render-a-hull-and-look test would pass by luck almost every
// run, which is worse than no test -- it would read as protection while
// providing none. Feeding the degenerate dot in as a uniform makes the failure
// deterministic. The cost is that this pins the EXPRESSION FORM rather than the
// call site, so it is paired with RimEnabledPassProducesNoNonFiniteTexels in
// frame_test.cc, which exercises the real shader.

#include <gtest/gtest.h>
#include <glad/glad.h>
#include <renderer/shader.h>
#include <renderer/window.h>

#include <cmath>
#include <memory>

namespace {

// RIM_POWER from opaque.frag. If that constant moves, this should follow.
constexpr float kRimPower = 36.0f;

// Minimal fullscreen-triangle vertex shader (resolve.vert needs no attributes
// beyond position, but keeping this local avoids coupling to its varyings).
constexpr const char* kVS = R"GLSL(
#version 330 core
layout(location = 0) in vec2 a_pos;
void main() { gl_Position = vec4(a_pos, 0.0, 1.0); }
)GLSL";

// r = the OLD expression (max), g = the FIXED expression (clamp).
constexpr const char* kFS = R"GLSL(
#version 330 core
out vec4 frag_color;
uniform float u_ndv;      // stands in for dot(n, V)
uniform float u_power;
void main() {
    float old_f = pow(1.0 - max(u_ndv, 0.0), u_power);
    float new_f = pow(1.0 - clamp(u_ndv, 0.0, 1.0), u_power);
    frag_color = vec4(old_f, new_f, 0.0, 1.0);
}
)GLSL";

class RimFresnelTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    std::unique_ptr<renderer::Shader> sh;
    std::uint32_t vao = 0, vbo = 0, tex = 0, fbo = 0;

    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(64, 64, "rim-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL: " << e.what();
        }
        sh = std::make_unique<renderer::Shader>(kVS, kFS);

        const float verts[] = { -1.0f, -1.0f,   3.0f, -1.0f,   -1.0f,  3.0f };
        glGenVertexArrays(1, &vao);
        glGenBuffers(1, &vbo);
        glBindVertexArray(vao);
        glBindBuffer(GL_ARRAY_BUFFER, vbo);
        glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
        glEnableVertexAttribArray(0);
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(float), nullptr);
        glBindVertexArray(0);

        // RGBA32F so a NaN survives the readback verbatim -- an 8-bit target
        // would quietly turn the very thing under test into a 0.
        glGenTextures(1, &tex);
        glBindTexture(GL_TEXTURE_2D, tex);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA32F, 1, 1, 0, GL_RGBA, GL_FLOAT, nullptr);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
        glGenFramebuffers(1, &fbo);
        glBindFramebuffer(GL_FRAMEBUFFER, fbo);
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                               GL_TEXTURE_2D, tex, 0);
    }

    void TearDown() override {
        if (fbo) glDeleteFramebuffers(1, &fbo);
        if (tex) glDeleteTextures(1, &tex);
        if (vbo) glDeleteBuffers(1, &vbo);
        if (vao) glDeleteVertexArrays(1, &vao);
    }

    // Returns {old_expression, fixed_expression} evaluated at n_dot_v.
    std::pair<float, float> eval(float n_dot_v) {
        glBindFramebuffer(GL_FRAMEBUFFER, fbo);
        glViewport(0, 0, 1, 1);
        glDisable(GL_CULL_FACE);
        glDisable(GL_DEPTH_TEST);
        glDisable(GL_BLEND);
        sh->use();
        sh->set_float("u_ndv", n_dot_v);
        sh->set_float("u_power", kRimPower);
        glBindVertexArray(vao);
        glDrawArrays(GL_TRIANGLES, 0, 3);
        glBindVertexArray(0);

        float px[4] = {0, 0, 0, 0};
        glReadPixels(0, 0, 1, 1, GL_RGBA, GL_FLOAT, px);
        return {px[0], px[1]};
    }
};

// ── The bug: dot(n,V) one ulp over 1.0 makes the OLD form non-finite ────────
// If this ever starts reporting the old form as finite, this hardware/driver
// no longer reproduces the original failure and the pairing below stops being
// evidence -- which is worth knowing explicitly rather than silently passing.
TEST_F(RimFresnelTest, DotSlightlyOverOneMakesTheUnclampedFormNonFinite) {
    auto [old_f, new_f] = eval(1.0f + 1e-7f);
    EXPECT_FALSE(std::isfinite(old_f))
        << "expected pow(negative, 36) to be non-finite, got " << old_f;
    EXPECT_TRUE(std::isfinite(new_f));
    EXPECT_FLOAT_EQ(new_f, 0.0f) << "a face-on fragment must have zero rim";
}

// ── The fix holds across the whole degenerate neighbourhood ────────────────
TEST_F(RimFresnelTest, ClampedFormIsFiniteForAnyDot) {
    for (float d : {-2.0f, -1e-7f, 0.0f, 0.5f,
                    1.0f - 1e-7f, 1.0f, 1.0f + 1e-7f, 1.0f + 1e-3f, 2.0f}) {
        auto [old_f, new_f] = eval(d);
        (void)old_f;
        EXPECT_TRUE(std::isfinite(new_f)) << "non-finite rim at dot = " << d;
        EXPECT_GE(new_f, 0.0f) << "negative rim at dot = " << d;
        EXPECT_LE(new_f, 1.0f) << "rim above 1 at dot = " << d;
    }
}

// ── Below 1.0 the fix changes nothing ──────────────────────────────────────
// The clamp must be invisible for every ordinary fragment; this is what makes
// it a safe change rather than a re-tune of the rim's look.
TEST_F(RimFresnelTest, ClampIsIdentityBelowOne) {
    for (float d : {0.0f, 0.25f, 0.5f, 0.75f, 0.9f, 0.99f}) {
        auto [old_f, new_f] = eval(d);
        EXPECT_FLOAT_EQ(old_f, new_f) << "clamp altered the rim at dot = " << d;
    }
}

}  // namespace
