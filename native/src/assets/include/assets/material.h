// native/src/assets/include/assets/material.h
#pragma once

#include <array>
#include <cstdint>

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
    /// PBR spike slots (populated by sibling-file probes in model_build.cc,
    /// same mechanism as Gloss): a NiImage's base texture is probed on disk
    /// for "<base>_normal.tga" / "_rough.tga" / "_metal.tga". These let
    /// modders ship tangent-space normal, roughness, and metalness maps for
    /// new ships; stock BC has none, so the slots stay empty and the PBR
    /// shader falls back to the global Dev Options knobs.
    enum class StageSlot {
        Base = 0, Dark, Detail, Gloss, Glow, Bump, Decal0, Decal1, Decal2,
        Normal, Roughness, Metalness,
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

    /// True when the Base-stage source texture's filename matches BC's
    /// baked-lightmap authoring convention (" lm.tga" or "_lm.tga",
    /// case-insensitive). Bridge geometry has duplicate meshes whose
    /// only material is a lightmap texture; those meshes need a
    /// multiply-blend draw over the regular base-textured geometry.
    /// Renderer's BridgePass reads this to partition bridge sub-passes.
    bool lightmap_pass = false;

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
};

}  // namespace assets
