// native/src/nif/src/dispatch.cc
#include "dispatch.h"

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

// "End Of File" is a v3.x sentinel handled directly in the walker (file.cc
// stops the loop on that exact type name before dispatching). No parser is
// registered for it — the walker never reaches dispatch for that name.

}  // namespace nif
