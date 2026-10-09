// native/tests/renderer/bridge_probe_test.cc
//
// Bridge reflection-probe infrastructure (BridgeProbe): the per-mip cubemap
// target, the six-face capture, the GGX prefilter over the mip chain and the
// split-sum BRDF LUT. Every test reads the GPU result back, so the probe
// shaders are compiled and drawn through here (shader errors are runtime).
// Every test skips cleanly when no GL context is available.
#include <gtest/gtest.h>
#include <glad/glad.h>

#include <renderer/bridge_lighting_tuning.h>
#include <renderer/bridge_probe.h>
#include <renderer/cubemap_target.h>
#include <renderer/hdr_target.h>
#include <renderer/window.h>
#include <scenegraph/camera.h>

#include <glm/glm.hpp>

#include <algorithm>
#include <cmath>
#include <memory>
#include <stdexcept>
#include <vector>

namespace {

/// Red channel of the centre texel of cube face `face` at mip `mip`.
float read_cube_texel(GLuint tex, int face, int mip) {
    glBindTexture(GL_TEXTURE_CUBE_MAP, tex);
    GLint w = 0, h = 0;
    glGetTexLevelParameteriv(GL_TEXTURE_CUBE_MAP_POSITIVE_X + face, mip, GL_TEXTURE_WIDTH, &w);
    glGetTexLevelParameteriv(GL_TEXTURE_CUBE_MAP_POSITIVE_X + face, mip, GL_TEXTURE_HEIGHT, &h);
    if (w <= 0 || h <= 0) { glBindTexture(GL_TEXTURE_CUBE_MAP, 0); return -1.0f; }
    std::vector<float> px(static_cast<size_t>(w) * h * 4);
    glGetTexImage(GL_TEXTURE_CUBE_MAP_POSITIVE_X + face, mip, GL_RGBA, GL_FLOAT, px.data());
    glBindTexture(GL_TEXTURE_CUBE_MAP, 0);
    const int x = w / 2, y = h / 2;
    return px[(static_cast<size_t>(y) * w + x) * 4];
}

/// RG of the LUT texel nearest the normalised coordinate (x = NdotV, y = rough).
glm::vec2 read_lut(GLuint lut, float x, float y) {
    glBindTexture(GL_TEXTURE_2D, lut);
    GLint w = 0, h = 0;
    glGetTexLevelParameteriv(GL_TEXTURE_2D, 0, GL_TEXTURE_WIDTH, &w);
    glGetTexLevelParameteriv(GL_TEXTURE_2D, 0, GL_TEXTURE_HEIGHT, &h);
    std::vector<float> px(static_cast<size_t>(w) * h * 2);
    glPixelStorei(GL_PACK_ALIGNMENT, 4);
    glGetTexImage(GL_TEXTURE_2D, 0, GL_RG, GL_FLOAT, px.data());
    glBindTexture(GL_TEXTURE_2D, 0);
    const int ix = std::min(w - 1, std::max(0, static_cast<int>(x * static_cast<float>(w))));
    const int iy = std::min(h - 1, std::max(0, static_cast<int>(y * static_cast<float>(h))));
    const size_t i = (static_cast<size_t>(iy) * w + ix) * 2;
    return {px[i], px[i + 1]};
}

/// CPU twin of brdf_lut.frag (standard Karis split-sum, 512 Hammersley
/// samples, a = rough^2, Smith-Schlick k = a / 2) at the texel centre the
/// shader evaluates for (x, y): an independent check of the GPU integration.
glm::vec2 cpu_split_sum(float x, float y, int size) {
    const auto centre = [size](float c) {
        const int i = std::min(size - 1, std::max(0, static_cast<int>(c * static_cast<float>(size))));
        return (static_cast<float>(i) + 0.5f) / static_cast<float>(size);
    };
    const double n_dot_v = std::max(static_cast<double>(centre(x)), 1e-3);
    const double rough = centre(y);
    const double a = rough * rough, k = a / 2.0;
    const double vx = std::sqrt(1.0 - n_dot_v * n_dot_v), vz = n_dot_v;
    const unsigned n = 512;
    double A = 0.0, B = 0.0;
    for (unsigned i = 0; i < n; ++i) {
        unsigned b = i;
        b = (b << 16) | (b >> 16);
        b = ((b & 0x55555555u) << 1) | ((b & 0xAAAAAAAAu) >> 1);
        b = ((b & 0x33333333u) << 2) | ((b & 0xCCCCCCCCu) >> 2);
        b = ((b & 0x0F0F0F0Fu) << 4) | ((b & 0xF0F0F0F0u) >> 4);
        b = ((b & 0x00FF00FFu) << 8) | ((b & 0xFF00FF00u) >> 8);
        const double x1 = double(i) / n, x2 = double(b) * 2.3283064365386963e-10;
        const double phi = 2.0 * 3.14159265358979 * x1;
        const double ct = std::sqrt((1.0 - x2) / (1.0 + (a * a - 1.0) * x2));
        const double st = std::sqrt(std::max(1.0 - ct * ct, 0.0));
        // The shader's tangent frame for N = +Z is tx = (0,-1,0), ty = (1,0,0),
        // so its H is (sin phi, -cos phi, ...) -- reproduced exactly, because
        // at 512 samples a rotated stratification differs by ~1% on tight lobes.
        const double hx = std::sin(phi) * st, hz = ct;
        const double vh = vx * hx + vz * hz;
        const double lz = 2.0 * vh * hz - vz;
        if (lz > 0.0) {
            const auto g = [k](double d) { return d / (d * (1.0 - k) + k); };
            const double vdh = std::max(vh, 0.0);
            const double gv = g(n_dot_v) * g(lz) * vdh / std::max(hz * n_dot_v, 1e-6);
            const double fc = std::pow(1.0 - vdh, 5.0);
            A += (1.0 - fc) * gv;
            B += fc * gv;
        }
    }
    return {static_cast<float>(A / n), static_cast<float>(B / n)};
}

class BridgeProbeGl : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(64, 64, "bridge-probe-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        while (glGetError() != GL_NO_ERROR) {}
    }
};

}  // namespace

