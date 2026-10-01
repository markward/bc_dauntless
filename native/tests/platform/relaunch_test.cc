#include <gtest/gtest.h>
#include "platform/relaunch.h"

using dauntless::platform::build_relaunch_argv;

TEST(RelaunchArgv, ExeFirstThenOriginalThenExtra) {
    auto a = build_relaunch_argv("/x/dauntless", {"--developer", "--game-dir", "/g"}, {"--mods"});
    EXPECT_EQ(a, (std::vector<std::string>{"/x/dauntless", "--developer", "--game-dir", "/g", "--mods"}));
}

TEST(RelaunchArgv, DoesNotDoubleAnExtraArg) {
    auto a = build_relaunch_argv("/x/dauntless", {"--mods", "--developer"}, {"--mods"});
    EXPECT_EQ(a, (std::vector<std::string>{"/x/dauntless", "--developer", "--mods"}));
}

TEST(RelaunchRequest, TakeIsOnceAndLastCallWins) {
    std::vector<std::string> out;
    EXPECT_FALSE(dauntless::platform::take_relaunch_request(&out));
    dauntless::platform::set_relaunch_request({"--a"});
    dauntless::platform::set_relaunch_request({"--mods"});
    ASSERT_TRUE(dauntless::platform::take_relaunch_request(&out));
    EXPECT_EQ(out, (std::vector<std::string>{"--mods"}));
    EXPECT_FALSE(dauntless::platform::take_relaunch_request(&out));
}
