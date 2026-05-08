// native/src/nif/include/nif/file.h
#pragma once

#include <nif/block.h>
#include <nif/version.h>

#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

namespace nif {

struct File {
    Version version{};
    std::vector<Block> blocks;
    /// v3.x stores a 4-byte link ID with each block (the value following
    /// the type name, before the body). Indices in this vector are parallel
    /// to `blocks`. Used by the resolver to map cross-block references.
    std::vector<std::uint32_t> block_ids;
    BlockHandle root{};
    std::vector<std::string> header_lines;
    std::filesystem::path source;
    /// True when the walker reached the "End Of File" sentinel block; false
    /// if it stopped earlier (e.g., on an unimplemented block type during
    /// the early phases when only some parsers are registered).
    bool eof_reached = false;

    File() = default;
    File(const File&) = delete;
    File(File&&) = default;
    File& operator=(const File&) = delete;
    File& operator=(File&&) = default;
};

File load(const std::filesystem::path& path);

}  // namespace nif
