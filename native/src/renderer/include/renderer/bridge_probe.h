// native/src/renderer/include/renderer/bridge_probe.h
#pragma once

#include <renderer/cubemap_target.h>

#include <scenegraph/camera.h>

#include <glm/glm.hpp>

#include <cstdint>
#include <memory>

namespace renderer {

class Shader;

/// One bridge reflection probe: a six-face capture of the room from a point,
/// GGX-prefiltered over kBridgeProbeMips mips (mip k = roughness
/// k / (kBridgeProbeMips - 1); mip 0 is a straight copy), for the bridge
/// shader to sample with textureLod(cube, R, rough * (mips - 1)). Captured on
/// demand (bridge load, lighting edits), never per frame.
///
/// Face order and orientation are BackdropPass::bake's table, so a
/// texture(cube, worldDir) sample returns what was drawn looking along
/// worldDir -- the same convention as the sky cubemap.
class BridgeProbe {
public:
    BridgeProbe();
    ~BridgeProbe();
    BridgeProbe(const BridgeProbe&) = delete;
    BridgeProbe& operator=(const BridgeProbe&) = delete;

    /// Lazily create the GL objects (raw + prefiltered cubes, prefilter
    /// program, full-screen triangle). False without a current GL context or
    /// if a target cannot be allocated. Idempotent.
    bool ensure();

    /// Render the six faces at `origin`: for each face, the raw cube's face is
    /// bound (viewport = kBridgeProbeFace², cleared to opaque black, depth
    /// cleared) and `draw_face(const scenegraph::Camera&)` is called with a
    /// 90° square camera looking down that face. Then prefilter() runs. The
    /// caller's FBO, viewport, clear colour, program, VAO, texture bindings and
    /// depth/blend/cull/scissor enables are restored afterwards. No-op if
    /// ensure() fails.
    template <class DrawFace>
    void capture(glm::vec3 origin, DrawFace draw_face) {
        if (!ensure()) return;
        begin_capture();
        for (int i = 0; i < 6; ++i) draw_face(begin_face(i, origin));
        end_capture();
    }

    /// Fill the prefiltered cube's mips from the raw capture (GGX importance
    /// sampling, Karis split-sum's first term). Called by capture(); public so
    /// a caller that drew the raw cube another way can re-run it. Restores the
    /// same state capture() does.
    void prefilter();

    /// The prefiltered cube (kBridgeProbeFace, kBridgeProbeMips levels).
    std::uint32_t texture() const { return out_.texture(); }
    /// True once a capture has been prefiltered into texture().
    bool valid() const { return captured_ && out_.valid(); }

    /// The split-sum BRDF LUT: kBridgeBrdfLutSize² GL_RG16F, x = NdotV,
    /// y = roughness, rg = (A, B) so that specular IBL = prefiltered *
    /// (F0 * A + B). Generated once, lazily, and cached in a function-local
    /// static. ASSUMPTION: one live GL context per process at a time (the
    /// game, and each test, which creates its context in SetUp). The cache is
    /// keyed on the current GLFW context and re-validated with glIsTexture, so
    /// a test that destroys its window and makes a new one gets a fresh LUT;
    /// two simultaneously live contexts would each regenerate (and orphan)
    /// it. 0 without a context. Never deleted -- it dies with its context.
    static std::uint32_t brdf_lut();

private:
    struct SavedState;
    void begin_capture();
    scenegraph::Camera begin_face(int i, glm::vec3 origin);
    void end_capture();
    void run_prefilter();

    CubemapTarget raw_;                       // capture, full mip chain
    CubemapTarget out_;                       // prefiltered, kBridgeProbeMips
    std::unique_ptr<Shader> prefilter_;
    std::uint32_t vao_ = 0;
    std::uint32_t vbo_ = 0;
    bool captured_ = false;
    std::unique_ptr<SavedState> saved_;       // live between begin/end_capture
};

}  // namespace renderer
