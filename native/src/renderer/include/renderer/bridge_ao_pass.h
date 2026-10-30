// native/src/renderer/include/renderer/bridge_ao_pass.h
#pragma once

#include <renderer/bridge_lighting_tuning.h>
#include <renderer/hdr_target.h>
#include <renderer/ldr_target.h>

#include <cstdint>
#include <functional>
#include <memory>

namespace scenegraph { struct Camera; }

namespace renderer {

class Shader;

/// Quality knobs for the bridge AO. Task 5 fills these from the presets.
struct BridgeAoSettings {
    int   samples = 32;              // kernel samples, clamped to 4..64 in the shader
    float resolution_scale = 0.5f;   // AO target size vs the view
};

/// The AO kernel's look, live-tunable from the developer dials
/// (engine/bridge_ao_dials.py). The defaults are Mark's live pick
/// (2026-10-30): kBridgeLighting's radius/strength/bias, a distance-only bias,
/// and an 8-sample detail kernel applied after the diffuse ceiling (the
/// DBridge panel frames).
struct BridgeAoTuning {
    float radius   = kBridgeLighting.ao_radius;     // view-space units
    float strength = kBridgeLighting.ao_strength;
    float bias     = kBridgeLighting.ao_bias;       // view-space units
    float bias_dist = kBridgeLighting.ao_bias_dist; // bias per unit of distance
    // 0 = the distance bias applies in full; 1 = it is scaled by (1 - N.V),
    // so a wall seen head-on keeps only `bias` and a grazing floor the lot.
    float bias_facing = 0.0f;
    float min_len = 0.1f;          // shortest sample, as a fraction of radius
    /// 0..1: how much of the main AO also darkens the spot and area-light
    /// diffuse (bridge.frag): a stand-in for the shadow a chair casts from the
    /// ceiling strips, which have none. 0 = ambient only.
    float main_direct = 0.0f;
    /// 0..1: that share of the main AO applied AFTER the diffuse ceiling, on
    /// all diffuse (lights included). 0 = before it, ambient only.
    float main_final  = 0.0f;
    // Second, small-scale kernel in the same pass for shallow steps (the
    // DBridge panel frame is 1.5 units deep, under the main kernel's lowest
    // sample). 0 samples = off. Its bias is always facing-scaled.
    int   detail_samples  = 8;
    float detail_radius   = 3.0f;
    float detail_strength = 1.5f;
    float detail_bias     = 0.1f;
    /// 0..1: how much of the detail AO also darkens the spot and area-light
    /// diffuse (bridge.frag). 0 = ambient only.
    float detail_direct   = 0.0f;
    /// 0..1: that share of the detail AO applied AFTER the diffuse ceiling, on
    /// all diffuse (lights included); the ceiling's knee flattens darkening
    /// on a bright wall applied before it.
    float detail_final    = 1.0f;
};

/// Screen-space ambient occlusion for the main bridge view. Owns a
/// full-resolution normal + depth pre-pass target and a (scaled) AO target;
/// bridge.frag reads the AO (and the pre-pass depth, for its depth-aware
/// upsampling filter) and applies it to RECEIVED light only. Radius, strength
/// and bias come from the BridgeAoTuning set with set_tuning().
class BridgeAoPass {
public:
    BridgeAoPass();
    ~BridgeAoPass();
    BridgeAoPass(const BridgeAoPass&) = delete;
    BridgeAoPass& operator=(const BridgeAoPass&) = delete;

    /// Render the normal+depth pre-pass via `draw_normals` (which must draw
    /// the bridge with u_output_normal = 1 into the currently bound FBO),
    /// then the AO kernel. Restores the caller's FBO and viewport.
    /// Returns false (and leaves AO invalid) if w or h < 8.
    bool render(const scenegraph::Camera& camera, int w, int h,
                const BridgeAoSettings& s,
                const std::function<void()>& draw_normals);

    /// Kernel look, read at the next render().
    void set_tuning(const BridgeAoTuning& t) { tuning_ = t; }
    const BridgeAoTuning& tuning() const { return tuning_; }

    std::uint32_t ao_texture() const;      // valid after a true render()
    std::uint32_t depth_texture() const;   // the pre-pass depth
    std::uint32_t raw_sampler() const;     // NEAREST, no compare: bind with depth_texture()
    int ao_width() const;
    int ao_height() const;

private:
    HdrTarget               pre_;      // world normal (rgb) + depth, at w x h
    LdrTarget               ao_;       // occlusion in .r, 1 = open
    std::unique_ptr<Shader> shader_;
    std::uint32_t           vao_ = 0;
    std::uint32_t           vbo_ = 0;
    std::uint32_t           sampler_raw_ = 0;
    BridgeAoTuning          tuning_;
    void ensure_gl();
};

}  // namespace renderer
