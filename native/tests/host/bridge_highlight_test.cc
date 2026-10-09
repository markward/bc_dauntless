// native/tests/host/bridge_highlight_test.cc
//
// set_bridge_highlight's body (spec 2026-10-08-bridge-emitters §4), tested
// where the developer gate can be flipped from C++ -- never from Python.
#include <gtest/gtest.h>

#include "bridge_highlight.h"
#include "developer_mode.h"

#include <renderer/bridge_pass.h>

namespace {

class BridgeHighlightApply : public ::testing::Test {
protected:
    void TearDown() override { dauntless::set_developer_mode(false); }
    dauntless::BridgeHighlight state;
    renderer::BridgePass pass;   // no GL is touched by set_highlight
};

constexpr unsigned long long kModel = 0x1234;

}  // namespace

TEST_F(BridgeHighlightApply, GateOffIsANoOp) {
    dauntless::set_developer_mode(false);
    EXPECT_FALSE(dauntless::apply_bridge_highlight(state, &pass, kModel, 3, 4));
    EXPECT_EQ(state.model, 0u);
    EXPECT_EQ(state.selected, -1);
    EXPECT_EQ(state.hover, -1);
    EXPECT_EQ(pass.highlight_model(), 0u);
    EXPECT_EQ(pass.highlight_selected(), -1);
}

TEST_F(BridgeHighlightApply, GateOnWithAValidModelSetsStateAndPass) {
    dauntless::set_developer_mode(true);
    EXPECT_TRUE(dauntless::apply_bridge_highlight(state, &pass, kModel, 3, 4));
    EXPECT_EQ(state.model, kModel);
    EXPECT_EQ(state.selected, 3);
    EXPECT_EQ(state.hover, 4);
    EXPECT_EQ(pass.highlight_model(), kModel);
    EXPECT_EQ(pass.highlight_selected(), 3);
    EXPECT_EQ(pass.highlight_hover(), 4);
}

TEST_F(BridgeHighlightApply, GateOnWithNoneOrAStaleIdClears) {
    dauntless::set_developer_mode(true);
    dauntless::apply_bridge_highlight(state, &pass, kModel, 3, 4);
    // The binding resolves None and a stale InstanceId both to handle 0.
    EXPECT_TRUE(dauntless::apply_bridge_highlight(state, &pass, 0, 3, 4));
    EXPECT_EQ(state.model, 0u);
    EXPECT_EQ(state.selected, -1);
    EXPECT_EQ(state.hover, -1);
    EXPECT_EQ(pass.highlight_model(), 0u);
    EXPECT_EQ(pass.highlight_selected(), -1);
    EXPECT_EQ(pass.highlight_hover(), -1);
}

TEST_F(BridgeHighlightApply, WithoutAPassOnlyTheStateChanges) {
    dauntless::set_developer_mode(true);
    EXPECT_TRUE(dauntless::apply_bridge_highlight(state, nullptr, kModel, 1, 2));
    EXPECT_EQ(state.model, kModel);
    EXPECT_EQ(state.selected, 1);
}
