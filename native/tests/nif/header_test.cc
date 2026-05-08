// native/tests/nif/header_test.cc
#include <gtest/gtest.h>

#include <nif/file.h>
#include <nif/version.h>

#include "sample_paths.h"

#include <filesystem>

class HeaderTest : public ::testing::TestWithParam<SampleFile> {};

TEST_P(HeaderTest, RecognizedAsBcVersion) {
    const auto& sample = GetParam();
    if (!std::filesystem::exists(sample.path)) {
        GTEST_SKIP() << "Sample missing (BC install required): " << sample.path;
    }
    auto f = nif::load(sample.path);
    EXPECT_TRUE(nif::is_bc(f.version))
        << sample.nickname << " parsed version 0x" << std::hex << f.version.value
        << " but kBcVersionValue is 0x" << nif::kBcVersionValue;
}

TEST_P(HeaderTest, HasNonEmptyTextHeader) {
    const auto& sample = GetParam();
    if (!std::filesystem::exists(sample.path)) {
        GTEST_SKIP() << "Sample missing: " << sample.path;
    }
    auto f = nif::load(sample.path);
    EXPECT_FALSE(f.header_lines.empty()) << sample.nickname;
    // First line is the magic line and must contain "Version".
    EXPECT_NE(f.header_lines.front().find("Version"), std::string::npos)
        << sample.nickname << " magic line: " << f.header_lines.front();
}

INSTANTIATE_TEST_SUITE_P(
    AllSamples, HeaderTest,
    ::testing::ValuesIn(kSampleFiles()),
    [](const auto& info) { return info.param.nickname; });
