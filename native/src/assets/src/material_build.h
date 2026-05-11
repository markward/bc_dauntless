// native/src/assets/src/material_build.h
#pragma once

#include <assets/material.h>
#include <nif/block.h>

#include <unordered_map>
#include <unordered_set>

namespace assets::detail {

/// Inputs for building a Material — the property blocks linked from a
/// NiTriShape, plus an image-link → texture-index map produced by the
/// orchestrator.
struct MaterialInputs {
    const nif::NiMaterialProperty*     material      = nullptr;
    const nif::NiTextureProperty*      texture       = nullptr;
    const nif::NiTexturingProperty*    texturing     = nullptr;
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
};

Material build_material(const MaterialInputs&);

}  // namespace assets::detail
