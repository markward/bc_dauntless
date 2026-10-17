// native/tests/renderer/bridge_probe_array_test.cc
//
// BridgeProbeArray: every bridge reflection probe in one cube-map array, plus
// a spare slot the in-flight probe is captured into and swapped in from, a
// shared raw capture cube, and a capture split into steps (one face, the mip
// chain + mip 0, one face of mip 1, or one of mips 2-5) so no frame pays for a
// whole probe. Every test reads the GPU
// result back; every test skips cleanly when no GL context is available.
#include <gtest/gtest.h>
#include <glad/glad.h>

#include <renderer/bridge_lighting_tuning.h>
#include <renderer/bridge_probe.h>
#include <renderer/bridge_probe_array.h>
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

using renderer::kBridgeProbeFace;
using renderer::kBridgeProbeMips;

int mip_size(int mip) { return std::max(1, kBridgeProbeFace >> mip); }

/// Every texel (RGB) of one face of one array layer at `mip`, read through a
/// throwaway FBO. Leaves the read framebuffer unbound.
std::vector<glm::vec3> read_array_face(GLuint tex, int layer, int face, int mip) {
    GLuint fbo = 0;
    glGenFramebuffers(1, &fbo);
    glBindFramebuffer(GL_READ_FRAMEBUFFER, fbo);
    glFramebufferTextureLayer(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, tex, mip,
                              layer * 6 + face);
    glReadBuffer(GL_COLOR_ATTACHMENT0);
    const int n = mip_size(mip);
    std::vector<float> px(static_cast<size_t>(n) * n * 4);
    glPixelStorei(GL_PACK_ALIGNMENT, 4);
    glReadPixels(0, 0, n, n, GL_RGBA, GL_FLOAT, px.data());
    glBindFramebuffer(GL_READ_FRAMEBUFFER, 0);
    glDeleteFramebuffers(1, &fbo);
    std::vector<glm::vec3> out(static_cast<size_t>(n) * n);
    for (size_t i = 0; i < out.size(); ++i) out[i] = {px[i * 4], px[i * 4 + 1], px[i * 4 + 2]};
    return out;
}

/// Every texel (RGB) of cube face `face` at `mip` of a plain cube map.
std::vector<glm::vec3> read_cube_face(GLuint tex, int face, int mip) {
    glBindTexture(GL_TEXTURE_CUBE_MAP, tex);
    const int n = mip_size(mip);
    std::vector<float> px(static_cast<size_t>(n) * n * 4);
    glPixelStorei(GL_PACK_ALIGNMENT, 4);
    glGetTexImage(GL_TEXTURE_CUBE_MAP_POSITIVE_X + face, mip, GL_RGBA, GL_FLOAT, px.data());
    glBindTexture(GL_TEXTURE_CUBE_MAP, 0);
    std::vector<glm::vec3> out(static_cast<size_t>(n) * n);
    for (size_t i = 0; i < out.size(); ++i) out[i] = {px[i * 4], px[i * 4 + 1], px[i * 4 + 2]};
    return out;
}

glm::vec3 centre(const std::vector<glm::vec3>& face, int mip) {
    const int n = mip_size(mip);
    return face[static_cast<size_t>(n / 2) * n + n / 2];
}

/// A draw_face that clears face i to colour_of(i); counts the faces drawn.
struct ClearFaces {
    glm::vec3 (*colour_of)(int);
    int* drawn;
    void operator()(const scenegraph::Camera&) const {
        const glm::vec3 c = colour_of(*drawn);
        glClearColor(c.r, c.g, c.b, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        ++*drawn;
    }
};

// Distinct per face and per channel, all positive (R11G11B10F has no sign).
glm::vec3 face_colours(int f) {
    return {0.1f * float(f + 1), 0.05f + 0.08f * float(5 - f), 0.15f + 0.1f * float(f % 3)};
}
glm::vec3 red(int) { return {1.0f, 0.0f, 0.0f}; }
glm::vec3 green(int) { return {0.0f, 1.0f, 0.0f}; }
glm::vec3 blue(int) { return {0.0f, 0.0f, 1.0f}; }

/// Run a whole probe for `slot` through the stepped capture; the number of
/// steps it took, or -1 if it never completed.
int capture_all(renderer::BridgeProbeArray& a, int slot, glm::vec3 (*colour_of)(int)) {
    int drawn = 0;
    a.begin(slot);
    for (int i = 1; i <= a.steps_per_probe() + 1; ++i) {
        // drawn == faces drawn so far == the index of the face being drawn.
        if (a.step(glm::vec3(0.0f), ClearFaces{colour_of, &drawn})) return i;
    }
    return -1;
}

class BridgeProbeArrayGl : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(64, 64, "bridge-probe-array-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        while (glGetError() != GL_NO_ERROR) {}
    }
};

}  // namespace

