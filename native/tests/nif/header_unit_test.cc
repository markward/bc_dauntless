// native/tests/nif/header_unit_test.cc — header parser unit tests that don't
// require sample files on disk.
#include <gtest/gtest.h>

#include <nif/error.h>

#include "../../src/nif/src/header.h"
#include "../../src/nif/src/reader.h"

#include <vector>

namespace {
nif::Reader make_reader(std::vector<unsigned char>& bytes) {
    return nif::Reader(bytes.data(), bytes.size(), "<test>");
}
}  // namespace

TEST(VersionFromMagicLine, ParsesV31) {
    EXPECT_EQ(nif::parse_version_from_magic_line(
                  "NetImmerse File Format, Version 3.1"),
              0x03010000u);
}

TEST(VersionFromMagicLine, ParsesV4002) {
    EXPECT_EQ(nif::parse_version_from_magic_line(
                  "NetImmerse File Format, Version 4.0.0.2"),
              0x04000002u);
}

TEST(VersionFromMagicLine, ThrowsOnNoVersionWord) {
    EXPECT_THROW(nif::parse_version_from_magic_line("garbage"),
                 nif::VersionMismatch);
}

TEST(ParseHeader, ReadsMultipleTextLinesUntilBinary) {
    std::vector<unsigned char> bytes;
    auto add_line = [&](const std::string& s) {
        for (char c : s) bytes.push_back(static_cast<unsigned char>(c));
        bytes.push_back('\n');
    };
    add_line("NetImmerse File Format, Version 3.1");
    add_line("Numerical Design Limited, Chapel Hill, NC 27514");
    add_line("Copyright (c) 1996-2000");
    add_line("All Rights Reserved");
    bytes.push_back(0x10);  // first binary byte (length-prefix LSB)
    bytes.push_back(0x00);
    bytes.push_back(0x00);
    bytes.push_back(0x00);

    auto r = make_reader(bytes);
    auto h = nif::parse_header(r);
    EXPECT_EQ(h.lines.size(), 4u);
    EXPECT_EQ(h.lines.front(), "NetImmerse File Format, Version 3.1");
    EXPECT_EQ(h.version.value, 0x03010000u);
    // The reader should be positioned at the first binary byte.
    EXPECT_EQ(r.peek_uint8(), 0x10u);
}

TEST(ParseHeader, ThrowsOnEmptyInput) {
    std::vector<unsigned char> bytes;
    auto r = make_reader(bytes);
    EXPECT_THROW(nif::parse_header(r), nif::VersionMismatch);
}
