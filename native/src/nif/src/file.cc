// native/src/nif/src/file.cc
#include <nif/file.h>
#include <nif/error.h>

namespace nif {

File load(const std::filesystem::path& path) {
    ParseError e("nif::load not yet implemented");
    e.file = path;
    throw e;
}

}  // namespace nif