TEST_F(BridgeProbeArrayGl, FormatIsR11G11B10F) {
    renderer::BridgeProbeArray a;
    ASSERT_TRUE(a.ensure(1));
    ASSERT_NE(a.texture(), 0u);
    glBindTexture(GL_TEXTURE_CUBE_MAP_ARRAY, a.texture());
    GLint fmt = 0, wdt = 0, depth = 0, max_level = -1;
    glGetTexLevelParameteriv(GL_TEXTURE_CUBE_MAP_ARRAY, 0, GL_TEXTURE_INTERNAL_FORMAT, &fmt);
    glGetTexLevelParameteriv(GL_TEXTURE_CUBE_MAP_ARRAY, 0, GL_TEXTURE_WIDTH, &wdt);
    glGetTexLevelParameteriv(GL_TEXTURE_CUBE_MAP_ARRAY, 0, GL_TEXTURE_DEPTH, &depth);
    glGetTexParameteriv(GL_TEXTURE_CUBE_MAP_ARRAY, GL_TEXTURE_MAX_LEVEL, &max_level);
    GLint last = 0;
    glGetTexLevelParameteriv(GL_TEXTURE_CUBE_MAP_ARRAY, kBridgeProbeMips - 1,
                             GL_TEXTURE_WIDTH, &last);
    glBindTexture(GL_TEXTURE_CUBE_MAP_ARRAY, 0);
    EXPECT_EQ(fmt, GL_R11F_G11F_B10F);
    EXPECT_EQ(wdt, kBridgeProbeFace);
    EXPECT_EQ(depth, 2 * 6);   // one usable slot + the spare, six faces each
    EXPECT_EQ(max_level, kBridgeProbeMips - 1);
    EXPECT_EQ(last, mip_size(kBridgeProbeMips - 1));
    EXPECT_EQ(a.capacity(), 1);
    // 6 faces + (mip chain + mip 0) + mip 1 per face + mips 2-5 (ruling R9).
    EXPECT_EQ(a.steps_per_probe(), 6 + 1 + 6 + (kBridgeProbeMips - 2));
    EXPECT_FALSE(a.valid(0));
    EXPECT_FALSE(a.in_flight());
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

TEST_F(BridgeProbeArrayGl, SteppedCaptureMatchesOneShot) {
    renderer::BridgeProbe one_shot;
    int drawn = 0;
    one_shot.capture(glm::vec3(0.0f), ClearFaces{face_colours, &drawn});
    ASSERT_TRUE(one_shot.valid());

    renderer::BridgeProbeArray a;
    ASSERT_TRUE(a.ensure(2));
    const int steps = capture_all(a, 1, face_colours);
    EXPECT_EQ(steps, a.steps_per_probe());
    ASSERT_TRUE(a.valid(1));
    EXPECT_FALSE(a.valid(0));
    EXPECT_FALSE(a.in_flight());

    // One ulp of each R11G11B10F channel, relative: R and G carry a 6-bit
    // mantissa, B only 5 -- and this driver TRUNCATES on conversion (measured:
    // 0.2866 stores as 0.28125), so B's error reaches a full 1/32, not 1/64.
    const float rel_tol[3] = {1.0f / 64.0f, 1.0f / 64.0f, 1.0f / 32.0f};
    for (int mip : {0, 3}) {
        for (int f = 0; f < 6; ++f) {
            const auto ref = read_cube_face(one_shot.texture(), f, mip);
            const auto got = read_array_face(a.texture(), a.layer_of(1), f, mip);
            ASSERT_EQ(ref.size(), got.size());
            int bad = 0;
            for (size_t i = 0; i < ref.size(); ++i) {
                for (int c = 0; c < 3; ++c) {
                    const float tol = std::max(std::fabs(ref[i][c]) * rel_tol[c], 1e-3f);
                    if (std::fabs(got[i][c] - ref[i][c]) > tol && bad++ < 3) {
                        ADD_FAILURE() << "mip " << mip << " face " << f << " texel " << i
                                      << " ch " << c << ": " << got[i][c] << " vs "
                                      << ref[i][c];
                    }
                }
            }
            EXPECT_EQ(bad, 0) << "mip " << mip << " face " << f;
        }
    }
    // Sanity: the faces really are distinct (mip 0 is the capture itself).
    EXPECT_NEAR(centre(read_array_face(a.texture(), a.layer_of(1), 4, 0), 0).r, 0.5f, 0.01f);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

// Ruling R9 (measured 2026-10-17): prefiltering mip 1 is the costliest step
// by far (~9 ms avg, ~15 ms max on DBridge), so it runs as one step per face.
TEST_F(BridgeProbeArrayGl, Mip1PrefilterIsOneStepPerFace) {
    renderer::BridgeProbeArray a;
    ASSERT_TRUE(a.ensure(1));
    EXPECT_EQ(a.steps_per_probe(), 17);
    // Two red captures leave BOTH layers (the slot's and the spare) red at
    // every face and mip, so a blue texel in the spare is this capture's.
    ASSERT_EQ(capture_all(a, 0, red), a.steps_per_probe());
    ASSERT_EQ(capture_all(a, 0, red), a.steps_per_probe());
    // Two layers: the spare is whichever one slot 0 is not in.
    const int spare = 1 - a.layer_of(0);
    ASSERT_TRUE(spare == 0 || spare == 1);

    const auto blue_faces = [&](int mip) {
        int n = 0;
        for (int f = 0; f < 6; ++f) {
            const glm::vec3 c = centre(read_array_face(a.texture(), spare, f, mip), mip);
            if (c.b > 0.5f && c.r < 0.01f) ++n;
            else EXPECT_GT(c.r, 0.5f) << "mip " << mip << " face " << f << " neither";
        }
        return n;
    };

    int drawn = 0;
    a.begin(0);
    for (int i = 0; i < 7; ++i)   // six faces, then the mip chain + mip 0
        ASSERT_FALSE(a.step(glm::vec3(0.0f), ClearFaces{blue, &drawn})) << i;
    EXPECT_EQ(blue_faces(0), 6);
    EXPECT_EQ(blue_faces(1), 0);
    for (int k = 1; k <= 6; ++k) {
        ASSERT_FALSE(a.step(glm::vec3(0.0f), ClearFaces{blue, &drawn})) << k;
        EXPECT_EQ(blue_faces(1), k) << "after " << k << " mip-1 steps";
        EXPECT_EQ(blue_faces(2), 0) << "after " << k << " mip-1 steps";
    }
    // Then one step per remaining mip; the last swaps the spare in.
    for (int mip = 2; mip < kBridgeProbeMips; ++mip) {
        const bool done = a.step(glm::vec3(0.0f), ClearFaces{blue, &drawn});
        EXPECT_EQ(done, mip == kBridgeProbeMips - 1) << mip;
        if (!done) EXPECT_EQ(blue_faces(mip), 6) << mip;
    }
    EXPECT_FALSE(a.in_flight());
    EXPECT_EQ(a.layer_of(0), spare);
    EXPECT_EQ(drawn, 6);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

TEST_F(BridgeProbeArrayGl, EachFaceStepIsBoundClearedAndHandedTheCaptureCamera) {
    renderer::BridgeProbeArray a;
    ASSERT_TRUE(a.ensure(1));
    const glm::vec3 origin(3.0f, -2.0f, 7.5f);
    const glm::vec3 dirs[6] = {{1, 0, 0}, {-1, 0, 0}, {0, 1, 0}, {0, -1, 0}, {0, 0, 1}, {0, 0, -1}};
    const glm::vec3 ups[6]  = {{0, -1, 0}, {0, -1, 0}, {0, 0, 1}, {0, 0, -1}, {0, -1, 0}, {0, -1, 0}};
    std::vector<scenegraph::Camera> seen;
    a.begin(0);
    bool done = false;
    for (int i = 0; i < a.steps_per_probe() && !done; ++i) {
        done = a.step(origin, [&](const scenegraph::Camera& c) {
            seen.push_back(c);
            GLint vp[4] = {};
            glGetIntegerv(GL_VIEWPORT, vp);
            EXPECT_EQ(vp[2], kBridgeProbeFace);
            EXPECT_EQ(vp[3], kBridgeProbeFace);
            // Cleared to opaque black before the draw.
            float px[4] = {-1, -1, -1, -1};
            glReadPixels(1, 1, 1, 1, GL_RGBA, GL_FLOAT, px);
            EXPECT_FLOAT_EQ(px[0], 0.0f);
            EXPECT_FLOAT_EQ(px[3], 1.0f);
        });
        // One face per face step: the six cameras arrive over six steps.
        if (i < 6) EXPECT_EQ(seen.size(), static_cast<size_t>(i + 1));
    }
    EXPECT_TRUE(done);
    ASSERT_EQ(seen.size(), 6u);
    for (int i = 0; i < 6; ++i) {
        const auto& c = seen[static_cast<size_t>(i)];
        EXPECT_EQ(c.eye, origin) << i;
        EXPECT_LT(glm::length(glm::normalize(c.target - c.eye) - dirs[i]), 1e-5f) << i;
        EXPECT_LT(glm::length(c.up - ups[i]), 1e-5f) << i;
        EXPECT_NEAR(c.fov_y_rad, glm::radians(90.0f), 1e-5f);
        EXPECT_FLOAT_EQ(c.aspect, 1.0f);
    }
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

TEST_F(BridgeProbeArrayGl, OldContentShowsUntilTheSwap) {
    renderer::BridgeProbeArray a;
    ASSERT_TRUE(a.ensure(1));
    ASSERT_EQ(capture_all(a, 0, red), a.steps_per_probe());
    const int old_layer = a.layer_of(0);
    EXPECT_NEAR(centre(read_array_face(a.texture(), old_layer, 0, 0), 0).r, 1.0f, 0.01f);

    int drawn = 0;
    a.begin(0);
    EXPECT_TRUE(a.in_flight());
    EXPECT_EQ(a.in_flight_slot(), 0);
    for (int i = 0; i < a.steps_per_probe() - 1; ++i) {
        EXPECT_FALSE(a.step(glm::vec3(0.0f), ClearFaces{blue, &drawn})) << i;
        EXPECT_EQ(a.layer_of(0), old_layer) << i;
        EXPECT_TRUE(a.valid(0)) << i;
        for (int mip : {0, kBridgeProbeMips - 1}) {
            const glm::vec3 c = centre(read_array_face(a.texture(), a.layer_of(0), 2, mip), mip);
            EXPECT_GT(c.r, 0.5f) << "step " << i << " mip " << mip;
            EXPECT_LT(c.b, 0.01f) << "step " << i << " mip " << mip;
        }
    }
    EXPECT_TRUE(a.step(glm::vec3(0.0f), ClearFaces{blue, &drawn}));
    EXPECT_FALSE(a.in_flight());
    EXPECT_NE(a.layer_of(0), old_layer);   // the spare took its place
    for (int mip : {0, kBridgeProbeMips - 1}) {
        const glm::vec3 c = centre(read_array_face(a.texture(), a.layer_of(0), 2, mip), mip);
        EXPECT_LT(c.r, 0.01f) << mip;
        EXPECT_GT(c.b, 0.5f) << mip;
    }
    // Complete: further steps do nothing.
    EXPECT_FALSE(a.step(glm::vec3(0.0f), ClearFaces{blue, &drawn}));
    EXPECT_EQ(drawn, 6);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

TEST_F(BridgeProbeArrayGl, GrowKeepsExistingSlots) {
    renderer::BridgeProbeArray a;
    ASSERT_TRUE(a.ensure(2));
    ASSERT_EQ(capture_all(a, 0, red), a.steps_per_probe());
    ASSERT_EQ(capture_all(a, 1, face_colours), a.steps_per_probe());
    std::vector<std::vector<glm::vec3>> before;
    for (int s = 0; s < 2; ++s)
        for (int f = 0; f < 6; ++f)
            for (int m = 0; m < kBridgeProbeMips; ++m)
                before.push_back(read_array_face(a.texture(), a.layer_of(s), f, m));

    ASSERT_TRUE(a.ensure(6));
    EXPECT_EQ(a.capacity(), 6);
    ASSERT_TRUE(a.ensure(3));            // never shrinks
    EXPECT_EQ(a.capacity(), 6);
    EXPECT_TRUE(a.valid(0));
    EXPECT_TRUE(a.valid(1));
    for (int s = 2; s < 6; ++s) EXPECT_FALSE(a.valid(s)) << s;

    size_t k = 0;
    for (int s = 0; s < 2; ++s)
        for (int f = 0; f < 6; ++f)
            for (int m = 0; m < kBridgeProbeMips; ++m) {
                const auto now = read_array_face(a.texture(), a.layer_of(s), f, m);
                EXPECT_EQ(now, before[k]) << "slot " << s << " face " << f << " mip " << m;
                ++k;
            }
    // The new slots are usable.
    EXPECT_EQ(capture_all(a, 5, green), a.steps_per_probe());
    EXPECT_GT(centre(read_array_face(a.texture(), a.layer_of(5), 0, 0), 0).g, 0.9f);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

TEST_F(BridgeProbeArrayGl, GrowMidCaptureKeepsTheProbeInFlight) {
    renderer::BridgeProbeArray a;
    ASSERT_TRUE(a.ensure(1));
    int drawn = 0;
    a.begin(0);
    // All faces, mip 0 and the first face of mip 1 land before the grow.
    for (int i = 0; i < 8; ++i) ASSERT_FALSE(a.step(glm::vec3(0.0f), ClearFaces{green, &drawn}));
    ASSERT_TRUE(a.ensure(4));
    EXPECT_TRUE(a.in_flight());
    EXPECT_EQ(a.in_flight_slot(), 0);
    bool done = false;
    for (int i = 8; i < a.steps_per_probe(); ++i)
        done = a.step(glm::vec3(0.0f), ClearFaces{green, &drawn});
    EXPECT_TRUE(done);
    EXPECT_EQ(drawn, 6);
    for (int mip = 0; mip < kBridgeProbeMips; ++mip) {
        const glm::vec3 c = centre(read_array_face(a.texture(), a.layer_of(0), 1, mip), mip);
        EXPECT_GT(c.g, 0.9f) << mip;
    }
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

TEST_F(BridgeProbeArrayGl, ShrinkKeepsTheLeadingSlots) {
    renderer::BridgeProbeArray a;
    ASSERT_TRUE(a.ensure(4));
    ASSERT_EQ(capture_all(a, 0, red), a.steps_per_probe());
    ASSERT_EQ(capture_all(a, 1, green), a.steps_per_probe());
    ASSERT_EQ(capture_all(a, 3, blue), a.steps_per_probe());
    // After the recaptures the layers are permuted: shrink must follow them.
    ASSERT_EQ(capture_all(a, 0, red), a.steps_per_probe());
    std::vector<std::vector<glm::vec3>> before;
    for (int s = 0; s < 2; ++s)
        for (int m = 0; m < kBridgeProbeMips; ++m)
            before.push_back(read_array_face(a.texture(), a.layer_of(s), 3, m));

    a.shrink_to(2);
    EXPECT_EQ(a.capacity(), 2);
    EXPECT_TRUE(a.valid(0));
    EXPECT_TRUE(a.valid(1));
    EXPECT_FALSE(a.valid(3));
    EXPECT_EQ(a.layer_of(3), -1);
    glBindTexture(GL_TEXTURE_CUBE_MAP_ARRAY, a.texture());
    GLint depth = 0;
    glGetTexLevelParameteriv(GL_TEXTURE_CUBE_MAP_ARRAY, 0, GL_TEXTURE_DEPTH, &depth);
    glBindTexture(GL_TEXTURE_CUBE_MAP_ARRAY, 0);
    EXPECT_EQ(depth, 3 * 6);   // two slots + the spare
    size_t k = 0;
    for (int s = 0; s < 2; ++s)
        for (int m = 0; m < kBridgeProbeMips; ++m) {
            EXPECT_EQ(read_array_face(a.texture(), a.layer_of(s), 3, m), before[k])
                << "slot " << s << " mip " << m;
            ++k;
        }
    // A probe in flight for a slot that no longer exists is dropped.
    a.ensure(4);
    a.begin(3);
    int drawn = 0;
    a.step(glm::vec3(0.0f), ClearFaces{blue, &drawn});
    a.shrink_to(2);
    EXPECT_FALSE(a.in_flight());
    // Shrinking to nothing frees the array.
    a.shrink_to(0);
    EXPECT_EQ(a.capacity(), 0);
    EXPECT_EQ(a.texture(), 0u);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

// A slot whose meaning changed (a re-planned layer) reads as absent until a
// new capture lands in it; a probe in flight for it is dropped (it was begun
// under the old meaning), one for another slot is not.
TEST_F(BridgeProbeArrayGl, InvalidateDropsTheSlotAndItsProbeInFlight) {
    renderer::BridgeProbeArray a;
    ASSERT_TRUE(a.ensure(2));
    ASSERT_EQ(capture_all(a, 0, red), a.steps_per_probe());
    ASSERT_EQ(capture_all(a, 1, red), a.steps_per_probe());
    int drawn = 0;
    a.begin(1);
    ASSERT_FALSE(a.step(glm::vec3(0.0f), ClearFaces{blue, &drawn}));
    a.invalidate(0);
    EXPECT_FALSE(a.valid(0));
    EXPECT_TRUE(a.valid(1));
    EXPECT_EQ(a.in_flight_slot(), 1);             // another slot's probe survives
    a.invalidate(1);
    EXPECT_FALSE(a.valid(1));
    EXPECT_FALSE(a.in_flight());                  // its own is dropped
    a.invalidate(-1);                             // out of range: nothing
    a.invalidate(2);
    EXPECT_EQ(capture_all(a, 0, green), a.steps_per_probe());
    EXPECT_TRUE(a.valid(0));
    EXPECT_GT(centre(read_array_face(a.texture(), a.layer_of(0), 0, 0), 0).g, 0.9f);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

TEST_F(BridgeProbeArrayGl, AbandonLeavesTheSlotUntouched) {
    renderer::BridgeProbeArray a;
    ASSERT_TRUE(a.ensure(1));
    ASSERT_EQ(capture_all(a, 0, red), a.steps_per_probe());
    const int layer = a.layer_of(0);
    std::vector<std::vector<glm::vec3>> before;
    for (int m = 0; m < kBridgeProbeMips; ++m)
        before.push_back(read_array_face(a.texture(), layer, 0, m));

    int drawn = 0;
    a.begin(0);
    for (int i = 0; i < 9; ++i) ASSERT_FALSE(a.step(glm::vec3(0.0f), ClearFaces{blue, &drawn}));
    a.abandon();
    EXPECT_FALSE(a.in_flight());
    EXPECT_EQ(a.in_flight_slot(), -1);
    EXPECT_FALSE(a.step(glm::vec3(0.0f), ClearFaces{blue, &drawn}));
    EXPECT_EQ(drawn, 6);   // nothing drawn after the abandon
    EXPECT_EQ(a.layer_of(0), layer);
    EXPECT_TRUE(a.valid(0));
    for (int m = 0; m < kBridgeProbeMips; ++m)
        EXPECT_EQ(read_array_face(a.texture(), layer, 0, m), before[static_cast<size_t>(m)]) << m;

    // A fresh begin starts over from the first face.
    drawn = 0;
    EXPECT_EQ(capture_all(a, 0, blue), a.steps_per_probe());
    EXPECT_GT(centre(read_array_face(a.texture(), a.layer_of(0), 0, 0), 0).b, 0.9f);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

TEST_F(BridgeProbeArrayGl, StepRestoresTheCallersGlState) {
    renderer::HdrTarget t;
    t.resize(64, 48);
    // A FRESH array: its first ensure() runs with the caller's state live.
    renderer::BridgeProbeArray a;
    GLuint cube = 0, arr = 0, tex2d = 0, vao = 0;
    glGenTextures(1, &cube);
    glGenTextures(1, &arr);
    glGenTextures(1, &tex2d);
    glGenVertexArrays(1, &vao);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_CUBE_MAP, cube);
    glBindTexture(GL_TEXTURE_CUBE_MAP_ARRAY, arr);
    glBindTexture(GL_TEXTURE_2D, tex2d);
    glActiveTexture(GL_TEXTURE3);
    glBindTexture(GL_TEXTURE_CUBE_MAP, cube);
    glBindVertexArray(vao);
    glUseProgram(0);
    glClearColor(0.25f, 0.5f, 0.75f, 1.0f);
    glEnable(GL_DEPTH_TEST);
    glEnable(GL_BLEND);
    glEnable(GL_CULL_FACE);
    glEnable(GL_SCISSOR_TEST);
    glDepthMask(GL_FALSE);

    const auto check = [&](const char* when) {
        GLint fbo = 0, vp[4] = {}, prog = -1, va = 0, active = 0;
        GLint cube0 = 0, arr0 = 0, t2d0 = 0, cube3 = 0;
        GLboolean mask = GL_TRUE;
        glGetIntegerv(GL_FRAMEBUFFER_BINDING, &fbo);
        glGetIntegerv(GL_VIEWPORT, vp);
        glGetIntegerv(GL_CURRENT_PROGRAM, &prog);
        glGetIntegerv(GL_VERTEX_ARRAY_BINDING, &va);
        glGetIntegerv(GL_ACTIVE_TEXTURE, &active);
        glGetIntegerv(GL_TEXTURE_BINDING_CUBE_MAP, &cube3);
        glActiveTexture(GL_TEXTURE0);
        glGetIntegerv(GL_TEXTURE_BINDING_CUBE_MAP, &cube0);
        glGetIntegerv(GL_TEXTURE_BINDING_CUBE_MAP_ARRAY, &arr0);
        glGetIntegerv(GL_TEXTURE_BINDING_2D, &t2d0);
        glActiveTexture(GL_TEXTURE3);
        glGetBooleanv(GL_DEPTH_WRITEMASK, &mask);
        GLfloat cc[4] = {};
        glGetFloatv(GL_COLOR_CLEAR_VALUE, cc);
        EXPECT_EQ(static_cast<GLuint>(fbo), t.fbo()) << when;
        EXPECT_EQ(vp[2], 64) << when;
        EXPECT_EQ(vp[3], 48) << when;
        EXPECT_EQ(prog, 0) << when;
        EXPECT_EQ(static_cast<GLuint>(va), vao) << when;
        EXPECT_EQ(active, GL_TEXTURE3) << when;
        EXPECT_EQ(static_cast<GLuint>(cube3), cube) << when;
        EXPECT_EQ(static_cast<GLuint>(cube0), cube) << when;
        EXPECT_EQ(static_cast<GLuint>(arr0), arr) << when;
        EXPECT_EQ(static_cast<GLuint>(t2d0), tex2d) << when;
        EXPECT_FLOAT_EQ(cc[0], 0.25f) << when;
        EXPECT_FLOAT_EQ(cc[2], 0.75f) << when;
        EXPECT_TRUE(glIsEnabled(GL_DEPTH_TEST)) << when;
        EXPECT_TRUE(glIsEnabled(GL_BLEND)) << when;
        EXPECT_TRUE(glIsEnabled(GL_CULL_FACE)) << when;
        EXPECT_TRUE(glIsEnabled(GL_SCISSOR_TEST)) << when;
        EXPECT_EQ(mask, GL_FALSE) << when;
    };

    t.bind();
    glViewport(0, 0, 64, 48);
    ASSERT_TRUE(a.ensure(1));
    check("ensure");
    a.begin(0);
    for (int i = 0; i < a.steps_per_probe(); ++i) {
        a.step(glm::vec3(0.0f), [](const scenegraph::Camera&) {});
        check(i < 6 ? "face step" : "prefilter step");
    }
    EXPECT_TRUE(a.valid(0));
    ASSERT_TRUE(a.ensure(3));   // the grow (a blit) restores too
    check("grow");
    a.shrink_to(1);
    check("shrink");
    // A face draw that throws leaves the step to be retried, state restored.
    a.begin(0);
    EXPECT_THROW(a.step(glm::vec3(0.0f), [](const scenegraph::Camera&) {
        throw std::runtime_error("draw failed");
    }), std::runtime_error);
    check("throw");
    int drawn = 0;
    EXPECT_FALSE(a.step(glm::vec3(0.0f), ClearFaces{red, &drawn}));
    EXPECT_EQ(drawn, 1);   // the failed face, drawn again

    glDisable(GL_DEPTH_TEST);
    glDisable(GL_BLEND);
    glDisable(GL_CULL_FACE);
    glDisable(GL_SCISSOR_TEST);
    glDepthMask(GL_TRUE);
    glActiveTexture(GL_TEXTURE3);
    glBindTexture(GL_TEXTURE_CUBE_MAP, 0);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_CUBE_MAP, 0);
    glBindTexture(GL_TEXTURE_CUBE_MAP_ARRAY, 0);
    glBindTexture(GL_TEXTURE_2D, 0);
    glBindVertexArray(0);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glDeleteVertexArrays(1, &vao);
    GLuint texs[3] = {cube, arr, tex2d};
    glDeleteTextures(3, texs);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}
