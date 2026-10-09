// native/src/renderer/include/renderer/bridge_ao_pass.h
#pragma once

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

/// Screen-space ambient occlusion for the main bridge view. Owns a
/// full-resolution normal + depth pre-pass target and a (scaled) AO target;
/// bridge.frag reads the AO (and the pre-pass depth, for its depth-aware
/// upsampling filter) and applies it to RECEIVED light only. Radius, strength
/// and bias come from kBridgeLighting (bridge_lighting_tuning.h).
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
    void ensure_gl();
};

}  // namespace renderer
