// native/src/nif/include/nif/file.h
#pragma once

#include <nif/block.h>
#include <nif/version.h>

#include <filesystem>
#include <string>
#include <vector>

namespace nif {

struct File {
    Version version{};
    std::vector<Block> blocks;
    BlockHandle root{};
    std::vector<std::string> header_lines;  // multi-line text header preserved verbatim
    std::filesystem::path source;

    File() = default;
    File(const File&) = delete;
    File(File&&) = default;
    File& operator=(const File&) = delete;
    File& operator=(File&&) = default;
};

File load(const std::filesystem::path& path);

}  // namespace nif
