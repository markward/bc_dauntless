// native/src/assets/src/material_build.h
#pragma once

#include <assets/material.h>
#include <nif/block.h>

#include <string>
#include <unordered_map>
#include <unordered_set>

namespace assets::detail {

/// Inputs for building a Material — the property blocks linked from a
/// NiTriShape, plus an image-link → texture-index map produced by the
/// orchestrator.
struct MaterialInputs {
    const nif::NiMaterialProperty*     material      = nullptr;
    const nif::NiTextureProperty*      texture       = nullptr;
    const nif::NiMultiTextureProperty* multi_texture = nullptr;
    const nif::NiAlphaProperty*        alpha         = nullptr;
    const nif::NiZBufferProperty*      zbuffer       = nullptr;
    const nif::NiVertexColorProperty*  vertex_color  = nullptr;
    /// Maps NIF link ID of a NiImage → assets::Model::textures index.
    const std::unordered_map<std::uint32_t, int>* image_to_texture = nullptr;
    /// Link IDs of NiImages whose filename matches BC's AddLOD "_glow"
    /// suffix convention. When a property's base-stage image is in this
    /// set, the texture is routed to StageSlot::Glow instead of Base.
    const std::unordered_set<std::uint32_t>* glow_image_links = nullptr;
    /// Link IDs of NiImages whose filename matches BC's AddLOD
    /// "_specular" / "_spec" suffix convention. When a property's base-
    /// stage image is in this set, the texture is routed to
    /// StageSlot::Gloss (specular mask). Unlike glow, specular images
    /// do NOT dual-bind to Base — they are standalone masks.
    const std::unordered_set<std::uint32_t>* specular_image_links = nullptr;

    /// Phase 1 AddLOD shim: NIF link_id of a non-`_specular` NiImage ->
    /// Model::textures index of a sibling `*_specular.tga` file that the
    /// asset loader probed for and found on disk. When a property's
    /// base-stage image_link is in this map, the spec sibling is bound
    /// to StageSlot::Gloss in addition to the hull texture's normal
    /// Base/Glow binding. Stand-in for BC's runtime AddLOD `_specular`
    /// suffix arg until full AddLOD threading lands.
    const std::unordered_map<std::uint32_t, int>* sibling_specular_for_image = nullptr;

    /// Maps NIF link ID of a NiImage → its source filename
    /// (NiImage::file_name). Used by build_material to apply BC's
    /// `_lm.tga` lightmap-pass filename predicate without having to
    /// chase the NiImage block through nif::File from the predicate
    /// site. Populated by load_all_textures for `use_external != 0`
    /// images; embedded images (NiRawImageData) leave no entry.
    const std::unordered_map<std::uint32_t, std::string>* image_filename_for_link = nullptr;

    /// Number of UV coordinate sets the shape's geometry actually carries
    /// (NiTriShapeData::uv_sets.size()). Used to clamp a multitexture stage
    /// whose authored uv_set indexes past the available sets — BC's EBridge
    /// ceiling lightmaps reference uv_set=2 on geometry that only has sets
    /// 0 and 1, and the original fixed-function engine clamps such an
    /// out-of-range coordinate set to the highest available one. 0 means
    /// "unknown / don't clamp" (callers that don't supply geometry info).
    std::size_t geometry_uv_set_count = 0;

    /// Link ID of the NiTextureProperty currently in `texture` (0 if
    /// none). Looked up against flip_image_override_for_prop below.
    std::uint32_t texture_link_id = 0;

    /// NiTextureProperty link_id → NiImage link_id for animated texture
    /// properties (image_link=0 with a NiFlipController on
    /// controller_link). Static stand-in for animation: the override
    /// resolves to the controller's frame-0 image_link. EBridge.nif's
    /// "Lcars Schematic right" panels are the driving case — without
    /// this they have no resolvable base texture and render as the
    /// white-fallback quad.
    const std::unordered_map<std::uint32_t, std::uint32_t>*
        flip_image_override_for_prop = nullptr;
};

Material build_material(const MaterialInputs&);

}  // namespace assets::detail
