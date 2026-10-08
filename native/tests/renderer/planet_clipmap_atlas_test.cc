// native/tests/renderer/planet_clipmap_atlas_test.cc
//
// Planet surface-detail clipmap atlas (Task 6): planet_bake.frag is the GLSL
// twin of planet_detail_noise.cc, so a baked texel must equal the CPU field
// at the same absolute texel, within fp16 + GPU-transcendental tolerance.
#include <gtest/gtest.h>

#include <renderer/planet_clipmap_atlas.h>
#include <renderer/planet_clipmap_schedule.h>
#include <renderer/planet_detail_noise.h>
#include <renderer/window.h>

#include <glad/glad.h>

#include <climits>
#include <cmath>
#include <memory>
#include <random>
#include <stdexcept>
#include <vector>

namespace {

using namespace renderer::planet_detail;

constexpr float kTs0 = 0.1f;
constexpr float kR = 3600.0f;
const glm::vec2 kNadir(3.0f, -2.0f);

int mod1024(int a) {
    int m = a % kLevelSize;
    return m < 0 ? m + kLevelSize : m;
}

class PlanetClipmapAtlasTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;

    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(64, 64, "planet-clipmap-atlas-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
    }

    static BakeParams params_for(SurfaceType t) {
        BakeParams bp;
        bp.anchor = make_anchor(glm::normalize(glm::vec3(0.3f, 0.5f, 0.8f)), kR);
        bp.type = t;
        bp.params = default_params(t);
        bp.scale = 1.0f;
        bp.seed = 7u;
        bp.ts0_gu = kTs0;
        for (int L = 0; L < 2; ++L) {
            bp.octaves_per_level.push_back(
                octaves_for_texel(bp.params, bp.scale, kTs0 * float(1 << L)));
        }
        return bp;
    }

    // Cold-fill a 2-level schedule at the nadir with an unlimited budget.
    static ClipmapSchedule cold_fill(std::vector<BakeRect>& rects) {
        ClipmapSchedule s(kTs0, {9, 8});
        s.update(kNadir, LLONG_MAX, rects);
        return s;
    }

    static std::vector<float> read_back(const ClipmapAtlas& atlas) {
        std::vector<float> px(std::size_t(kLevelSize) * kBandRows * atlas.levels() * 4);
        GLint prev = 0;
        glGetIntegerv(GL_TEXTURE_BINDING_2D, &prev);
        glBindTexture(GL_TEXTURE_2D, atlas.texture());
        glGetTexImage(GL_TEXTURE_2D, 0, GL_RGBA, GL_FLOAT, px.data());
        glBindTexture(GL_TEXTURE_2D, GLuint(prev));
        return px;
    }

    static const float* texel(const std::vector<float>& px, int x, int row) {
        return &px[(std::size_t(row) * kLevelSize + x) * 4];
    }

    void expect_matches_cpu(SurfaceType t, void (*tweak)(TypeParams&) = nullptr) {
        ClipmapAtlas atlas(2);
        std::vector<BakeRect> rects;
        ClipmapSchedule sched = cold_fill(rects);
        ASSERT_TRUE(sched.complete(kNadir));
        BakeParams bp = params_for(t);
        if (tweak) tweak(bp.params);
        atlas.bake(rects, bp);
        ASSERT_EQ(glGetError(), GLenum(GL_NO_ERROR));
        std::vector<float> px = read_back(atlas);

        std::mt19937 rng(1234u);
        for (int L = 0; L < 2; ++L) {
            const Rect& v = sched.valid(L);
            std::uniform_int_distribution<int> dx(v.x0, v.x1 - 1), dy(v.y0, v.y1 - 1);
            const float ts = kTs0 * float(1 << L);
            const int oct = octaves_for_texel(bp.params, bp.scale, ts);
            for (int i = 0; i < 64; ++i) {
                const int ax = dx(rng), ay = dy(rng);
                glm::vec2 pl((float(ax) + 0.5f) * ts, (float(ay) + 0.5f) * ts);
                glm::vec3 p = from_plane(bp.anchor, pl);
                FieldSample s = field(t, bp.params, p, bp.seed, bp.scale, oct);
                const float expected[4] = {s.h, glm::dot(s.grad, bp.anchor.E),
                                           glm::dot(s.grad, bp.anchor.N), s.a};
                const float* got = texel(px, mod1024(ax), L * kBandRows + mod1024(ay) + 1);
                for (int c = 0; c < 4; ++c) {
                    ASSERT_TRUE(std::isfinite(got[c])) << "type " << int(t) << " channel " << c;
                    EXPECT_NEAR(got[c], expected[c], 2e-2f + 2e-2f * std::fabs(expected[c]))
                        << "type " << int(t) << " level " << L << " abs (" << ax << ", " << ay
                        << ") channel " << c;
                }
            }
        }
    }
};

