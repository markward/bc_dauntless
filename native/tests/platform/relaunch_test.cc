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

using dauntless::platform::quote_windows_arg;

TEST(RelaunchQuoteWindowsArg, PlainArgUnchanged) {
    EXPECT_EQ(quote_windows_arg("--developer"), "--developer");
    EXPECT_EQ(quote_windows_arg("C:\\Games\\BC"), "C:\\Games\\BC");
}

TEST(RelaunchQuoteWindowsArg, ArgWithSpacesIsQuoted) {
    EXPECT_EQ(quote_windows_arg("C:\\Program Files (x86)\\BC"), "\"C:\\Program Files (x86)\\BC\"");
    EXPECT_EQ(quote_windows_arg("a\tb"), "\"a\tb\"");
}

TEST(RelaunchQuoteWindowsArg, EmbeddedQuoteIsEscaped) {
    EXPECT_EQ(quote_windows_arg("say \"hi\""), "\"say \\\"hi\\\"\"");
    // Backslashes before an embedded quote are doubled, plus one for the quote.
    EXPECT_EQ(quote_windows_arg("a\\\"b"), "\"a\\\\\\\"b\"");
}

TEST(RelaunchQuoteWindowsArg, TrailingBackslashBeforeClosingQuoteIsDoubled) {
    EXPECT_EQ(quote_windows_arg("C:\\My Dir\\"), "\"C:\\My Dir\\\\\"");
}

TEST(RelaunchQuoteWindowsArg, EmptyArgIsTwoQuotes) {
    EXPECT_EQ(quote_windows_arg(""), "\"\"");
}
