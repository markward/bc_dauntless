// native/src/nif/src/blocks/ni_tri_shape.cc
//
// NiTriShape and NiTriShapeData parsers for NIF v3.1.
//
// NiTriShape body = NiAVObject base + uint32 data_link.
//   (Skin Instance ref appears since 3.3.0.13, so absent in v3.1.)
//
// NiTriShapeData body =
//   NiGeometryData (v3.1):
//     num_vertices     (uint16)
//     has_vertices     (uint32 bool)
//     vertices         (Vec3 × num_vertices)        if has_vertices
//     has_normals      (uint32 bool)
//     normals          (Vec3 × num_vertices)        if has_normals
//     bound_center     (Vec3)
//     bound_radius     (float)
//     has_vertex_colors (uint32 bool)
//     vertex_colors    (Color4 × num_vertices)      if has_vertex_colors
//     data_flags       (uint16)                     until 4.2.2.0
//     has_uv           (uint32 bool)                until 4.0.0.2
//     uv_sets          (TexCoord × num_vertices) × (data_flags & 63)
//   NiTriBasedGeomData:
//     num_triangles    (uint16)
//   NiTriShapeData:
//     num_triangle_points (uint32)
//     triangles        (Triangle × num_triangles)
//     num_match_groups (uint16)                     since 3.1
//     match_groups     (MatchGroup × num_match_groups)
//
// MatchGroup = uint16 num_vertices + uint16[num_vertices] vertex_indices.

#include "../dispatch.h"
#include "../reader.h"
#include "av_object_base.h"

#include <nif/block.h>
#include <nif/error.h>

#include <array>
#include <cstdint>
#include <string>

namespace nif {

namespace {

constexpr std::uint32_t kPlausibleVertexCap = 65535;
constexpr std::uint32_t kPlausibleTriangleCap = 65535;

NiTriShape parse_NiTriShape_body(Reader& r) {
    NiTriShape s;
    s.av = parse_av_object_base(r, "NiTriShape");
    s.data_link = r.read_uint32();
    return s;
}

/// v3.x NIFs encode bool as uint32 with "non-zero == true" semantics —
/// niflib's own ReadBool returns `(ReadUInt(in) != 0)` for these versions.
/// Real BC files use uint32 values like 0x03e54648 (a hash-like sentinel)
/// for true; do NOT reject them as malformed.
bool read_bool_uint32(Reader& r) {
    return r.read_uint32() != 0;
}

NiTriShapeData parse_NiTriShapeData_body(Reader& r) {
    NiTriShapeData d;

    d.num_vertices = r.read_uint16();
    d.has_vertices = read_bool_uint32(r);
    if (d.has_vertices) {
        d.vertices.reserve(d.num_vertices);
        for (std::uint16_t i = 0; i < d.num_vertices; ++i) {
            d.vertices.push_back(r.read_vec3());
        }
    }

    d.has_normals = read_bool_uint32(r);
    if (d.has_normals) {
        d.normals.reserve(d.num_vertices);
        for (std::uint16_t i = 0; i < d.num_vertices; ++i) {
            d.normals.push_back(r.read_vec3());
        }
    }

    d.bound_center = r.read_vec3();
    d.bound_radius = r.read_float();

    d.has_vertex_colors = read_bool_uint32(r);
    if (d.has_vertex_colors) {
        d.vertex_colors.reserve(d.num_vertices);
        for (std::uint16_t i = 0; i < d.num_vertices; ++i) {
            d.vertex_colors.push_back(r.read_color4());
        }
    }

    // numUvSets is uint16 in v3.1; lower 6 bits encode the number of UV sets.
    d.data_flags = r.read_uint16();
    d.has_uv = read_bool_uint32(r);
    auto num_uv_sets = static_cast<std::uint32_t>(d.data_flags & 0x3F);
    // Per niflib's NiGeometryData::Read, uvSets are always read regardless
    // of has_uv — has_uv is informational only.
    d.uv_sets.resize(num_uv_sets);
    for (auto& set : d.uv_sets) {
        set.reserve(d.num_vertices);
        for (std::uint16_t i = 0; i < d.num_vertices; ++i) {
            TexCoord t;
            t.u = r.read_float();
            t.v = r.read_float();
            set.push_back(t);
        }
    }

    // NiTriBasedGeomData
    d.num_triangles = r.read_uint16();
    if (d.num_triangles > kPlausibleTriangleCap) {
        ParseError e("num_triangles implausible: " + std::to_string(d.num_triangles));
        e.file = r.source();
        e.byte_offset = r.offset();
        e.block_type = "NiTriShapeData";
        throw e;
    }

    // NiTriShapeData
    d.num_triangle_points = r.read_uint32();
    d.triangles.reserve(d.num_triangles);
    for (std::uint16_t i = 0; i < d.num_triangles; ++i) {
        std::array<std::uint16_t, 3> tri{};
        tri[0] = r.read_uint16();
        tri[1] = r.read_uint16();
        tri[2] = r.read_uint16();
        d.triangles.push_back(tri);
    }

    d.num_match_groups = r.read_uint16();
    d.match_groups.resize(d.num_match_groups);
    for (auto& group : d.match_groups) {
        auto num = r.read_uint16();
        group.reserve(num);
        for (std::uint16_t i = 0; i < num; ++i) {
            group.push_back(r.read_uint16());
        }
    }

    if (d.num_vertices > kPlausibleVertexCap) {
        ParseError e("num_vertices implausible: " + std::to_string(d.num_vertices));
        e.file = r.source();
        e.byte_offset = r.offset();
        e.block_type = "NiTriShapeData";
        throw e;
    }

    return d;
}

}  // namespace

NIF_REGISTER_BLOCK(NiTriShape, [](Reader& r) -> Block {
    return parse_NiTriShape_body(r);
});

NIF_REGISTER_BLOCK(NiTriShapeData, [](Reader& r) -> Block {
    return parse_NiTriShapeData_body(r);
});

}  // namespace nif
