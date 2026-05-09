// native/tests/nif/reader_test.cc
#include <gtest/gtest.h>
#include "../../src/nif/src/reader.h"

#include <vector>

namespace {
nif::Reader make_reader(std::vector<unsigned char> bytes) {
    static thread_local std::vector<unsigned char> storage;
    storage = std::move(bytes);
    return nif::Reader(storage.data(), storage.size(), "<test>");
}
}

TEST(Reader, ReadsLittleEndianUint32) {
    auto r = make_reader({0x78, 0x56, 0x34, 0x12});
    EXPECT_EQ(r.read_uint32(), 0x12345678u);
    EXPECT_EQ(r.bytes_remaining(), 0u);
}

TEST(Reader, ReadsFloat) {
    auto r = make_reader({0x00, 0x00, 0x80, 0x3F});
    EXPECT_FLOAT_EQ(r.read_float(), 1.0f);
}

TEST(Reader, ReadsLengthPrefixedString) {
    auto r = make_reader({0x05, 0x00, 0x00, 0x00, 'h','e','l','l','o'});
    EXPECT_EQ(r.read_string_uint32(), "hello");
}

TEST(Reader, ThrowsOnTruncation) {
    auto r = make_reader({0x00, 0x00});
    EXPECT_THROW(r.read_uint32(), nif::ParseError);
}

TEST(Reader, OffsetAdvancesAfterRead) {
    auto r = make_reader({0x01, 0x00, 0x02, 0x00});
    EXPECT_EQ(r.read_uint16(), 1u);
    EXPECT_EQ(r.offset(), 2u);
    EXPECT_EQ(r.read_uint16(), 2u);
    EXPECT_EQ(r.offset(), 4u);
}

TEST(Reader, ReadsVec3) {
    auto r = make_reader({
        0x00, 0x00, 0x80, 0x3F,
        0x00, 0x00, 0x00, 0x40,
        0x00, 0x00, 0x40, 0x40,
    });
    auto v = r.read_vec3();
    EXPECT_FLOAT_EQ(v.x, 1.0f);
    EXPECT_FLOAT_EQ(v.y, 2.0f);
    EXPECT_FLOAT_EQ(v.z, 3.0f);
}

TEST(Reader, ReadsLine) {
    auto r = make_reader({'l','i','n','e','\n','x'});
    EXPECT_EQ(r.read_line(), "line");
    EXPECT_EQ(r.offset(), 5u);
}
