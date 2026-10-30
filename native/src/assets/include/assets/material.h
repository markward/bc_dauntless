// native/src/assets/include/assets/material.h
#pragma once

#include <array>
#include <cstdint>
#include <string>

#include <glm/glm.hpp>

namespace assets {

struct Material {
    // From NiMaterialProperty
    glm::vec3 ambient{1.0f, 1.0f, 1.0f};
    glm::vec3 diffuse{1.0f, 1.0f, 1.0f};
    glm::vec3 specular{0.0f, 0.0f, 0.0f};
    glm::vec3 emissive{0.0f, 0.0f, 0.0f};
    float glossiness = 0.0f;
    float alpha = 1.0f;

    /// Texture stages. The Base slot is populated by NiTextureProperty
    /// (singular) or NiMultiTextureProperty (5-stage table). Two slots
    /// have runtime-attached conventions driven by AddLOD filename
    /// suffixes on NiImages (see model_build.cc):
    ///
    ///   Glow  — populated when a NiImage filename ends in "_glow".
    ///           Dual-binds with Base; alpha is the emissive mask.
    ///   Gloss — populated when a NiImage filename ends in "_specular"
    ///           or "_spec". Standalone per-texel specular mask; does
    ///           NOT dual-bind with Base.
    ///
    /// Decal0..2 mirror the NIF NiTexturingProperty decal slots only; they
    /// are NOT project hull-name decals, which live on Model::decals.
    ///
    /// Roughness/Metalness: `<stem>_rough` / `<stem>_metal` siblings, read
    /// only by the bridge PBR path (spec 2026-10-08-bridge-emitters §9.2).
    ///
    /// Emissive / EmissiveYellow / EmissiveRed / EmissiveSpecial:
    /// `<stem>_emissive`, `_emissive_y`, `_emissive_r`, `_emissive_s` siblings
    /// (RGB = emitted colour), probed on INTERIOR loads only and chosen per
    /// bridge state by the bridge pass (renderer::bridge_emissive_texture;
    /// spec 2026-10-08-bridge-emitters §13.1).
    enum class StageSlot {
        Base = 0, Dark, Detail, Gloss, Glow, Bump, Decal0, Decal1, Decal2,
        Roughness, Metalness,
        Emissive, EmissiveYellow, EmissiveRed, EmissiveSpecial,
        Count
    };

    struct TextureStage {
        int           texture_index = -1;
        std::uint32_t clamp_mode = 0;
        std::uint32_t filter_mode = 0;
        std::uint32_t uv_set = 0;
        std::uint32_t apply_mode = 0;
    };

    std::array<TextureStage, static_cast<std::size_t>(StageSlot::Count)> stages{};

    // From NiAlphaProperty (decoded bitfield, values verbatim)
    bool          blend_enabled = false;
    std::uint32_t blend_src_factor = 0;
    std::uint32_t blend_dst_factor = 0;
    bool          alpha_test_enabled = false;
    std::uint32_t alpha_test_func = 0;
    std::uint8_t  alpha_test_threshold = 0;
    bool          zwrite_when_blended = false;

    // From NiZBufferProperty
    bool          depth_test_enabled = true;
    bool          depth_write_enabled = true;
    std::uint32_t depth_func = 0;

    // From NiVertexColorProperty
    std::uint32_t vc_lighting_mode = 0;
    std::uint32_t vc_source = 0;

    /// Index into Model::texture_animations when this material's Base
    /// stage is driven by a NiFlipController, -1 otherwise. The
    /// renderer reads animation_index at draw time and substitutes the
    /// current frame's texture for stages[Base].texture_index.
    int animation_index = -1;

    /// Index into Model::panel_sources when this material's Base image is a
    /// bridge panel (interior loads only), -1 otherwise. Never -1 for an
    /// interior external albedo that decoded, whether or not a Lottie file
    /// exists beside it; the renderer decides from the files on disk. Head
    /// grafts drop it (the head's panel_sources are not merged).
    int panel_index = -1;

    /// Basename of the source file (NiImage::file_name) of the texture this
    /// material's Base stage was built from, "" when Base has none or the
    /// image is embedded. Recorded where the Base stage is resolved, so it
    /// reflects property inheritance from parent nodes exactly as drawn
    /// (nif_shapes' per-shape walk does not). Identity only -- the bridge
    /// editor's readout (spec 2026-10-08-bridge-emitters §4); never drawn.
    std::string base_texture_name;
};

}  // namespace assets
