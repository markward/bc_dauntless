// native/src/scenegraph/include/scenegraph/instance.h
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <vector>
#include <glm/glm.hpp>
#include "scenegraph/damage_decals.h"
#include "scenegraph/hull_craters.h"

namespace scenegraph {

using ModelHandle = std::uint64_t;  // Opaque key into the asset cache.

struct InstanceId {
    std::uint32_t index = 0;
    std::uint32_t generation = 0;
    bool operator==(const InstanceId&) const = default;
};

/// Which renderer pass an instance is drawn in.
/// - Space: ships, planets, suns, dust, backdrops (default).
/// - Bridge: the bridge interior geometry, drawn after a depth clear.
enum class Pass : std::uint8_t { Space = 0, Bridge = 1 };

struct Instance {
    ModelHandle model_handle = 0;
    glm::mat4 world{1.0f};
    bool visible = true;
    Pass pass = Pass::Space;

    /// True for ship hulls; gates the opaque-pass Fresnel rim term so it
    /// applies to hulls only. Planets share the opaque shader but must
    /// not receive a metallic rim — they default false. The future
    /// planet-atmosphere effect will add its own per-instance params.
    bool rim_eligible = false;

    /// Scales the ship's self-illumination (material emissive + glow map) at
    /// draw time. 1.0 = normal; 0.0 = no self-light, used for destroyed ships
    /// so a dead hull goes dark in space (diffuse-lit, specular, and rim
    /// terms are unaffected, so the hull stays visible).
    float emissive_scale = 1.0f;

    /// Per-instance skinning palette (world_pose * inverse_bind per bone).
    /// Empty = the renderer falls back to the model's bind pose. Set by the
    /// placement system; SP2 rewrites it per frame. Runtime state, not saved.
    std::vector<glm::mat4> bone_palette;

    /// SP2 animation playback. clip_index < 0 means "not animated" (palette is
    /// left as set, or bind). The clip lives in the instance's Model::animations.
    /// Runtime state, never serialized.
    struct AnimationState {
        int    clip_index     = -1;
        double start_wall_time = 0.0;
        bool   loop           = false;
        bool   sample_at_start = false;  // movement clips evaluate from t=0
        bool   settled        = false;   // non-loop clip reached its end
    };
    AnimationState animation;

    /// Per-instance persistent damage decals (object space, body frame).
    /// Runtime VFX state only — never serialized to saves.
    DamageDecalRing decals;

    /// Per-instance persistent hull-deformation craters (object space, body
    /// frame). Runtime VFX state only — never serialized to saves (spec §9).
    HullCraterField craters;

    /// Per-instance glow capsules (body frame, model units).
    /// Runtime VFX state only — never serialized. Fixed cap: a ship has at
    /// most a handful of glow regions.
    static constexpr std::size_t kMaxGlowRegions = 4;
    struct GlowRegion {
        glm::vec3 center{0.0f};
        glm::vec3 axis{0.0f, 1.0f, 0.0f};
        float     radius = 0.0f;
        float     aft = 0.0f;
        float     fore = 0.0f;
        float     dim_target = 1.0f;
        float     disable_time = -1.0f;
        float     flicker = 0.0f;   // 1 = disabled (continuous flicker), 0 = solid settle
        bool      active = false;
    };
    std::array<GlowRegion, kMaxGlowRegions> glow_regions{};
};

}  // namespace scenegraph
