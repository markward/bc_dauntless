// native/tests/renderer/bridge_probe_schedule_test.cc
//
// CPU-only: the bridge reflection capture queue's order (spec
// 2026-10-17-bridge-reflection-layers §4.7). The shown state's base first,
// then that state's layers, then the other bases, then the other layers --
// one probe at a time, index order within each group. Probe ids: base of
// state s = s, layer k = kBridgeStates + k.
#include <gtest/gtest.h>

#include <renderer/bridge_probe_schedule.h>

#include <cmath>
#include <set>
#include <vector>

TEST(BridgeProbeSchedule, ShownBaseFirstThenItsLayersThenOthers) {
    // Layer 0 = probe 5 at green, layer 1 = probe 6 at red; red is shown.
    const std::vector<int> layer_states = {0, 2};
    std::set<int> done;
    auto needs = [&](int p) { return done.count(p) == 0; };
    std::vector<int> order;
    for (int i = 0; i < 20; ++i) {
        const int p = renderer::next_probe(2, layer_states, needs);
        if (p < 0) break;
        order.push_back(p);
        done.insert(p);
    }
    EXPECT_EQ(order, (std::vector<int>{2, 6, 0, 1, 3, 4, 5}));
}

TEST(BridgeProbeSchedule, NothingNeededReturnsMinusOne) {
    EXPECT_EQ(renderer::next_probe(0, {0, 1, 4}, [](int) { return false; }), -1);
    EXPECT_EQ(renderer::next_probe(3, {}, [](int) { return false; }), -1);
}

// Only what is needed is returned: a settled shown state hands the queue to
// the others without re-picking anything valid.
TEST(BridgeProbeSchedule, ReturnsOnlyNeededProbes) {
    EXPECT_EQ(renderer::next_probe(1, {1}, [](int p) { return p == 4; }), 4);
    EXPECT_EQ(renderer::next_probe(1, {1, 3}, [](int p) { return p == 6; }), 6);
}

// An out-of-range shown state (the alert level is clamped by the caller, but
// the queue must not trust it) still drains every needed probe.
TEST(BridgeProbeSchedule, OutOfRangeShownStateStillDrainsTheQueue) {
    EXPECT_EQ(renderer::next_probe(-1, {2}, [](int p) { return p == 0; }), 0);
    EXPECT_EQ(renderer::next_probe(9, {2}, [](int p) { return p == 5; }), 5);
}

// ── Base fade (spec §4.2): the state cross-fade lives in C++ ───────────────
//
// ProbeFade moves the shown state's base toward 1 and the others toward 0 at
// 1 / 0.5 s, only once the shown base is valid, keeping the weights summing
// to 1. With nothing showing, the first valid target snaps to 1.

namespace {
constexpr float kDt = 1.0f / 60.0f;
auto all_valid = [](int) { return true; };

float weight_sum(const renderer::ProbeFade& f) {
    float s = 0.0f;
    for (float w : f.w) s += w;
    return s;
}
}  // namespace

TEST(BridgeProbeFade, FadeSettlesOnTheTarget) {
    renderer::ProbeFade f;
    f.w[0] = 1.0f;                                   // green settled
    for (int i = 0; i < 15; ++i) f.update(2, kDt, all_valid);   // 0.25 s
    EXPECT_NEAR(f.w[2], 0.5f, 1e-4f);
    EXPECT_NEAR(f.w[0], 0.5f, 1e-4f);
    for (int i = 0; i < 30; ++i) f.update(2, kDt, all_valid);   // past 0.5 s
    for (int s = 0; s < renderer::kBridgeStates; ++s)
        EXPECT_EQ(f.w[s], s == 2 ? 1.0f : 0.0f) << s;
}

TEST(BridgeProbeFade, FirstValidTargetSnaps) {
    renderer::ProbeFade f;                           // nothing showing
    f.update(1, kDt, all_valid);
    for (int s = 0; s < renderer::kBridgeStates; ++s)
        EXPECT_EQ(f.w[s], s == 1 ? 1.0f : 0.0f) << s;
    renderer::ProbeFade g;
    g.update(3, 0.0f, all_valid);                    // even paused
    EXPECT_EQ(g.w[3], 1.0f);
}

TEST(BridgeProbeFade, InvalidTargetHoldsTheCurrentWeights) {
    renderer::ProbeFade f;
    f.w[0] = 0.25f;
    f.w[1] = 0.75f;
    auto not_red = [](int p) { return p != 2; };
    for (int i = 0; i < 60; ++i) f.update(2, kDt, not_red);
    EXPECT_EQ(f.w[0], 0.25f);
    EXPECT_EQ(f.w[1], 0.75f);
    EXPECT_EQ(f.w[2], 0.0f);
    renderer::ProbeFade none;                        // nothing showing, nothing landed
    none.update(2, kDt, not_red);
    EXPECT_EQ(weight_sum(none), 0.0f);
}

