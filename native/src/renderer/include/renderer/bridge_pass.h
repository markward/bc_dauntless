// native/src/renderer/include/renderer/bridge_pass.h
#pragma once

#include <renderer/frame.h>

#include <functional>

namespace scenegraph { class World; struct Camera; }

namespace renderer {

class Pipeline;

/// Renders the bridge interior in two sub-passes:
///   A. Base geometry — opaque, alpha-test, base * ambient via bridge.frag.
///   B. Lightmap geometry — multiply blend over the framebuffer via
///      lightmap.frag, depth-write off + polygon offset.
///
/// Caller is responsible for clearing color + depth before calling
/// render() (the bridge interior overlays the space scene; see
/// host_bindings.cc::frame). Renders nothing if the world has no
/// scenegraph::Pass::Bridge-tagged instances.
class BridgePass {
public:
    using ModelLookup = std::function<const assets::Model*(unsigned long long)>;

    BridgePass() = default;
    ~BridgePass();
    BridgePass(const BridgePass&) = delete;
    BridgePass& operator=(const BridgePass&) = delete;

    void render(const scenegraph::World& world,
                const scenegraph::Camera& camera,
                Pipeline& pipeline,
                const ModelLookup& lookup,
                const Lighting& lighting);

    /// Set the wall time used to advance NiFlipController-driven
    /// texture animations on bridge materials. Host loop calls this
    /// once per tick with time.monotonic().
    void set_wall_time(double t) { wall_time_ = t; }

    /// Identify the viewscreen instance by its model handle and supply the
    /// render-to-texture color texture to draw on it. When a Pass::Bridge
    /// instance's model_handle matches the registered viewscreen handle and
    /// the texture is non-zero, the base sub-pass binds `tex` as u_base_color
    /// and forces full emissive (so the feed isn't dimmed by bridge ambient).
    /// tex==0 (the default) restores the instance's authored NIF texture —
    /// the step-5b blank panel.
    void set_viewscreen_model(unsigned long long model_handle) {
        viewscreen_model_handle_ = model_handle;
    }
    void set_viewscreen_texture(unsigned int tex) { viewscreen_tex_ = tex; }

private:
    /// Lazily-allocated 1x1 white texture, used as a fallback for any
    /// bridge mesh whose Base-stage texture failed to load. Same role
    /// as FrameSubmitter::white_texture_ but owned by this pass so the
    /// GL handle lifetime tracks BridgePass.
    std::uint32_t white_texture_ = 0;
    std::uint32_t ensure_white_texture();
    double wall_time_ = 0.0;
    unsigned long long viewscreen_model_handle_ = 0;
    unsigned int       viewscreen_tex_ = 0;
};

}  // namespace renderer
