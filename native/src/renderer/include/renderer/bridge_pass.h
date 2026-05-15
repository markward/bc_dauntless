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

private:
    /// Lazily-allocated 1x1 white texture, used as a fallback for any
    /// bridge mesh whose Base-stage texture failed to load. Same role
    /// as FrameSubmitter::white_texture_ but owned by this pass so the
    /// GL handle lifetime tracks BridgePass.
    std::uint32_t white_texture_ = 0;
    std::uint32_t ensure_white_texture();
};

}  // namespace renderer
