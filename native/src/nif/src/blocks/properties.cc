// native/src/nif/src/blocks/properties.cc
//
// NiZBufferProperty / NiVertexColorProperty / NiAlphaProperty parsers
// for NIF v3.1.
//
// All three inherit from NiProperty (which is just NiObjectNET — name,
// extra_data_link, controller_link) and add a small number of body fields:
//
//   NiZBufferProperty (v3.1):
//     flags (uint16)            // ZBufferFlags
//     // Function field is since 4.1.0.12 — absent in v3.1.
//
//   NiVertexColorProperty (v3.1):
//     flags (uint16)            // VertexColorFlags
//     vertex_mode (uint32)      // SourceVertexMode (until 20.0.0.5)
//     lighting_mode (uint32)    // LightingMode (until 20.0.0.5)
//
//   NiAlphaProperty (v3.1):
//     flags (uint16)            // AlphaFlags
//     threshold (uint8)
//     // The two "Unknown" fields are until 2.3 — absent in v3.1.

#include "../dispatch.h"
#include "../reader.h"
#include "av_object_base.h"

#include <nif/block.h>

namespace nif {

namespace {

NiZBufferProperty parse_NiZBufferProperty_body(Reader& r) {
    NiZBufferProperty p;
    p.obj = parse_object_net_base(r);
    p.flags = r.read_uint16();
    return p;
}

NiVertexColorProperty parse_NiVertexColorProperty_body(Reader& r) {
    NiVertexColorProperty p;
    p.obj = parse_object_net_base(r);
    p.flags = r.read_uint16();
    p.vertex_mode = r.read_uint32();
    p.lighting_mode = r.read_uint32();
    return p;
}

NiAlphaProperty parse_NiAlphaProperty_body(Reader& r) {
    NiAlphaProperty p;
    p.obj = parse_object_net_base(r);
    p.flags = r.read_uint16();
    p.threshold = r.read_uint8();
    return p;
}

}  // namespace

NIF_REGISTER_BLOCK(NiZBufferProperty, [](Reader& r) -> Block {
    return parse_NiZBufferProperty_body(r);
});

NIF_REGISTER_BLOCK(NiVertexColorProperty, [](Reader& r) -> Block {
    return parse_NiVertexColorProperty_body(r);
});

NIF_REGISTER_BLOCK(NiAlphaProperty, [](Reader& r) -> Block {
    return parse_NiAlphaProperty_body(r);
});

}  // namespace nif
