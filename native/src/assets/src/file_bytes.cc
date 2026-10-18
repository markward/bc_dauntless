// native/src/assets/src/file_bytes.cc
#include <assets/file_bytes.h>

#include <fstream>

namespace assets {

std::optional<std::vector<std::uint8_t>> read_binary_file(
        const std::filesystem::path& path) {
    std::ifstream in(path, std::ios::binary | std::ios::ate);
    if (!in) return std::nullopt;
    const std::streamoff size = in.tellg();
    if (size < 0) return std::nullopt;
    std::vector<std::uint8_t> bytes(static_cast<std::size_t>(size));
    in.seekg(0, std::ios::beg);
    if (size > 0 && !in.read(reinterpret_cast<char*>(bytes.data()), size)) {
        return std::nullopt;
    }
    return bytes;
}

}  // namespace assets
