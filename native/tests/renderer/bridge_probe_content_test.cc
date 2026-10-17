// native/tests/renderer/bridge_probe_content_test.cc
//
// What each bridge reflection probe holds (spec
// 2026-10-17-bridge-reflection-layers §4.1), read back from the probe array
// through BridgePass's capture_probe_now / read_probe test seams. A base probe
// (id = state s) is the room in s with every animation at zero: ambient x
// probe_scale(s), lights at capture_radiance[s], glow-capture shapes at
// base[s], other shapes' texture-level _emissive default for s (dark at
// offline). A layer probe (id = kBridgeStates + k) holds ONLY layer k's
// members at the wave's peak: ambient 0, member lights at layer_radiance[s],
// member glow at layer_rgb[s], no texture-level default. Every probe caps its
// lit diffuse at its own ceiling and adds decode(glow) uncapped on top.
//
// The room: bridge_test_room's corner (floor z = 0, wall x = 0) seen from a
// probe at (60, 0, 40). Face 1 (-X) is centred on the wall at (0, 0, 40);
// face 5 (-Z) on the floor at (60, 0, 0). GL tests: they need a context and
// SKIP without one -- a skip is not a pass.
#include <gtest/gtest.h>
#include <glad/glad.h>

#include "bridge_test_room.h"

#include <renderer/bridge_lighting_tuning.h>
#include <renderer/bridge_pass.h>
#include <renderer/frame.h>
#include <renderer/pipeline.h>
#include <renderer/window.h>
#include <scenegraph/instance.h>
#include <scenegraph/world.h>

#include <assets/material.h>
#include <assets/model.h>

#include <glm/glm.hpp>

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <memory>
#include <stdexcept>
#include <vector>

namespace {

using bridge_test_room::lookup_fn;
using bridge_test_room::make_two_mesh_corner;
using bridge_test_room::solid_1x1;
using renderer::kBridgeProbeFace;
using renderer::kBridgeStates;

constexpr int kFaceMinusX = 1;   // looks at the wall
constexpr int kFaceMinusZ = 5;   // looks at the floor
constexpr int kWallMesh = 1;
constexpr int kRed = 2;
constexpr int kLayer0 = kBridgeStates;   // probe id of layer 0

int mip_size(int mip) { return std::max(1, kBridgeProbeFace >> mip); }

/// The texel at the centre of `face` in a read_probe result.
glm::vec3 centre(const std::vector<glm::vec3>& probe, int face, int mip) {
    const int n = mip_size(mip);
    return probe[static_cast<std::size_t>(face) * n * n
                 + static_cast<std::size_t>(n / 2) * n + n / 2];
}

float max_channel(const std::vector<glm::vec3>& probe) {
    float m = 0.0f;
    for (const auto& t : probe) m = std::max(m, std::max(t.r, std::max(t.g, t.b)));
    return m;
}

/// A spot 30 above the floor pointing straight down, lighting a disc round
/// (x, y, 0). `capture` = its base capture colour in red; `layer` /
/// `at_peak` its red layer membership.
renderer::BridgeSpot down_spot(float x, float y, glm::vec3 capture, int layer,
                               glm::vec3 at_peak) {
    renderer::BridgeSpot sp;
    sp.position = {x, y, 30.0f};
    sp.direction = {0.0f, 0.0f, -1.0f};
    sp.cos_inner = std::cos(glm::radians(30.0f));
    sp.cos_outer = std::cos(glm::radians(40.0f));
    sp.range = 200.0f;
    sp.has_capture = true;
    sp.capture_radiance[kRed] = capture;
    sp.layer[kRed] = layer;
    sp.layer_radiance[kRed] = at_peak;
    return sp;
}

/// A flat glow on the wall: `base_red` in red's base, `layer_red` /
/// `at_peak` its red layer membership.
renderer::BridgeGlowCapture wall_glow(glm::vec3 base_red, int layer_red, glm::vec3 at_peak) {
    renderer::BridgeGlowCapture g;
    g.mesh = kWallMesh;
    g.src = 2;
    g.base[kRed] = base_red;
    g.layer[kRed] = layer_red;
    g.layer_rgb[kRed] = at_peak;
    return g;
}

class BridgeProbeContent : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    std::unique_ptr<renderer::Pipeline> p;
    std::unique_ptr<renderer::BridgePass> pass;
    std::unique_ptr<assets::Model> model;
    renderer::Lighting lighting;

    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(64, 64, "bridge-probe-content-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        p = std::make_unique<renderer::Pipeline>();
        pass = std::make_unique<renderer::BridgePass>();
        pass->set_ao_enabled(false);
        pass->set_probe_origin({60.0f, 0.0f, 40.0f});
        pass->set_probe_scales({1.0f, 1.0f, 1.0f, 1.0f, 1.0f});
        model = make_two_mesh_corner({0.6f, 0.6f, 0.6f}, {0.6f, 0.6f, 0.6f});
        lighting.ambient = glm::vec3(0.3f);
        while (glGetError() != GL_NO_ERROR) {}
    }

