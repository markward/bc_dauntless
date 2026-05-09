// native/tests/nif/ship_gate_test.cc — v1 ship-gate test:
// every BC sample file parses end-to-end and reaches End Of File.
#include <gtest/gtest.h>

#include <nif/file.h>

#include "sample_paths.h"

#include <filesystem>

class ShipGate : public ::testing::TestWithParam<SampleFile> {};

TEST_P(ShipGate, ParsesAllBlocksAndReachesEndOfFile) {
    const auto& sample = GetParam();
    if (!std::filesystem::exists(sample.path)) {
        GTEST_SKIP() << "Sample missing (BC install required): " << sample.path;
    }
    auto f = nif::load(sample.path);
    EXPECT_TRUE(f.eof_reached)
        << sample.nickname << " stopped at block " << f.blocks.size()
        << " — see NIF_TRACE=1 output for the unimplemented block type.";
    EXPECT_GT(f.blocks.size(), 0u);
}

INSTANTIATE_TEST_SUITE_P(
    AllSamples, ShipGate,
    ::testing::ValuesIn(kSampleFiles()),
    [](const auto& info) { return info.param.nickname; });
