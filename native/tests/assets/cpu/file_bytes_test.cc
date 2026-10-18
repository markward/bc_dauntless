// native/tests/assets/cpu/file_bytes_test.cc
//
// assets::read_binary_file reads a whole file in one block. The renderer's
// loaders copied files one byte at a time through istreambuf_iterator; for
// the 12.6 MB collision-scuff normal map that was ~350 ms in Debug, in the
// frame of the session's first scuff (perf-register P-11).
#include <gtest/gtest.h>

#include <assets/file_bytes.h>

#include <cstdint>
#include <filesystem>
#include <fstream>
#include <vector>

namespace {

std::filesystem::path scratch(const char* name) {
    auto dir = std::filesystem::temp_directory_path() / "dauntless_file_bytes_test";
    std::filesystem::create_directories(dir);
    return dir / name;
}

}  // namespace

TEST(ReadBinaryFile, ReturnsEveryByteUnchanged) {
    std::vector<std::uint8_t> want(1 << 20);
    for (std::size_t i = 0; i < want.size(); ++i)
        want[i] = static_cast<std::uint8_t>((i * 2654435761u) >> 13);
    want[0] = 0; want[1] = 0xFF; want[2] = '\n'; want[3] = '\r'; want[4] = 0x1A;
    const auto path = scratch("all_bytes.bin");
    {
        std::ofstream out(path, std::ios::binary);
        out.write(reinterpret_cast<const char*>(want.data()),
                  static_cast<std::streamsize>(want.size()));
    }
    const auto got = assets::read_binary_file(path);
    ASSERT_TRUE(got.has_value());
    EXPECT_EQ(*got, want);
}

TEST(ReadBinaryFile, AnEmptyFileIsAnEmptyBuffer) {
    const auto path = scratch("empty.bin");
    { std::ofstream out(path, std::ios::binary); }
    const auto got = assets::read_binary_file(path);
    ASSERT_TRUE(got.has_value());
    EXPECT_TRUE(got->empty());
}

TEST(ReadBinaryFile, AMissingFileIsNullopt) {
    EXPECT_FALSE(assets::read_binary_file(scratch("no_such_file.bin")).has_value());
}
