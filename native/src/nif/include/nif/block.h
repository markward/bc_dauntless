// native/src/nif/include/nif/block.h
#pragma once

#include <nif/types.h>

#include <array>
#include <cstdint>
#include <string>
#include <variant>
#include <vector>

namespace nif {

/// Texture coordinate (u, v). 8 bytes.
struct TexCoord { float u, v; };

/// NiObjectNET base fields shared by every named NIF block (NiAVObject
/// blocks, NiProperty blocks, etc.). Field layout for v3.1.
struct ObjectNetBase {
    std::string name;
    std::uint32_t extra_data_link = 0;
    std::uint32_t controller_link = 0;
};

/// NiAVObject-derived block fields shared by NiNode and NiTriShape (and
/// other scene-graph blocks). Field layout for v3.1.
struct AvObjectBase {
    std::string name;
    std::uint32_t extra_data_link = 0;   // 0 = no extra data
    std::uint32_t controller_link = 0;   // 0 = no controller
    std::uint16_t flags = 0;
    Vec3 translation{};
    Mat3x3 rotation{ .m = {1, 0, 0, 0, 1, 0, 0, 0, 1} };
    float scale = 1.0f;
    Vec3 velocity{};
    std::vector<std::uint32_t> property_links;
    bool has_bounding_volume = false;
    // bounding_volume body deferred until a sample file requires it.
};

/// Generic scene-graph node. Adds child + effect arrays to the AV base.
struct NiNode {
    AvObjectBase av;
    std::vector<std::uint32_t> child_links;
    std::vector<std::uint32_t> effect_links;
};

/// Single triangle-mesh shape. Adds a Data ref pointing to a
/// NiTriShapeData block.
struct NiTriShape {
    AvObjectBase av;
    std::uint32_t data_link = 0;
};

/// Vertex / index / per-vertex-attribute storage for an NiTriShape.
/// Inherits NiGeometryData → NiTriBasedGeomData → NiTriShapeData.
/// Field layout for v3.1.
struct NiTriShapeData {
    // NiGeometryData (v3.1 filtered):
    std::uint16_t num_vertices = 0;
    bool has_vertices = false;
    std::vector<Vec3> vertices;
    bool has_normals = false;
    std::vector<Vec3> normals;
    Vec3 bound_center{};
    float bound_radius = 0.0f;
    bool has_vertex_colors = false;
    std::vector<Color4> vertex_colors;
    std::uint16_t data_flags = 0;        // lower 6 bits = number of UV sets
    bool has_uv = false;
    /// uv_sets[set_index][vertex_index]
    std::vector<std::vector<TexCoord>> uv_sets;
    // NiTriBasedGeomData:
    std::uint16_t num_triangles = 0;
    // NiTriShapeData:
    std::uint32_t num_triangle_points = 0;
    /// Each triangle is three uint16 vertex indices.
    std::vector<std::array<std::uint16_t, 3>> triangles;
    std::uint16_t num_match_groups = 0;
    /// Each match group is a list of vertex indices that share a position.
    std::vector<std::vector<std::uint16_t>> match_groups;
};

/// Z-buffer test/write property. v3.1 has only NiObjectNET base + flags.
struct NiZBufferProperty {
    ObjectNetBase obj;
    std::uint16_t flags = 0;
};

/// Vertex-color application mode. v3.1 has flags + vertex_mode + lighting_mode.
struct NiVertexColorProperty {
    ObjectNetBase obj;
    std::uint16_t flags = 0;
    std::uint32_t vertex_mode = 0;
    std::uint32_t lighting_mode = 0;
};

/// Alpha-blend / alpha-test property. v3.1 has flags + threshold.
struct NiAlphaProperty {
    ObjectNetBase obj;
    std::uint16_t flags = 0;
    std::uint8_t threshold = 0;
};

/// Texture-stage configuration (legacy pre-10.1 property).
/// v3.1: flags(uint16) + ps2_l(int16) + ps2_k(int16).
struct NiTextureModeProperty {
    ObjectNetBase obj;
    std::uint16_t flags = 0;
    std::int16_t ps2_l = 0;
    std::int16_t ps2_k = -75;
};

/// Image data block (legacy pre-10.1). Either references an external file
/// path or a NiRawImageData block via image_data_link.
struct NiImage {
    std::uint8_t use_external = 0;       // 0 = embedded, !=0 = external file
    std::string file_name;                // populated when use_external != 0
    std::uint32_t image_data_link = 0;    // populated when use_external == 0
    std::uint32_t unknown_int = 7;
    float unknown_float = 128.5f;         // since 3.1
};

/// Single-texture property. v3.1: flags + image link.
struct NiTextureProperty {
    ObjectNetBase obj;
    std::uint16_t flags = 0;
    std::uint32_t image_link = 0;
};

/// Surface material property. v3.1: flags + 4 colors + glossiness + alpha.
struct NiMaterialProperty {
    ObjectNetBase obj;
    std::uint16_t flags = 0;
    Color3 ambient{ 1.0f, 1.0f, 1.0f };
    Color3 diffuse{ 1.0f, 1.0f, 1.0f };
    Color3 specular{ 1.0f, 1.0f, 1.0f };
    Color3 emissive{ 0.0f, 0.0f, 0.0f };
    float glossiness = 10.0f;
    float alpha = 1.0f;
};

using Block = std::variant<
    std::monostate,
    NiNode,
    NiTriShape,
    NiTriShapeData,
    NiZBufferProperty,
    NiVertexColorProperty,
    NiAlphaProperty,
    NiTextureModeProperty,
    NiImage,
    NiTextureProperty,
    NiMaterialProperty
>;

struct BlockHandle {
    const Block* ptr = nullptr;
    explicit operator bool() const { return ptr != nullptr; }
    const Block& operator*() const { return *ptr; }
    const Block* operator->() const { return ptr; }
};

}  // namespace nif