    unsigned long long handle() const {
        return reinterpret_cast<unsigned long long>(model.get());
    }

    /// Capture probe `probe` in one go and read all six faces at `mip`.
    std::vector<glm::vec3> capture(int probe, int mip = 0) {
        scenegraph::World world;
        auto iid = world.create_instance(
            reinterpret_cast<scenegraph::ModelHandle>(model.get()));
        world.set_world_transform(iid, glm::mat4(1.0f));
        world.set_pass(iid, scenegraph::Pass::Bridge);
        pass->capture_probe_now(probe, world, *p, lookup_fn, lighting);
        EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
        std::vector<glm::vec3> rgb;
        EXPECT_TRUE(pass->read_probe(probe, mip, rgb)) << "probe " << probe;
        EXPECT_EQ(rgb.size(), static_cast<std::size_t>(6) * mip_size(mip) * mip_size(mip));
        return rgb;
    }

    /// The wall's material gets a solid-colour _emissive map.
    void give_wall_emissive(glm::vec4 rgba) {
        model->textures.push_back(solid_1x1(rgba));
        model->materials[kWallMesh].stages[static_cast<std::size_t>(
            assets::Material::StageSlot::Emissive)].texture_index =
            static_cast<int>(model->textures.size()) - 1;
    }
};

/// Per texel, within RGB11 (R11F_G11F_B10F: 5-6 mantissa bits, three
/// roundings) tolerance.
void expect_same(const std::vector<glm::vec3>& a, const std::vector<glm::vec3>& b,
                 const char* what) {
    ASSERT_EQ(a.size(), b.size());
    int bad = 0;
    for (std::size_t i = 0; i < a.size(); ++i)
        for (int c = 0; c < 3; ++c) {
            const float tol = 0.05f * std::max(a[i][c], b[i][c]) + 1e-3f;
            if (std::abs(a[i][c] - b[i][c]) > tol && bad++ < 5)
                ADD_FAILURE() << what << ": texel " << i << " channel " << c << ": "
                              << a[i][c] << " vs " << b[i][c];
        }
    EXPECT_EQ(bad, 0) << what;
}

}  // namespace

// A flat glow seen by a face lands decoded (2^2.2) and UNCAPPED: far above
// the diffuse ceiling, so a reflected bar can bloom like the bar.
TEST_F(BridgeProbeContent, GlowShowsInTheBase) {
    lighting.ambient = glm::vec3(0.0f);   // the texel is the glow alone
    renderer::BridgeGlowCapture g;
    g.mesh = kWallMesh;
    g.src = 2;
    g.base[0] = glm::vec3(2.0f);
    pass->set_glow_captures(handle(), {g});
    const glm::vec3 c = centre(capture(0), kFaceMinusX, 0);
    const float want = std::pow(2.0f, 2.2f);
    EXPECT_NEAR(c.r, want, 0.03f * want);
    EXPECT_NEAR(c.g, want, 0.03f * want);
    EXPECT_NEAR(c.b, want, 0.03f * want);
    EXPECT_GT(c.r, 1.0f);
}

