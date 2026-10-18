// native/src/assets/include/assets/file_bytes.h
#pragma once

#include <cstdint>
#include <filesystem>
#include <optional>
#include <vector>

namespace assets {

/// The whole file at `path`, read in one block; nullopt when it cannot be
/// opened or read. Prefer this to copying through istreambuf_iterator, which
/// reads one byte at a time: the 12.6 MB collision-scuff normal map took
/// ~350 ms that way in Debug (perf-register P-11).
std::optional<std::vector<std::uint8_t>> read_binary_file(
    const std::filesystem::path& path);

}  // namespace assets
