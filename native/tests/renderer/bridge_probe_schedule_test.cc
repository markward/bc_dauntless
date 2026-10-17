// native/tests/renderer/bridge_probe_schedule_test.cc
//
// CPU-only: the bridge reflection capture queue's order (spec
// 2026-10-17-bridge-reflection-layers §4.7). The shown state's base first,
// then that state's layers, then the other bases, then the other layers --
// one probe at a time, index order within each group. Probe ids: base of
// state s = s, layer k = kBridgeStates + k.
#include <gtest/gtest.h>

#include <renderer/bridge_probe_schedule.h>

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