// A shape with an _emissive map and no glow capture shows the texture-level
// default in its base -- except offline, where the view draws it dark too.
TEST_F(BridgeProbeContent, OfflineBaseDarkensTheTextureDefault) {
    lighting.ambient = glm::vec3(0.0f);
    give_wall_emissive({0.0f, 0.8f, 0.0f, 1.0f});
    const glm::vec3 green = centre(capture(0), kFaceMinusX, 0);
    EXPECT_NEAR(green.g, std::pow(0.8f, 2.2f), 0.03f);
    EXPECT_LT(green.r, 1e-3f);
    const glm::vec3 offline = centre(capture(renderer::kBridgeStateOffline), kFaceMinusX, 0);
    EXPECT_LT(offline.g, 1e-3f);
}

// A light that animates in red is 0 in red's base: the base matches the same
// room with no spot at all (and the spot really does light the floor when it
// is steady, so the comparison is not vacuous).
TEST_F(BridgeProbeContent, AnimatedMemberIsAbsentFromItsBase) {
    pass->set_probe_layers({kRed});
    pass->set_spots({});
    const std::vector<glm::vec3> no_spot = capture(kRed);
    pass->set_spots({down_spot(60.0f, 0.0f, glm::vec3(0.0f), 0, glm::vec3(1300.0f))});
    expect_same(capture(kRed), no_spot, "animated member in its base");
    pass->set_spots({down_spot(60.0f, 0.0f, glm::vec3(1300.0f), -1, glm::vec3(0.0f))});
    EXPECT_GT(centre(capture(kRed), kFaceMinusZ, 0).r,
              centre(no_spot, kFaceMinusZ, 0).r + 0.05f);
}

// A layer is lit ONLY by its members: no ambient, no non-member light -- a
// layer with only a non-member (and a bright ambient) is black; adding the
// member lights it, and the non-member still adds nothing.
TEST_F(BridgeProbeContent, LayerHoldsOnlyItsMembers) {
    lighting.ambient = glm::vec3(0.8f);
    pass->set_probe_layers({kRed});
    const auto other = down_spot(60.0f, 60.0f, glm::vec3(1300.0f), -1, glm::vec3(0.0f));
    const auto member = down_spot(60.0f, -60.0f, glm::vec3(0.0f), 0, glm::vec3(1300.0f));
    pass->set_spots({other});
    EXPECT_LT(max_channel(capture(kLayer0)), 1e-3f);
    pass->set_spots({member});
    const std::vector<glm::vec3> member_only = capture(kLayer0);
    EXPECT_GT(max_channel(member_only), 0.05f);
    pass->set_spots({other, member});
    expect_same(capture(kLayer0), member_only, "non-member in the layer");
}

// A layer holds no glow but its members' (spec §4.1): neither the texture-
// level _emissive default (the floor's map) nor a non-member glow shape (the
// wall: steady in red's base, and a member of red's OTHER layer) -- else
// every default glow would count once in the base and again in each
// weighted layer. The other layer holds the wall; once the wall is layer
// 0's member, layer 0 holds it too. The floor's default still shows in red's
// base, so the map is really there.
//
// Mutations checked once (2026-10-17), each FAILS this test: the shader's
// `u_capture_layer < 0 &&` dropped (the default enters a layer); a
// non-member drawn as in a base (src + base[s]); a non-member drawn at its
// layer_rgb (the membership check dropped).
TEST_F(BridgeProbeContent, LayerExcludesTextureDefaultAndNonMemberGlow) {
    lighting.ambient = glm::vec3(0.8f);
    pass->set_probe_layers({kRed, kRed});           // probes 5 (layer 0) and 6 (layer 1)
    model->textures.push_back(solid_1x1({0.0f, 0.8f, 0.0f, 1.0f}));
    model->materials[0].stages[static_cast<std::size_t>(
        assets::Material::StageSlot::Emissive)].texture_index =
        static_cast<int>(model->textures.size()) - 1;   // the floor's default glow
    const glm::vec3 g(1.5f, 1.0f, 0.5f);
    renderer::BridgeGlowCapture other = wall_glow(g, /*layer_red=*/1, g);
    pass->set_glow_captures(handle(), {other});
    EXPECT_GT(centre(capture(kRed), kFaceMinusZ, 0).g, 0.5f) << "floor default in the base";
    const std::vector<glm::vec3> layer0 = capture(kLayer0);
    EXPECT_LT(max_channel(layer0), 1e-3f);
    EXPECT_LT(centre(layer0, kFaceMinusZ, 0).g, 1e-3f) << "floor default";
    EXPECT_LT(centre(layer0, kFaceMinusX, 0).r, 1e-3f) << "non-member wall glow";
    EXPECT_GT(centre(capture(kLayer0 + 1), kFaceMinusX, 0).r, 1.0f) << "its own layer";
    pass->set_glow_captures(handle(), {wall_glow(glm::vec3(0.0f), 0, g)});
    const std::vector<glm::vec3> member = capture(kLayer0);
    EXPECT_NEAR(centre(member, kFaceMinusX, 0).r, std::pow(1.5f, 2.2f), 0.06f);
    EXPECT_LT(centre(member, kFaceMinusZ, 0).g, 1e-3f) << "floor default";
}

