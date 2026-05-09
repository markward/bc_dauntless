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

    enum class StageSlot {
        Base = 0, Dark, Detail, Gloss, Glow, Bump, Decal0, Decal1, Decal2,
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
};

}  // namespace assets
