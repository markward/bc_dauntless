// native/src/nif/src/blocks/ni_node.cc
//
// NiNode parser for NIF v3.1 (BC). Body = NiAVObject base fields followed
// by num_children + child_links + num_effects + effect_links. Verified
// against Galaxy.nif's root block (offset 0xA2, 102-byte body).
#include "../dispatch.h"
#include "../reader.h"
#include "av_object_base.h"

#include <nif/block.h>

namespace nif {

namespace {

NiNode parse_NiNode_body(Reader& r) {
    NiNode n;
    n.av = parse_av_object_base(r, "NiNode");

    auto num_children = r.read_uint32();
    n.child_links.reserve(num_children);
    for (std::uint32_t i = 0; i < num_children; ++i) {
        n.child_links.push_back(r.read_uint32());
    }

    auto num_effects = r.read_uint32();
    n.effect_links.reserve(num_effects);
    for (std::uint32_t i = 0; i < num_effects; ++i) {
        n.effect_links.push_back(r.read_uint32());
    }
    return n;
}

}  // namespace

NIF_REGISTER_BLOCK(NiNode, [](Reader& r) -> Block {
    return parse_NiNode_body(r);
});

// NiBone inherits NiNode and adds no fields of its own (per nifxml schema).
// Reuses the NiNode parser; the resulting Block holds an NiNode value with
// the bone's transform and child links.
NIF_REGISTER_BLOCK(NiBone, [](Reader& r) -> Block {
    return parse_NiNode_body(r);
});

}  // namespace nif