// THE LINEARITY FALSIFIER (spec §6). Below the diffuse knee, the room with a
// member's wave forced to w = 0.6 (probe A: its contribution folded into the
// base) equals base + layer x 0.6^2.2 (probes B and C: the member at 0 in the
// base, at its peak in the layer) -- per texel, for a light member and a
// glow member. A light's at-peak radiance is linear, so its base value is
// L x 0.6^2.2; a glow's is DISPLAY space, so its base value is g x 0.6 and
// the capture's decode supplies the ^2.2.
//
// Mutation check (done once, 2026-10-17): with the capture's decode of the
// glow removed (glow added in display space), the glow case FAILS.
TEST_F(BridgeProbeContent, BasePlusWeightedLayerEqualsTheFullCapture) {
    const float w = 0.6f;
    const float w22 = std::pow(w, 2.2f);
    pass->set_probe_layers({kRed});
    for (int mip : {0, 2}) {
        SCOPED_TRACE(mip);
        // Light member.
        const glm::vec3 L(1300.0f, 900.0f, 600.0f);
        pass->set_glow_captures(0, {});
        pass->set_spots({down_spot(60.0f, 0.0f, L * w22, -1, glm::vec3(0.0f))});
        const std::vector<glm::vec3> a = capture(kRed, mip);
        ASSERT_LT(max_channel(a), 0.3f) << "room must stay below the diffuse knee";
        pass->set_spots({down_spot(60.0f, 0.0f, glm::vec3(0.0f), 0, L)});
        const std::vector<glm::vec3> b = capture(kRed, mip);
        const std::vector<glm::vec3> c = capture(kLayer0, mip);
        ASSERT_GT(max_channel(c), 0.05f) << "the layer must hold the light";
        std::vector<glm::vec3> sum(b.size());
        for (std::size_t i = 0; i < b.size(); ++i) sum[i] = b[i] + w22 * c[i];
        expect_same(a, sum, "light member");

        // Glow member (flat, on the wall).
        const glm::vec3 g(1.5f, 1.0f, 0.5f);
        pass->set_spots({});
        pass->set_glow_captures(handle(), {wall_glow(g * w, -1, glm::vec3(0.0f))});
        const std::vector<glm::vec3> ga = capture(kRed, mip);
        pass->set_glow_captures(handle(), {wall_glow(glm::vec3(0.0f), 0, g)});
        const std::vector<glm::vec3> gb = capture(kRed, mip);
        const std::vector<glm::vec3> gc = capture(kLayer0, mip);
        ASSERT_GT(max_channel(gc), 1.0f) << "the layer must hold the glow, uncapped";
        std::vector<glm::vec3> gsum(gb.size());
        for (std::size_t i = 0; i < gb.size(); ++i) gsum[i] = gb[i] + w22 * gc[i];
        expect_same(ga, gsum, "glow member");
    }
}

// capture_probe_now / read_probe are test seams: an out-of-range probe
// captures nothing, and an uncaptured probe reads back nothing.
TEST_F(BridgeProbeContent, OutOfRangeProbesCaptureAndReadNothing) {
    std::vector<glm::vec3> rgb;
    EXPECT_FALSE(pass->read_probe(0, 0, rgb));
    scenegraph::World world;
    pass->capture_probe_now(kLayer0, world, *p, lookup_fn, lighting);   // no layers
    EXPECT_FALSE(pass->read_probe(kLayer0, 0, rgb));
    EXPECT_FALSE(pass->read_probe(-1, 0, rgb));
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}
