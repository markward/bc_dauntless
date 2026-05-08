// native/src/nif/include/nif/block.h
#pragma once

#include <nif/types.h>

#include <variant>
#include <vector>

namespace nif {

// Block variant grows as parsers land in subsequent tasks. Today: just the
// monostate placeholder, so the variant compiles.
using Block = std::variant<std::monostate>;

struct BlockHandle {
    const Block* ptr = nullptr;
    explicit operator bool() const { return ptr != nullptr; }
    const Block& operator*() const { return *ptr; }
    const Block* operator->() const { return ptr; }
};

}  // namespace nif