TEST_F(PlanetClipmapAtlasTest, AtlasHasStackedLevelBands) {
    ClipmapAtlas atlas(2);
    EXPECT_EQ(atlas.levels(), 2);
    ASSERT_NE(atlas.texture(), 0u);
    GLint prev = 0, wpx = 0, hpx = 0, fmt = 0;
    glGetIntegerv(GL_TEXTURE_BINDING_2D, &prev);
    glBindTexture(GL_TEXTURE_2D, atlas.texture());
    glGetTexLevelParameteriv(GL_TEXTURE_2D, 0, GL_TEXTURE_WIDTH, &wpx);
    glGetTexLevelParameteriv(GL_TEXTURE_2D, 0, GL_TEXTURE_HEIGHT, &hpx);
    glGetTexLevelParameteriv(GL_TEXTURE_2D, 0, GL_TEXTURE_INTERNAL_FORMAT, &fmt);
    GLint minf = 0, magf = 0, ws = 0, wt = 0;
    glGetTexParameteriv(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, &minf);
    glGetTexParameteriv(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, &magf);
    glGetTexParameteriv(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, &ws);
    glGetTexParameteriv(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, &wt);
    glBindTexture(GL_TEXTURE_2D, GLuint(prev));
    EXPECT_EQ(minf, GL_LINEAR);
    EXPECT_EQ(magf, GL_LINEAR);
    EXPECT_EQ(ws, GL_REPEAT);
    EXPECT_EQ(wt, GL_CLAMP_TO_EDGE);
    EXPECT_EQ(wpx, kLevelSize);
    EXPECT_EQ(hpx, kBandRows * 2);
    EXPECT_EQ(fmt, GL_RGBA16F);
}

TEST_F(PlanetClipmapAtlasTest, RockyBakeMatchesCpuField) { expect_matches_cpu(SurfaceType::Rocky); }
TEST_F(PlanetClipmapAtlasTest, DesertBakeMatchesCpuField) { expect_matches_cpu(SurfaceType::Desert); }
TEST_F(PlanetClipmapAtlasTest, IceBakeMatchesCpuField) { expect_matches_cpu(SurfaceType::Ice); }
TEST_F(PlanetClipmapAtlasTest, GasBakeMatchesCpuField) { expect_matches_cpu(SurfaceType::Gas); }
TEST_F(PlanetClipmapAtlasTest, OceanBakeMatchesCpuField) { expect_matches_cpu(SurfaceType::Ocean); }

// R4 guards, GLSL side: degenerate dials must bake finite texels that still
// agree with the guarded CPU twin.
// (A negative width discriminates on the GPU: unguarded, every texel's crack
// mask saturates to a = 1; guarded, a ~ 0 like the CPU. Zero only diverges at
// an exact c == 0, which sampled texels never hit; the CPU test covers that.)
TEST_F(PlanetClipmapAtlasTest, IceNegativeCrackWidthBakeMatchesCpuField) {
    expect_matches_cpu(SurfaceType::Ice, [](TypeParams& p) { p.crack_width = -0.5f; });
}
TEST_F(PlanetClipmapAtlasTest, MaxOctavesZeroBakeMatchesCpuField) {
    expect_matches_cpu(SurfaceType::Rocky, [](TypeParams& p) { p.max_octaves = 0; });
}

