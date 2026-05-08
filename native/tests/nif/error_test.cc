// native/tests/nif/error_test.cc — synthetic malformed inputs to nif::load.
#include <gtest/gtest.h>

#include <nif/error.h>
#include <nif/file.h>

#include <filesystem>
#include <fstream>
#include <vector>

namespace {

std::filesystem::path write_temp(const std::vector<unsigned char>& bytes,
                                 const char* suffix = "") {
    auto path = std::filesystem::temp_directory_path() /
                ("nif_error_test" + std::string(suffix) + ".nif");
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    out.write(reinterpret_cast<const char*>(bytes.data()),
              static_cast<std::streamsize>(bytes.size()));
    return path;
}

}  // namespace

TEST(ErrorTest, EmptyFileThrows) {
    auto path = write_temp({}, "_empty");
    EXPECT_THROW(nif::load(path), nif::ParseError);
}

TEST(ErrorTest, NoNewlineInFirstLineThrows) {
    // Bytes that look like text but never terminate with \n.
    auto path = write_temp(
        {'g','a','r','b','a','g','e',' ','b','y','t','e','s',' ','f','o','r','e','v','e','r'},
        "_nonl");
    EXPECT_THROW(nif::load(path), nif::ParseError);
}

TEST(ErrorTest, MissingVersionInMagicLineThrows) {
    std::vector<unsigned char> bytes;
    auto add_line = [&](const std::string& s) {
        for (char c : s) bytes.push_back(static_cast<unsigned char>(c));
        bytes.push_back('\n');
    };
    add_line("Bridge Commander File Format");  // no "Version" word
    add_line("");
    bytes.push_back(0x00);  // binary follows
    auto path = write_temp(bytes, "_noversion");
    EXPECT_THROW(nif::load(path), nif::VersionMismatch);
}

TEST(ErrorTest, NonexistentFileThrows) {
    EXPECT_THROW(nif::load("/nonexistent/path/file.nif"), nif::ParseError);
}

TEST(ErrorTest, BlockTypeLengthOverflowThrows) {
    // Valid header followed by a block with a bogus uint32 length.
    std::vector<unsigned char> bytes;
    auto add_line = [&](const std::string& s) {
        for (char c : s) bytes.push_back(static_cast<unsigned char>(c));
        bytes.push_back('\n');
    };
    add_line("NetImmerse File Format, Version 3.1");
    add_line("");
    // Block-type length = 9999 (way over the 80-byte plausible bound).
    bytes.push_back(0x0F);
    bytes.push_back(0x27);
    bytes.push_back(0x00);
    bytes.push_back(0x00);
    auto path = write_temp(bytes, "_typeoverflow");
    EXPECT_THROW(nif::load(path), nif::VersionMismatch);
}

TEST(ErrorTest, EndOfFileImmediatelyAfterHeaderSucceeds) {
    // Minimal valid v3.1 NIF: header text + immediate "End Of File" block.
    std::vector<unsigned char> bytes;
    auto add_line = [&](const std::string& s) {
        for (char c : s) bytes.push_back(static_cast<unsigned char>(c));
        bytes.push_back('\n');
    };
    add_line("NetImmerse File Format, Version 3.1");
    add_line("");
    // uint32(11) "End Of File"
    bytes.insert(bytes.end(), {0x0B, 0x00, 0x00, 0x00});
    for (char c : std::string("End Of File")) {
        bytes.push_back(static_cast<unsigned char>(c));
    }
    auto path = write_temp(bytes, "_minimal");
    auto f = nif::load(path);
    EXPECT_TRUE(f.eof_reached);
    EXPECT_EQ(f.blocks.size(), 0u);
    EXPECT_EQ(f.version.value, 0x03010000u);
}
