// native/src/nif/src/blocks/av_object_base.cc
#include "av_object_base.h"

#include <nif/error.h>

#include <string>

namespace nif {

ObjectNetBase parse_object_net_base(Reader& r) {
    ObjectNetBase o;
    o.name = r.read_string_uint32();
    o.extra_data_link = r.read_uint32();
    o.controller_link = r.read_uint32();
    return o;
}

AvObjectBase parse_av_object_base(Reader& r, const char* block_type) {
    AvObjectBase a;
    a.obj = parse_object_net_base(r);
    a.flags = r.read_uint16();
    a.translation = r.read_vec3();
    a.rotation = r.read_mat3x3();
    a.scale = r.read_float();
    a.velocity = r.read_vec3();

    auto num_properties = r.read_uint32();
    a.property_links.reserve(num_properties);
    for (std::uint32_t i = 0; i < num_properties; ++i) {
        a.property_links.push_back(r.read_uint32());
    }

    // v3.x bools follow niflib's ReadBool(version <= 0x04010001) semantics:
    // any non-zero uint32 is true. BC files use hash-like sentinel values
    // (e.g. 0x03e54648) for true; do not strict-compare against 0/1.
    a.has_bounding_volume = (r.read_uint32() != 0);
    if (a.has_bounding_volume) {
        ParseError e(std::string(block_type) +
                     " bounding_volume body not yet implemented");
        e.file = r.source();
        e.byte_offset = r.offset();
        e.block_type = block_type;
        throw e;
    }
    return a;
}

}  // namespace nif
