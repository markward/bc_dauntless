// native/src/nif/src/resolver.cc
#include "resolver.h"

#include <nif/error.h>

#include <string>

namespace nif {

BlockHandle resolve_handle(File& f, BlockId id) {
    if (id == kNullBlockId) return BlockHandle{};
    if (id < 0 || static_cast<std::size_t>(id) >= f.blocks.size()) {
        ParseError e("block reference out of range: " + std::to_string(id));
        e.file = f.source;
        throw e;
    }
    return BlockHandle{ &f.blocks[static_cast<std::size_t>(id)] };
}

void resolve_references(File& /*f*/) {
    // Per-block reference fix-up is added by each block parser as it lands.
    // Today the variant has only std::monostate, so there are no references
    // to fix up. NiNode (Task 21) will be the first to add a real branch.
}

}  // namespace nif