TEST_F(PlanetClipmapAtlasTest, GuardRowsMirrorTheOppositeContentRow) {
    ClipmapAtlas atlas(2);
    std::vector<BakeRect> rects;
    cold_fill(rects);
    atlas.bake(rects, params_for(SurfaceType::Rocky));
    std::vector<float> px = read_back(atlas);
    for (int L = 0; L < 2; ++L) {
        const int base = L * kBandRows;
        int mismatches = 0, nonzero = 0;
        for (int x = 0; x < kLevelSize; ++x) {
            for (int c = 0; c < 4; ++c) {
                if (texel(px, x, base + 0)[c] != 0.0f) ++nonzero;
                if (texel(px, x, base + 1025)[c] != 0.0f) ++nonzero;
                if (texel(px, x, base + 0)[c] != texel(px, x, base + 1024)[c]) ++mismatches;
                if (texel(px, x, base + 1025)[c] != texel(px, x, base + 1)[c]) ++mismatches;
            }
        }
        EXPECT_EQ(mismatches, 0) << "level " << L;
        EXPECT_GT(nonzero, kLevelSize) << "level " << L << ": guard rows were never baked";
    }
}

TEST_F(PlanetClipmapAtlasTest, BakeRestoresGlState) {
    ClipmapAtlas atlas(1);
    std::vector<BakeRect> rects{BakeRect{0, 0, 0, 0, 1, 16, 16}};

    GLuint fbo = 0, tex = 0;
    glGenTextures(1, &tex);
    glBindTexture(GL_TEXTURE_2D, tex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, 8, 8, 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
    glGenFramebuffers(1, &fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, tex, 0);
    glViewport(1, 2, 3, 4);
    glDisable(GL_SCISSOR_TEST);
    glScissor(5, 6, 7, 8);
    glUseProgram(0);

    GLint fb0 = 0, prog0 = 0, vp0[4] = {}, sc0[4] = {};
    glGetIntegerv(GL_FRAMEBUFFER_BINDING, &fb0);
    glGetIntegerv(GL_CURRENT_PROGRAM, &prog0);
    glGetIntegerv(GL_VIEWPORT, vp0);
    glGetIntegerv(GL_SCISSOR_BOX, sc0);

    atlas.bake(rects, params_for(SurfaceType::Rocky));

    GLint fb1 = 0, prog1 = 0, vp1[4] = {}, sc1[4] = {};
    glGetIntegerv(GL_FRAMEBUFFER_BINDING, &fb1);
    glGetIntegerv(GL_CURRENT_PROGRAM, &prog1);
    glGetIntegerv(GL_VIEWPORT, vp1);
    glGetIntegerv(GL_SCISSOR_BOX, sc1);
    EXPECT_EQ(fb1, fb0);
    EXPECT_EQ(prog1, prog0);
    for (int i = 0; i < 4; ++i) {
        EXPECT_EQ(vp1[i], vp0[i]) << i;
        EXPECT_EQ(sc1[i], sc0[i]) << i;
    }
    EXPECT_FALSE(glIsEnabled(GL_SCISSOR_TEST));

    // And the enabled case.
    glEnable(GL_SCISSOR_TEST);
    atlas.bake(rects, params_for(SurfaceType::Rocky));
    EXPECT_TRUE(glIsEnabled(GL_SCISSOR_TEST));

    glDisable(GL_SCISSOR_TEST);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glDeleteFramebuffers(1, &fbo);
    glDeleteTextures(1, &tex);
}

}  // namespace
