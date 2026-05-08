// native/src/nif/src/file.cc
#include <nif/file.h>
#include <nif/error.h>

#include "header.h"
#include "reader.h"

#include <fstream>
#include <vector>

namespace nif {

namespace {
std::vector<unsigned char> slurp(const std::filesystem::path& path) {
    std::ifstream in(path, std::ios::binary | std::ios::ate);
    if (!in) {
        ParseError e("could not open file");
        e.file = path;
        throw e;
    }
    auto size = static_cast<std::size_t>(in.tellg());
    in.seekg(0);
    std::vector<unsigned char> bytes(size);
    if (size > 0) {
        in.read(reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(size));
    }
    return bytes;
}
}  // namespace

File load(const std::filesystem::path& path) {
    auto bytes = slurp(path);
    Reader r(bytes.data(), bytes.size(), path);

    File f;
    f.source = path;

    auto h = parse_header(r);
    f.version = h.version;
    f.header_lines = h.lines;

    // Block walking lands in Task 18 (dispatch table). Until then, the file
    // is parsed only up to the end of the text header.
    return f;
}

}  // namespace nif
