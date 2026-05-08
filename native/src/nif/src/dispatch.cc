// native/src/nif/src/dispatch.cc
#include "dispatch.h"
#include "reader.h"

#include <nif/error.h>

namespace nif {

Dispatch& Dispatch::instance() {
    static Dispatch d;
    return d;
}

void Dispatch::register_parser(std::string type_name, BlockParser parser) {
    parsers_[std::move(type_name)] = std::move(parser);
}

bool Dispatch::has(const std::string& type_name) const {
    return parsers_.find(type_name) != parsers_.end();
}

const BlockParser& Dispatch::get(const std::string& type_name) const {
    auto it = parsers_.find(type_name);
    if (it == parsers_.end()) {
        UnknownBlockType e("no parser registered for block type: " + type_name);
        e.block_type = type_name;
        throw e;
    }
    return it->second;
}

// "End Of File" is a sentinel that closes every BC v3.1 NIF. Its body
// consumes zero bytes — the walker uses encountering this block as the
// signal to stop reading.
NIF_REGISTER_BLOCK(EndOfFile, [](Reader&) -> Block {
    return std::monostate{};
});

}  // namespace nif

// "End Of File" contains a space, so the macro-friendly form above
// registers under "EndOfFile". Add the spaced alias the file format
// actually uses.
namespace {
struct _nif_reg_eof_alias {
    _nif_reg_eof_alias() {
        ::nif::Dispatch::instance().register_parser(
            "End Of File",
            [](::nif::Reader&) -> ::nif::Block { return std::monostate{}; });
    }
} _nif_reg_eof_alias_instance;
}
