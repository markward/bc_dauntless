#include <gtest/gtest.h>
#include <renderer/key_gate.h>

using renderer::KeyGate;

TEST(KeyGate, PassesRawThroughWhenNotCaptured) {
    KeyGate g;
    EXPECT_FALSE(g.captured());
    EXPECT_TRUE(g.report(87, true));
    EXPECT_FALSE(g.report(87, false));
}

TEST(KeyGate, CapturedReportsEveryKeyUp) {
    KeyGate g;
    g.capture();
    EXPECT_TRUE(g.captured());
    EXPECT_FALSE(g.report(87, true));
    EXPECT_FALSE(g.report(32, true));
    EXPECT_FALSE(g.report(256, false));
}

TEST(KeyGate, KeyHeldThroughReleaseStaysUpUntilPhysicallyReleased) {
    KeyGate g;
    g.capture();
    g.release({256});                    // Esc still down when capture ends
    EXPECT_FALSE(g.captured());
    EXPECT_FALSE(g.report(256, true));   // still held: masked
    EXPECT_FALSE(g.report(256, true));
    EXPECT_FALSE(g.report(256, false));  // released: unmasks
    EXPECT_TRUE(g.report(256, true));    // a NEW press is reported
}

TEST(KeyGate, KeyPressedAfterReleaseIsNotMasked) {
    KeyGate g;
    g.capture();
    g.release({256});
    EXPECT_TRUE(g.report(87, true));     // W was not down at release
}

TEST(KeyGate, ReleaseWithNothingDownMasksNothing) {
    KeyGate g;
    g.capture();
    g.release({});
    EXPECT_TRUE(g.report(256, true));
}

TEST(KeyGate, StrayReleaseWhileNotCapturedDoesNotMask) {
    KeyGate g;
    g.release({256});
    EXPECT_TRUE(g.report(256, true));
}

TEST(KeyGate, SecondCaptureIsHarmlessAndClearsAStaleMask) {
    KeyGate g;
    g.capture();
    g.release({256});
    g.capture();
    g.capture();
    EXPECT_FALSE(g.report(256, true));
    g.release({});
    EXPECT_TRUE(g.report(256, true));    // the old mask did not survive
}
