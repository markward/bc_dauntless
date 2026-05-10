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
};

Material build_material(const MaterialInputs&);

}  // namespace assets::detail
