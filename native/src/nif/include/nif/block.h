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
/// other scene-graph blocks). Field layout for v3.1. Composes the
/// NiObjectNET base via `obj` rather than flattening the fields, matching
/// the pattern used by property blocks (NiZBufferProperty etc.).
struct AvObjectBase {
    ObjectNetBase obj;
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

/// Camera. v3.x body: NiAVObject + frustum bounds + viewport bounds +
/// lod_adjust + scene_link + 2 unknown ints.
struct NiCamera {
    AvObjectBase av;
    float frustum_left = 0.0f, frustum_right = 0.0f;
    float frustum_top = 0.0f, frustum_bottom = 0.0f;
    float frustum_near = 0.0f, frustum_far = 0.0f;
    float viewport_left = 0.0f, viewport_right = 0.0f;
    float viewport_top = 0.0f, viewport_bottom = 0.0f;
    float lod_adjust = 0.0f;
    std::uint32_t scene_link = 0;
    std::uint32_t unknown_int = 0;
    std::uint32_t unknown_int_3 = 0;  // only present in v3.x (until 3.1)
};

/// Common base fields for dynamic-effect (light) blocks. v3.x has
/// NiAVObject base + num_affected_node_pointers + uint32 array.
struct DynamicEffectBase {
    AvObjectBase av;
    std::uint32_t num_affected_node_pointers = 0;
    std::vector<std::uint32_t> affected_node_pointers;
};

/// Light common fields: dimmer + 3 colors.
struct LightCommon {
    DynamicEffectBase dyn;
    float dimmer = 1.0f;
    Color3 ambient_color{};
    Color3 diffuse_color{};
    Color3 specular_color{};
};

/// Point light: LightCommon + 3 attenuation coefficients.
struct NiPointLight {
    LightCommon light;
    float constant_attenuation = 0.0f;
    float linear_attenuation = 0.0f;
    float quadratic_attenuation = 0.0f;
};

/// Spot light: NiPointLight body + cutoff_angle + exponent.
struct NiSpotLight {
    LightCommon light;
    float constant_attenuation = 0.0f;
    float linear_attenuation = 0.0f;
    float quadratic_attenuation = 0.0f;
    float cutoff_angle = 0.0f;
    float exponent = 0.0f;
};

/// Ambient light source: just the LightCommon body, no extra fields.
struct NiAmbientLight {
    LightCommon light;
};

/// Directional light source: just the LightCommon body, no extra fields.
struct NiDirectionalLight {
    LightCommon light;
};

/// Single visibility key: time + visibility byte (0 = hidden, !=0 = visible).
struct VisKey {
    float time = 0.0f;
    std::uint8_t visible = 1;
};

/// Per-keyframe visibility data. v3.x: num_keys (uint32) + linear-typed keys.
struct NiVisData {
    std::uint32_t num_keys = 0;
    std::vector<VisKey> keys;
};

/// Float-keyframe data block. Same shape as NiKeyframeData's FloatKeyArray
/// but stored standalone (referenced by NiRollController and similar).
struct NiFloatData {
    std::uint32_t num_keys = 0;
    std::uint32_t interpolation = 0;
    struct K {
        float time = 0.0f, value = 0.0f;
        float fwd_tan = 0.0f, bwd_tan = 0.0f;       // QUADRATIC only
        float tension = 0.0f, bias = 0.0f, continuity = 0.0f;  // TBC only
    };
    std::vector<K> keys;
};

/// Roll-axis animation controller. v3.x body: NiTimeController fields +
/// data_link (ref to NiFloatData / NiPosData per niflib's link_stack).
struct NiRollController {
    std::uint32_t next_controller_link = 0;
    std::uint16_t flags = 0;
    float frequency = 1.0f;
    float phase = 0.0f;
    float start_time = 0.0f;
    float stop_time = 0.0f;
    std::uint32_t unknown_integer = 0;
    std::uint32_t data_link = 0;
};

/// Embedded RGB or RGBA image data referenced by an NiImage block (when
/// use_external == 0). 1 byte per channel, width × height pixels.
struct NiRawImageData {
    std::uint32_t width = 0;
    std::uint32_t height = 0;
    std::uint32_t image_type = 0;       // 1 = RGB, 2 = RGBA
    std::vector<std::uint8_t> pixels;   // row-major, channels-per-pixel = 3 or 4
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

/// Per-slot texture descriptor used by NiTexturingProperty.
/// Field set per niflib's TexDesc Read for v3.1.
struct TexDesc {
    bool has = false;
    std::uint32_t source_link = 0;   // link to NiImage / NiSourceTexture
    std::uint32_t clamp_mode = 0;
    std::uint32_t filter_mode = 0;
    std::uint32_t uv_set = 0;
    std::int16_t  ps2_l = 0;
    std::int16_t  ps2_k = -75;
    std::uint16_t unknown1 = 0;
};

/// Standard NIF texture-stage descriptor used by NiTexturingProperty.
struct NiTexturingProperty {
    ObjectNetBase obj;
    std::uint16_t flags = 0;
    std::uint32_t apply_mode = 2;     // APPLY_MODULATE
    std::uint32_t texture_count = 7;
    TexDesc base;
    TexDesc dark;
    TexDesc detail;
    TexDesc gloss;
    TexDesc glow;
    TexDesc bump_map;
    float bump_map_luma_scale = 0.0f;
    float bump_map_luma_offset = 0.0f;
    /// Bump map matrix (Matrix22 = 4 floats).
    std::array<float, 4> bump_map_matrix{};
    TexDesc decal0;
    TexDesc decal1;  // populated only if texture_count >= 8
    TexDesc decal2;  // populated only if texture_count >= 9
};

/// Per-stage entry inside a legacy NiMultiTextureProperty body.
/// Field set per niflib's NiMultiTextureProperty::Read for v3.1 — note
/// that this is NOT TexDesc (different field set, smaller, no flags or
/// transform).
struct MultiTextureElement {
    bool has_image = false;
    std::uint32_t image_link = 0;
    std::uint32_t clamp_mode = 0;
    std::uint32_t filter_mode = 0;
    std::uint32_t uv_set = 0;
    std::int16_t  ps2_l = 0;
    std::int16_t  ps2_k = -75;
    std::uint16_t unknown_short3 = 0;
};

/// Legacy v3.x multi-texture property. Despite the schema's
/// `inherit="NiTexturingProperty"` line, niflib's actual Read implements
/// a custom body of 5 MultiTextureElement entries — much simpler than
/// NiTexturingProperty's slot list.
struct NiMultiTextureProperty {
    ObjectNetBase obj;
    std::uint16_t flags = 0;
    std::uint32_t unknown_int = 0;
    std::array<MultiTextureElement, 5> elements;
};

/// Per-vertex bone weight in legacy v3.x skin data.
struct OldSkinWeight {
    float weight = 0.0f;
    std::uint16_t vertex_index = 0;
    Vec3 unknown_vector{};
};

/// Legacy v3.x skinning controller. Per-bone vertex influence lists.
/// (NiTimeController fields + numBones + per-bone vertex counts and links
/// + per-(bone,vertex) weight data.)
struct NiTriShapeSkinController {
    // NiTimeController:
    std::uint32_t next_controller_link = 0;
    std::uint16_t flags = 0;
    float frequency = 1.0f;
    float phase = 0.0f;
    float start_time = 0.0f;
    float stop_time = 0.0f;
    std::uint32_t unknown_integer = 0;
    // body:
    std::uint32_t num_bones = 0;
    std::vector<std::uint32_t> vertex_counts_per_bone;
    std::vector<std::uint32_t> bone_links;
    /// bone_weights[bone_index][vertex_within_bone] -> OldSkinWeight
    std::vector<std::vector<OldSkinWeight>> bone_weights;
};

/// Keyframe animation data block. Holds rotation, translation, scale
/// keyframe arrays referenced by NiKeyframeController.
struct NiKeyframeData {
    std::uint32_t num_rotation_keys = 0;
    std::uint32_t rotation_type = 0;     // 1=linear, 2=quadratic, 3=TBC, 4=XYZ
    /// Per-rotation keyframe; raw fields preserved for fidelity. Layout
    /// per niflib's Key<Quaternion> NifStream spec.
    struct QuatKey {
        float time = 0.0f;
        Quat value{};
        float tension = 0.0f, bias = 0.0f, continuity = 0.0f;  // only for rotation_type == TBC
    };
    std::vector<QuatKey> quaternion_keys;
    /// Used only when rotation_type == 4 and version <= 10.1.0.0.
    float unknown_float = 0.0f;
    struct FloatKeyArray {
        std::uint32_t num_keys = 0;
        std::uint32_t interpolation = 0;
        struct K {
            float time = 0.0f, value = 0.0f;
            float fwd_tan = 0.0f, bwd_tan = 0.0f;       // QUADRATIC
            float tension = 0.0f, bias = 0.0f, continuity = 0.0f;  // TBC
        };
        std::vector<K> keys;
    };
    /// xyz_rotations[0..2] only populated when rotation_type == 4.
    std::array<FloatKeyArray, 3> xyz_rotations;
    struct Vec3KeyArray {
        std::uint32_t num_keys = 0;
        std::uint32_t interpolation = 0;
        struct K {
            float time = 0.0f;
            Vec3 value{};
            Vec3 fwd_tan{}, bwd_tan{};                  // QUADRATIC
            float tension = 0.0f, bias = 0.0f, continuity = 0.0f;
        };
        std::vector<K> keys;
    };
    Vec3KeyArray translations;
    FloatKeyArray scales;
};

/// Visibility-animation controller. v3.x body: NiTimeController fields +
/// data_link (ref to NiVisData).
struct NiVisController {
    std::uint32_t next_controller_link = 0;
    std::uint16_t flags = 0;
    float frequency = 1.0f;
    float phase = 0.0f;
    float start_time = 0.0f;
    float stop_time = 0.0f;
    std::uint32_t unknown_integer = 0;
    std::uint32_t data_link = 0;
};

/// Look-at constraint. v3.x body: NiTimeController fields + look_at_node_link.
struct NiLookAtController {
    std::uint32_t next_controller_link = 0;
    std::uint16_t flags = 0;
    float frequency = 1.0f;
    float phase = 0.0f;
    float start_time = 0.0f;
    float stop_time = 0.0f;
    std::uint32_t unknown_integer = 0;
    std::uint32_t look_at_node_link = 0;
};

/// Texture-flip controller — cycles through a list of NiImage links over time.
struct NiFlipController {
    // NiTimeController:
    std::uint32_t next_controller_link = 0;
    std::uint16_t flags = 0;
    float frequency = 1.0f;
    float phase = 0.0f;
    float start_time = 0.0f;
    float stop_time = 0.0f;
    std::uint32_t unknown_integer = 0;
    // body:
    std::uint32_t texture_slot = 0;
    float delta = 0.0f;
    std::uint32_t num_sources = 0;
    std::vector<std::uint32_t> image_links;
};

/// Keyframe animation controller (NiTimeController + data ref).
/// v3.1 body: next_controller_link, flags, frequency, phase, start_time,
/// stop_time, unknown_integer (only since v3.1 and earlier), data_link.
struct NiKeyframeController {
    std::uint32_t next_controller_link = 0;
    std::uint16_t flags = 0;
    float frequency = 1.0f;
    float phase = 0.0f;
    float start_time = 0.0f;
    float stop_time = 0.0f;
    std::uint32_t unknown_integer = 0;
    std::uint32_t data_link = 0;
};

/// String-typed extra data attached to a node (legacy pre-v10).
struct NiStringExtraData {
    std::uint32_t next_extra_data_link = 0;
    std::uint32_t bytes_remaining = 0;
    std::string string_data;
};

/// Voxel-collision extra data. References a NiBinaryVoxelData block.
struct NiBinaryVoxelExtraData {
    std::uint32_t next_extra_data_link = 0;
    std::uint32_t unknown_int = 0;
    std::uint32_t data_link = 0;
};

/// Raw voxel-collision data block. Field set per niflib's
/// NiBinaryVoxelData::Read.
struct NiBinaryVoxelData {
    std::uint16_t unknown_short1 = 0;
    std::uint16_t unknown_short2 = 0;
    std::uint16_t unknown_short3 = 0;
    std::array<float, 7> unknown_7_floats{};
    /// 7 × 12 bytes of opaque preamble data.
    std::array<std::array<std::uint8_t, 12>, 7> unknown_bytes1{};
    std::uint32_t num_unknown_vectors = 0;
    std::vector<Vec3> unknown_vectors;
    std::uint32_t num_unknown_bytes2 = 0;
    std::vector<std::uint8_t> unknown_bytes2;
    std::array<std::uint32_t, 5> unknown_5_ints{};
    /// Opaque voxel-grid bytes captured between the parsed header and the
    /// End Of File marker. Real v3.x voxel encoding is undocumented; this
    /// preserves the bytes so future work can decode them.
    std::vector<std::uint8_t> raw_voxel_payload;
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
    NiMaterialProperty,
    NiKeyframeController,
    NiTriShapeSkinController,
    NiTexturingProperty,
    NiMultiTextureProperty,
    NiKeyframeData,
    NiStringExtraData,
    NiFlipController,
    NiBinaryVoxelExtraData,
    NiBinaryVoxelData,
    NiCamera,
    NiPointLight,
    NiSpotLight,
    NiAmbientLight,
    NiDirectionalLight,
    NiRawImageData,
    NiVisController,
    NiVisData,
    NiLookAtController,
    NiRollController,
    NiFloatData
>;

struct BlockHandle {
    const Block* ptr = nullptr;
    explicit operator bool() const { return ptr != nullptr; }
    const Block& operator*() const { return *ptr; }
    const Block* operator->() const { return ptr; }
};

}  // namespace nif
