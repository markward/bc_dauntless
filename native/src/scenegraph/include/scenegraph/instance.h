// native/src/scenegraph/include/scenegraph/instance.h
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <unordered_map>
#include <vector>
#include <glm/glm.hpp>
#include <glm/gtc/quaternion.hpp>
#include "scenegraph/breach_events.h"
#include "scenegraph/damage_decals.h"
#include "scenegraph/hull_carve.h"

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
/// - Comm: comm/remote-set geometry (starbase viewscreens, hailing faces),
///   drawn by the comm render branch for the active comm set only.
enum class Pass : std::uint8_t { Space = 0, Bridge = 1, Comm = 2 };

struct Instance {
    ModelHandle model_handle = 0;
    glm::mat4 world{1.0f};
    bool visible = true;
    Pass pass = Pass::Space;

    /// Which comm/remote set this instance belongs to (0 = none). Lets the
    /// comm render branch draw only the viewscreen's active set when several
    /// comm sets are realized at once.
    std::uint32_t comm_set_id = 0;

    /// True for ship hulls; gates the opaque-pass Fresnel rim term so it
    /// applies to hulls only. Planets share the opaque shader but must
    /// not receive a metallic rim — they default false. The future
    /// planet-atmosphere effect will add its own per-instance params.
    bool rim_eligible = false;

    /// Fresnel rim intensity for rim_eligible instances. Authored per-ship
    /// by the hardpoint stats' 'SpecularCoef' key; ships without one keep
    /// this default.
    float rim_strength = 0.1f;

    /// Scales the ship's self-illumination (material emissive + glow map) at
    /// draw time. 1.0 = normal; 0.0 = no self-light, used for destroyed ships
    /// so a dead hull goes dark in space (diffuse-lit, specular, and rim
    /// terms are unaffected, so the hull stays visible).
    float emissive_scale = 1.0f;

    /// Per-instance skinning palette (world_pose * inverse_bind per bone).
    /// Empty = the renderer falls back to the model's bind pose. Set by the
    /// placement system; SP2 rewrites it per frame. Runtime state, not saved.
    std::vector<glm::mat4> bone_palette;

    /// Per-instance officer FACE override (lip-sync). When face_active, the
    /// bridge sub-pass blends the HEAD meshes' base texture between face_tex_a
    /// and face_tex_b by face_mix (0 = a, 1 = b). A 0 id falls back to the
    /// head's own base texture (= neutral), so ("neutral","neutral",0) renders
    /// byte-identically to the un-overridden head. Off (face_active=false) for
    /// every officer that never speaks. Runtime state, never serialized.
    bool          face_active = false;
    std::uint32_t face_tex_a  = 0;  // GL texture id
    std::uint32_t face_tex_b  = 0;  // GL texture id
    float         face_mix    = 0.0f;

    /// Per-instance node-local overrides for NON-SKINNED instances (the
    /// bridge): node_index -> animated local_transform. Empty = every node
    /// uses its model's static local (byte-identical to the un-animated
    /// render). Written each frame by the bridge-node animation updater;
    /// consulted by walk_bridge_meshes. Runtime state, never serialized.
    std::unordered_map<int, glm::mat4> node_overrides;

    /// ── Per-channel skeletal animation (BC TGAnimBlender-faithful) ──────────
    /// One channel per skeleton bone. clip_index < 0 = unbound: the bone shows
    /// its rest local (SkeletalAnim::rest_locals) or, without a rest pose, the
    /// skeleton bind local. Channels are (re)bound per bone by
    /// renderer::bind_clip via BC's exact case-sensitive node-name strcmp;
    /// bones a clip does not track keep their previous channel untouched
    /// (per-node last-bind-wins — every bridge animation in BC is
    /// non-exclusive). Runtime state, never serialized.
    struct BoneChannel {
        int    clip_index  = -1;   // into Model::animations
        int    track_index = -1;   // into clip.tracks (name-matched at bind)
        double start_wall_time = 0.0;
        float  blend_in_s = 0.0f;  // 0 = snap; else ramp seed→clip over this
        bool   loop = false;           // idle loops; gestures/walks clamp+hold
        bool   root_motion = false;    // root bone: APPLY track translation
        bool   use_clip_base = false;  // omitted-channel base = clip rest_locals
        bool   hold_at_start = false;  // evaluate at t=0 and settle immediately
        bool   settled = false;        // non-loop reached end AND blend done
        // Blend seed: the bone's local at bind time, decomposed once.
        glm::vec3 seed_t{0.0f};
        glm::quat seed_r{1.0f, 0.0f, 0.0f, 0.0f};
        float     seed_s = 1.0f;
    };
    struct SkeletalAnim {
        std::vector<BoneChannel> channels;   // sized to skeleton at first use
        std::vector<glm::mat4>  rest_locals; // placement pose, sampled ONCE
        std::vector<glm::mat4>  last_locals; // last evaluated pose (blend seeds)
        bool has_rest = false;
        bool dirty    = true;   // false = everything settled; skip rebuilds
    };
    SkeletalAnim anim;

    /// SP2 animation playback. clip_index < 0 means "not animated" (palette is
    /// left as set, or bind). The clip lives in the instance's Model::animations.
    /// Runtime state, never serialized.
    struct AnimationState {
        int    clip_index     = -1;
        double start_wall_time = 0.0;
        bool   loop           = false;
        bool   sample_at_start = false;  // movement clips evaluate from t=0
        bool   sample_at_end  = false;   // rest "stand"/"seated" clips hold t=dur
        bool   settled        = false;   // non-loop clip reached its end
        bool   layer_over_rest = false;  // gesture: sample OVER the rest pose
    };
    AnimationState animation;

    AnimationState rest_pose;            // the static placement pose (AT_DEFAULT)
    bool           has_rest_pose = false;

    /// Per-instance persistent damage decals (object space, body frame).
    /// Runtime VFX state only — never serialized to saves.
    DamageDecalRing decals;

    /// Per-instance hull carve spheres (body frame, model units). Drives the
    /// see-through breach holes and the interior voxel splat. Runtime VFX only
    /// — never serialized to saves.
    HullCarveField carve;

    /// Per-instance transient breach-event ring. Drives debris, venting, and
    /// molten-rim emissive. Runtime VFX only — never serialized to saves.
    BreachEventRing breach_events;

    /// Self-referential id stamped by World::create_instance so particle
    /// emitters built from breach events can carry an attached instance_id.
    InstanceId id{};

    /// Per-instance glow capsules (body frame, model units).
    /// Runtime VFX state only — never serialized. Fixed cap: a ship has at
    /// most a handful of glow regions.
    // Cap covers a ship's full glow set: warp nacelles + several impulse
    // engine pods + sensor array, with headroom for multi-hardpoint ships.
    static constexpr std::size_t kMaxGlowRegions = 12;
    struct GlowRegion {
        glm::vec3 center{0.0f};
        glm::vec3 axis{0.0f, 1.0f, 0.0f};
        float     radius = 0.0f;
        float     aft = 0.0f;
        float     fore = 0.0f;
        float     dim_target = 1.0f;
        float     disable_time = -1.0f;
        float     flicker = 0.0f;   // 1 = disabled (continuous flicker), 0 = solid settle
        float     gain = 1.0f;      // >1 brightens glow inside the region (impulse power/speed)
        glm::vec3 gain_axis{0.0f};  // aft dir (model space); non-zero gates gain to faces facing it
        bool      active = false;
    };
    std::array<GlowRegion, kMaxGlowRegions> glow_regions{};
};

}  // namespace scenegraph