// green -> red, then yellow 0.3 s into the fade: no pop -- every step moves
// each weight by at most dt / 0.5, and the weights always sum to 1.
TEST(BridgeProbeFade, RetargetMidFadeIsContinuous) {
    renderer::ProbeFade f;
    f.w[0] = 1.0f;
    auto step = [&](int target) {
        const renderer::ProbeFade before = f;
        f.update(target, kDt, all_valid);
        for (int s = 0; s < renderer::kBridgeStates; ++s)
            EXPECT_LE(std::fabs(f.w[s] - before.w[s]), kDt / 0.5f + 1e-6f) << s;
        EXPECT_NEAR(weight_sum(f), 1.0f, 1e-5f);
    };
    for (int i = 0; i < 18; ++i) step(2);            // 0.3 s
    EXPECT_GT(f.w[0], 0.0f);
    EXPECT_GT(f.w[2], 0.0f);
    step(1);
    EXPECT_GT(f.w[0], 0.0f);                         // three bases weigh in
    EXPECT_GT(f.w[1], 0.0f);
    EXPECT_GT(f.w[2], 0.0f);
    for (int i = 0; i < 60; ++i) step(1);
    EXPECT_EQ(f.w[1], 1.0f);
    EXPECT_EQ(f.w[0], 0.0f);
    EXPECT_EQ(f.w[2], 0.0f);
}

TEST(BridgeProbeFade, FadeFreezesAtZeroDt) {
    renderer::ProbeFade f;
    f.w[0] = 0.5f;
    f.w[2] = 0.5f;
    for (float dt : {0.0f, -0.1f, std::nanf("")}) {
        f.update(2, dt, all_valid);
        f.update(1, dt, all_valid);                  // a retarget while paused
        EXPECT_EQ(f.w[0], 0.5f) << dt;
        EXPECT_EQ(f.w[1], 0.0f) << dt;
        EXPECT_EQ(f.w[2], 0.5f) << dt;
    }
}

// ── The sampled entries (spec §4.2): bases + layers, one weighted list ─────

TEST(BridgeProbeEntries, BasesAndLayersWeightedByTheirStatesBase) {
    const float w[renderer::kBridgeStates] = {0.25f, 0.0f, 0.75f, 0.0f, 0.0f};
    // Layer 0 (probe 5) red at 0.5, layer 1 (probe 6) green at 1, layer 2
    // (probe 7) yellow -- yellow weighs 0, so it is not sampled.
    const auto e = renderer::probe_entries(w, {2, 0, 1}, {0.5f, 1.0f, 1.0f}, all_valid);
    ASSERT_EQ(e.size(), 4u);
    EXPECT_EQ(e[0].probe, 0); EXPECT_FLOAT_EQ(e[0].weight, 0.25f);
    EXPECT_EQ(e[1].probe, 2); EXPECT_FLOAT_EQ(e[1].weight, 0.75f);
    EXPECT_EQ(e[2].probe, 5); EXPECT_FLOAT_EQ(e[2].weight, 0.375f);
    EXPECT_EQ(e[3].probe, 6); EXPECT_FLOAT_EQ(e[3].weight, 0.25f);
}

TEST(BridgeProbeEntries, InvalidProbesMissingAndZeroValuesAreNotSampled) {
    const float w[renderer::kBridgeStates] = {0.5f, 0.0f, 0.5f, 0.0f, 0.0f};
    auto valid = [](int p) { return p != 2 && p != 5; };
    // Layer 0 invalid, layer 1 at value 0, layer 2 has no value sent.
    const auto e = renderer::probe_entries(w, {0, 0, 0}, {1.0f, 0.0f}, valid);
    ASSERT_EQ(e.size(), 1u);
    EXPECT_EQ(e[0].probe, 0);
    EXPECT_FLOAT_EQ(e[0].weight, 0.5f);
}

TEST(BridgeProbeEntries, KeepTheLargestWeightsWithinTheCaps) {
    const float w[renderer::kBridgeStates] = {0.1f, 0.2f, 0.3f, 0.4f, 0.0f};
    std::vector<int> states(20, 3);
    std::vector<float> values;
    for (int k = 0; k < 20; ++k) values.push_back(0.01f * static_cast<float>(k + 1));
    const auto e = renderer::probe_entries(w, states, values, all_valid);
    ASSERT_EQ(e.size(), static_cast<std::size_t>(renderer::kBridgeMaxProbeEntries));
    std::set<int> probes;
    for (const auto& x : e) probes.insert(x.probe);
    EXPECT_EQ(probes.count(0), 0u);                  // the lightest base goes
    for (int s = 1; s <= 3; ++s) EXPECT_EQ(probes.count(s), 1u) << s;
    for (int k = 0; k < 4; ++k)                      // ...and the 4 lightest layers
        EXPECT_EQ(probes.count(renderer::kBridgeStates + k), 0u) << k;
    for (int k = 4; k < 20; ++k)
        EXPECT_EQ(probes.count(renderer::kBridgeStates + k), 1u) << k;
}