TEST_F(BridgeProbeGl, CaptureFillsEachFaceWithWhatThatFaceSees) {
    renderer::BridgeProbe probe;
    ASSERT_TRUE(probe.ensure());
    EXPECT_FALSE(probe.valid());   // nothing captured yet
    // Each face clears to a colour keyed by its index: proves face order and
    // that every face was rendered.
    int face = 0;
    probe.capture(glm::vec3(0.0f), [&](const scenegraph::Camera&) {
        const float v = 0.1f * float(face + 1);
        glClearColor(v, v, v, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        ++face;
    });
    EXPECT_EQ(face, 6);
    EXPECT_TRUE(probe.valid());
    // Mip 0 of the PREFILTERED cube is a copy: +X face (index 0) reads 0.1.
    for (int f = 0; f < 6; ++f) {
        EXPECT_NEAR(read_cube_texel(probe.texture(), f, 0), 0.1f * float(f + 1), 0.01f)
            << "face " << f;
    }
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

TEST_F(BridgeProbeGl, CaptureHandsEachFaceANinetyDegreeCameraAtTheOrigin) {
    renderer::BridgeProbe probe;
    ASSERT_TRUE(probe.ensure());
    const glm::vec3 origin(3.0f, -2.0f, 7.5f);
    // The backdrop bake's face table: the camera for face i looks along +X,
    // -X, +Y, -Y, +Z, -Z in that order with these up vectors.
    const glm::vec3 dirs[6] = {{1, 0, 0}, {-1, 0, 0}, {0, 1, 0}, {0, -1, 0}, {0, 0, 1}, {0, 0, -1}};
    const glm::vec3 ups[6]  = {{0, -1, 0}, {0, -1, 0}, {0, 0, 1}, {0, 0, -1}, {0, -1, 0}, {0, -1, 0}};
    std::vector<scenegraph::Camera> seen;
    GLint vp[4] = {};
    probe.capture(origin, [&](const scenegraph::Camera& c) {
        seen.push_back(c);
        glGetIntegerv(GL_VIEWPORT, vp);
    });
    ASSERT_EQ(seen.size(), 6u);
    for (int i = 0; i < 6; ++i) {
        const auto& c = seen[static_cast<size_t>(i)];
        EXPECT_EQ(c.eye, origin) << i;
        EXPECT_LT(glm::length(glm::normalize(c.target - c.eye) - dirs[i]), 1e-5f) << i;
        EXPECT_LT(glm::length(c.up - ups[i]), 1e-5f) << i;
        EXPECT_NEAR(c.fov_y_rad, glm::radians(90.0f), 1e-5f);
        EXPECT_FLOAT_EQ(c.aspect, 1.0f);
    }
    EXPECT_EQ(vp[2], renderer::kBridgeProbeFace);
    EXPECT_EQ(vp[3], renderer::kBridgeProbeFace);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

TEST_F(BridgeProbeGl, RougherMipsBlendNeighbouringFaces) {
    renderer::BridgeProbe probe;
    ASSERT_TRUE(probe.ensure());
    int face = 0;
    probe.capture(glm::vec3(0.0f), [&](const scenegraph::Camera&) {
        const float v = (face == 0) ? 1.0f : 0.0f;   // only +X is lit
        glClearColor(v, v, v, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        ++face;
    });
    const float sharp = read_cube_texel(probe.texture(), 2, 0);   // +Y face, mip 0: black
    const float rough = read_cube_texel(probe.texture(), 2, renderer::kBridgeProbeMips - 1);
    EXPECT_NEAR(sharp, 0.0f, 0.01f);
    EXPECT_GT(rough, 0.02f);                                      // +X light bled in
    // Monotonic: the opposite face sees nothing at mip 0 and less than +Y at
    // the roughest mip; +X itself stays the brightest.
    EXPECT_LT(read_cube_texel(probe.texture(), 1, renderer::kBridgeProbeMips - 1), rough);
    EXPECT_GT(read_cube_texel(probe.texture(), 0, renderer::kBridgeProbeMips - 1), rough);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

/// The LUT agrees with the CPU twin at a spread of points.
void expect_lut_matches_cpu_twin(GLuint lut) {
    const float pts[][2] = {{0.05f, 0.05f}, {0.05f, 0.95f}, {0.5f, 0.5f},
                            {0.2f, 0.3f},   {0.9f, 0.8f},   {0.99f, 0.05f}};
    for (const auto& p : pts) {
        const glm::vec2 gpu = read_lut(lut, p[0], p[1]);
        const glm::vec2 cpu = cpu_split_sum(p[0], p[1], renderer::kBridgeBrdfLutSize);
        EXPECT_NEAR(gpu.x, cpu.x, 0.002f) << p[0] << "," << p[1];
        EXPECT_NEAR(gpu.y, cpu.y, 0.002f) << p[0] << "," << p[1];
    }
}

TEST_F(BridgeProbeGl, BrdfLutMatchesTheKnownSplitSumCorners) {
    renderer::BrdfLut owner;
    ASSERT_TRUE(owner.ensure());
    const GLuint lut = owner.texture();
    ASSERT_NE(lut, 0u);
    // Head-on, smooth: A ≈ 1, B ≈ 0. Grazing, rough: A + B small.
    const glm::vec2 smooth_head_on = read_lut(lut, /*n_dot_v=*/0.99f, /*rough=*/0.05f);
    EXPECT_GT(smooth_head_on.x, 0.9f);
    EXPECT_LT(smooth_head_on.y, 0.05f);
    // Grazing: a rough surface reflects less than a smooth one (energy lost
    // to the wide lobe and shadowing); the smooth one is Fresnel-dominated.
    // (The brief's "A + B < 0.5" at (0.05, 0.95) does not hold for the
    // standard Karis LUT -- its value there is ~0.61, see cpu_split_sum.)
    const glm::vec2 rough_grazing = read_lut(lut, 0.05f, 0.95f);
    const glm::vec2 smooth_grazing = read_lut(lut, 0.05f, 0.05f);
    EXPECT_LT(rough_grazing.x + rough_grazing.y, smooth_grazing.x + smooth_grazing.y);
    EXPECT_GT(smooth_grazing.y, smooth_grazing.x);   // Fresnel bias dominates
    // The whole integration agrees with an independent CPU twin.
    expect_lut_matches_cpu_twin(lut);
    // Generated once per owner: ensure() again keeps the same texture.
    ASSERT_TRUE(owner.ensure());
    EXPECT_EQ(owner.texture(), lut);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

TEST_F(BridgeProbeGl, BrdfLutIsRegeneratedInARecreatedContext) {
    // A recreated window can hand back the same GLFWwindow*, and its fresh
    // context restarts texture names at 1 -- so a handle cached across
    // contexts would name one of the NEW context's unrelated textures.
    {
        renderer::BrdfLut first;
        ASSERT_TRUE(first.ensure());
        expect_lut_matches_cpu_twin(first.texture());
    }
    w.reset();
    w = std::make_unique<renderer::Window>(64, 64, "bridge-probe-test-2", false);
    GLuint unrelated[4] = {};
    glGenTextures(4, unrelated);
    for (GLuint t : unrelated) {
        glBindTexture(GL_TEXTURE_2D, t);
        const float zero[2 * 4 * 4] = {};
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RG16F, 4, 4, 0, GL_RG, GL_FLOAT, zero);
    }
    glBindTexture(GL_TEXTURE_2D, 0);
    renderer::BrdfLut second;
    ASSERT_TRUE(second.ensure());
    for (GLuint t : unrelated) EXPECT_NE(second.texture(), t);
    expect_lut_matches_cpu_twin(second.texture());
    glDeleteTextures(4, unrelated);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

TEST_F(BridgeProbeGl, BrdfLutDestructorReleasesItsTexture) {
    GLuint name = 0;
    {
        renderer::BrdfLut lut;
        ASSERT_TRUE(lut.ensure());
        name = lut.texture();
        EXPECT_TRUE(glIsTexture(name));
    }
    EXPECT_FALSE(glIsTexture(name));
}

TEST_F(BridgeProbeGl, PrefilterBeforeAnyCaptureIsANoOp) {
    renderer::BridgeProbe probe;
    ASSERT_TRUE(probe.ensure());
    probe.prefilter();
    EXPECT_FALSE(probe.valid());
    probe.capture(glm::vec3(0.0f), [](const scenegraph::Camera&) {});
    EXPECT_TRUE(probe.valid());
    probe.prefilter();   // re-run after a capture is fine
    EXPECT_TRUE(probe.valid());
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

TEST_F(BridgeProbeGl, ACaptureThatThrowsStillRestoresTheCallersState) {
    renderer::HdrTarget t;
    t.resize(64, 48);
    t.bind();
    glViewport(0, 0, 64, 48);
    renderer::BridgeProbe probe;
    ASSERT_TRUE(probe.ensure());
    int faces = 0;
    EXPECT_THROW(
        probe.capture(glm::vec3(0.0f), [&](const scenegraph::Camera&) {
            if (++faces == 3) throw std::runtime_error("draw failed");
        }),
        std::runtime_error);
    GLint fbo = 0, vp[4] = {};
    glGetIntegerv(GL_FRAMEBUFFER_BINDING, &fbo);
    glGetIntegerv(GL_VIEWPORT, vp);
    EXPECT_EQ(static_cast<GLuint>(fbo), t.fbo());
    EXPECT_EQ(vp[2], 64);
    EXPECT_EQ(vp[3], 48);
    EXPECT_FALSE(probe.valid());   // a partial capture is not a capture
    probe.prefilter();
    EXPECT_FALSE(probe.valid());
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

TEST_F(BridgeProbeGl, CaptureRestoresTheCallersFramebufferAndViewport) {
    renderer::HdrTarget t;
    t.resize(64, 48);
    t.bind();
    glViewport(0, 0, 64, 48);
    renderer::BridgeProbe probe;
    ASSERT_TRUE(probe.ensure());
    probe.capture(glm::vec3(0.0f), [](const scenegraph::Camera&) {});
    GLint fbo = 0, vp[4] = {};
    glGetIntegerv(GL_FRAMEBUFFER_BINDING, &fbo);
    glGetIntegerv(GL_VIEWPORT, vp);
    EXPECT_EQ(static_cast<GLuint>(fbo), t.fbo());
    EXPECT_EQ(vp[2], 64);
    EXPECT_EQ(vp[3], 48);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

TEST_F(BridgeProbeGl, CaptureRestoresProgramTextureAndClearState) {
    // A FRESH probe and LUT: their first ensure() (GL object creation) runs
    // inside capture() / ensure() below, with the caller on unit 3.
    renderer::BridgeProbe probe;
    renderer::BrdfLut lut;
    GLuint tex = 0;
    glGenTextures(1, &tex);
    glActiveTexture(GL_TEXTURE3);
    glBindTexture(GL_TEXTURE_CUBE_MAP, tex);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_CUBE_MAP, tex);
    glActiveTexture(GL_TEXTURE3);
    glClearColor(0.25f, 0.5f, 0.75f, 1.0f);
    glEnable(GL_DEPTH_TEST);
    glUseProgram(0);

    probe.capture(glm::vec3(0.0f), [](const scenegraph::Camera&) {});
    ASSERT_TRUE(probe.valid());
    ASSERT_TRUE(lut.ensure());

    GLint active = 0, cube0 = 0, cube3 = 0, prog = -1;
    glGetIntegerv(GL_ACTIVE_TEXTURE, &active);
    EXPECT_EQ(active, GL_TEXTURE3);
    glGetIntegerv(GL_TEXTURE_BINDING_CUBE_MAP, &cube3);
    glActiveTexture(GL_TEXTURE0);
    glGetIntegerv(GL_TEXTURE_BINDING_CUBE_MAP, &cube0);
    EXPECT_EQ(static_cast<GLuint>(cube0), tex);
    EXPECT_EQ(static_cast<GLuint>(cube3), tex);
    glGetIntegerv(GL_CURRENT_PROGRAM, &prog);
    EXPECT_EQ(prog, 0);
    GLfloat cc[4] = {};
    glGetFloatv(GL_COLOR_CLEAR_VALUE, cc);
    EXPECT_FLOAT_EQ(cc[0], 0.25f);
    EXPECT_FLOAT_EQ(cc[2], 0.75f);
    EXPECT_TRUE(glIsEnabled(GL_DEPTH_TEST));
    glDisable(GL_DEPTH_TEST);
    glBindTexture(GL_TEXTURE_CUBE_MAP, 0);
    glDeleteTextures(1, &tex);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

TEST_F(BridgeProbeGl, CubemapTargetAllocatesEveryMipAndBindsItAtItsSize) {
    renderer::CubemapTarget c;
    ASSERT_TRUE(c.allocate(64, 4));
    glBindTexture(GL_TEXTURE_CUBE_MAP, c.texture());
    GLint max_level = -1;
    glGetTexParameteriv(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_MAX_LEVEL, &max_level);
    EXPECT_EQ(max_level, 3);
    for (int f = 0; f < 6; ++f) {
        GLint w3 = 0;
        glGetTexLevelParameteriv(GL_TEXTURE_CUBE_MAP_POSITIVE_X + f, 3, GL_TEXTURE_WIDTH, &w3);
        EXPECT_EQ(w3, 8) << f;
    }
    glBindTexture(GL_TEXTURE_CUBE_MAP, 0);
    c.bind_face(5, 2);
    GLint vp[4] = {};
    glGetIntegerv(GL_VIEWPORT, vp);
    EXPECT_EQ(vp[2], 16);
    EXPECT_EQ(vp[3], 16);
    GLint level = -1;
    glGetFramebufferAttachmentParameteriv(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                                          GL_FRAMEBUFFER_ATTACHMENT_TEXTURE_LEVEL, &level);
    EXPECT_EQ(level, 2);
    EXPECT_EQ(glCheckFramebufferStatus(GL_FRAMEBUFFER),
              static_cast<GLenum>(GL_FRAMEBUFFER_COMPLETE));
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

TEST_F(BridgeProbeGl, CubemapTargetSingleLevelAllocateKeepsTheBackdropDefaults) {
    // allocate(n) == allocate(n, 1): the backdrop relies on the default
    // MAX_LEVEL so its generate_mips() builds a full chain.
    renderer::CubemapTarget c;
    ASSERT_TRUE(c.allocate(32));
    glBindTexture(GL_TEXTURE_CUBE_MAP, c.texture());
    GLint max_level = -1;
    glGetTexParameteriv(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_MAX_LEVEL, &max_level);
    EXPECT_EQ(max_level, 1000);
    GLint w1 = -1;
    glGetTexLevelParameteriv(GL_TEXTURE_CUBE_MAP_POSITIVE_X, 1, GL_TEXTURE_WIDTH, &w1);
    EXPECT_EQ(w1, 0);   // only level 0 allocated
    glBindTexture(GL_TEXTURE_CUBE_MAP, 0);
    c.bind_face(0);
    GLint vp[4] = {};
    glGetIntegerv(GL_VIEWPORT, vp);
    EXPECT_EQ(vp[2], 32);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}
