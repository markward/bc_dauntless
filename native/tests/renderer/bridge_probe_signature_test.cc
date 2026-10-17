// native/tests/renderer/bridge_probe_signature_test.cc
//
// CPU-only (BridgePass constructs without GL; no render()): the per-probe
// signature is FNV-1a over exactly the inputs that probe reads (spec
// 2026-10-17-bridge-reflection-layers §4.5). Probe ids: base of state s = s,
// layer k = kBridgeStates + k.
#include <gtest/gtest.h>

#include <renderer/bridge_pass.h>

#include <array>
#include <cstdint>
#include <vector>

namespace {

using renderer::kBridgeStates;

renderer::BridgeSpot make_spot() {
    renderer::BridgeSpot sp;
    sp.position = {70.0f, 0.0f, 60.0f};
    sp.direction = {0.0f, 0.0f, -1.0f};
    sp.cos_inner = 0.9f;
    sp.cos_outer = 0.5f;
    sp.range = 200.0f;
    sp.has_capture = true;
    for (int s = 0; s < kBridgeStates; ++s) {
        sp.capture_radiance[s] = glm::vec3(1.0f + static_cast<float>(s));
        sp.layer[s] = -1;
    }
    return sp;
}

std::vector<std::uint64_t> sigs(const renderer::BridgePass& p) {
    std::vector<std::uint64_t> v;
    for (int i = 0; i < p.probe_count(); ++i) v.push_back(p.probe_signature(i));
    return v;
}

// Indices whose signature differs between two snapshots.
std::vector<int> moved(const std::vector<std::uint64_t>& a,
                       const std::vector<std::uint64_t>& b) {
    std::vector<int> out;
    for (std::size_t i = 0; i < a.size(); ++i)
        if (a[i] != b[i]) out.push_back(static_cast<int>(i));
    return out;
}

}  // namespace

TEST(BridgeProbeSignature, RedOnlyCaptureChangeMovesOnlyTheRedBase) {
    renderer::BridgePass p;
    auto sp = make_spot();
    p.set_spots({sp});
    const auto before = sigs(p);
    sp.capture_radiance[2] = glm::vec3(9.0f);
    p.set_spots({sp});
    EXPECT_EQ(moved(before, sigs(p)), std::vector<int>({2}));
}

TEST(BridgeProbeSignature, LayerMemberChangeMovesOnlyThatLayer) {
    renderer::BridgePass p;
    p.set_probe_layers({2, 2});
    ASSERT_EQ(p.probe_count(), kBridgeStates + 2);
    auto sp = make_spot();
    sp.layer[2] = 1;
    sp.layer_radiance[2] = glm::vec3(0.5f);
    p.set_spots({sp});
    const auto before = sigs(p);
    sp.layer_radiance[2] = glm::vec3(0.75f);
    p.set_spots({sp});
    EXPECT_EQ(moved(before, sigs(p)), std::vector<int>({6}));
}

TEST(BridgeProbeSignature, OverridesMoveEveryProbe) {
    renderer::BridgePass p;
    p.set_probe_layers({0, 3});
    p.set_material_overrides(7, {{0, 0.5f, 0.1f}});
    const auto before = sigs(p);
    p.set_material_overrides(7, {{0, 0.5f, 0.9f}});
    EXPECT_EQ(moved(before, sigs(p)).size(), static_cast<std::size_t>(p.probe_count()));
}

TEST(BridgeProbeSignature, IdenticalRepushMovesNothing) {
    renderer::BridgePass p;
    p.set_probe_layers({1});
    auto sp = make_spot();
    sp.layer[1] = 0;
    sp.layer_radiance[1] = glm::vec3(2.0f);
    p.set_spots({sp});
    renderer::BridgeAreaLight al;
    al.has_capture = true;
    p.set_area_lights({al});
    const auto before = sigs(p);
    p.set_spots({sp});
    p.set_area_lights({al});
    EXPECT_TRUE(moved(before, sigs(p)).empty());
}

TEST(BridgeProbeSignature, ScaleMovesOnlyItsBase) {
    renderer::BridgePass p;
    p.set_probe_layers({3});
    std::array<float, kBridgeStates> scales{1, 1, 1, 1, 1};
    p.set_probe_scales(scales);
    const auto before = sigs(p);
    scales[3] = 2.0f;
    p.set_probe_scales(scales);
    EXPECT_EQ(moved(before, sigs(p)), std::vector<int>({3}));
    EXPECT_EQ(p.probe_scale(3), 2.0f);
}

TEST(BridgeProbeSignature, LiveRadianceNeverMovesASignature) {
    renderer::BridgePass p;
    p.set_probe_layers({0});
    p.set_spots({make_spot()});
    renderer::BridgeAreaLight al;
    al.has_capture = true;
    p.set_area_lights({al});
    p.set_glow_captures(5, {renderer::BridgeGlowCapture{}});
    const auto before = sigs(p);
    p.set_spot_radiance({glm::vec3(5000.0f)});
    p.set_area_radiance({glm::vec3(5000.0f)});
    p.set_glow(5, {{0, 2, {1.0f, 1.0f, 1.0f}, 1.0f}});
    EXPECT_TRUE(moved(before, sigs(p)).empty());
}

TEST(BridgeProbeSignature, GlowCaptureBaseMovesItsState) {
    renderer::BridgePass p;
    renderer::BridgeGlowCapture g;
    g.mesh = 3;
    p.set_glow_captures(5, {g});
    const auto before = sigs(p);
    g.base[0] = glm::vec3(0.4f);
    p.set_glow_captures(5, {g});
    EXPECT_EQ(moved(before, sigs(p)), std::vector<int>({0}));
}
