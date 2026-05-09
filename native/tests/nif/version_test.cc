// native/tests/nif/version_test.cc
#include <gtest/gtest.h>
#include <nif/version.h>

TEST(Version, IsBcReturnsTrueForKnownBcVersion) {
    nif::Version v{ nif::kBcVersionValue };
    EXPECT_TRUE(nif::is_bc(v));
}

TEST(Version, IsBcReturnsFalseForOtherVersions) {
    nif::Version v{ 0x04000002 };  // Morrowind
    EXPECT_FALSE(nif::is_bc(v));
}
