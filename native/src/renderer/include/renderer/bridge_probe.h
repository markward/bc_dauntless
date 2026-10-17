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
/// k / (kBridgeProbeMips - 1); mip 0 is a straight copy), all in one call.
/// The one-shot REFERENCE: no production code uses it any more -- BridgePass
/// captures through the time-sliced BridgeProbeArray, which must match it
/// (bridge_probe_array_test.cc's SteppedCaptureMatchesOneShot is the oracle;
/// bridge_probe_test.cc covers the capture and prefilter themselves). The
/// production half of this header is BrdfLut, below.
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
        // Restores the caller's GL state on EVERY exit, including a throw
        // from draw_face (the probe then stays as it was: no new capture).
        struct Restore {
            BridgeProbe* p;
            ~Restore() { p->restore_capture_state(); }
        } restore{this};
        for (int i = 0; i < 6; ++i) draw_face(begin_face(i, origin));
        finish_capture();
    }

    /// Fill the prefiltered cube's mips from the raw capture (GGX importance
    /// sampling, Karis split-sum's first term). Called by capture(); public so
    /// the prefilter can be re-run. A no-op (valid() stays false) until a
    /// capture has filled the raw cube. Restores the same state capture() does.
    void prefilter();

    /// The prefiltered cube (kBridgeProbeFace, kBridgeProbeMips levels).
    std::uint32_t texture() const { return out_.texture(); }
    /// True once a capture has been prefiltered into texture().
    bool valid() const { return captured_ && out_.valid(); }

private:
    struct SavedState;
    void begin_capture();
    scenegraph::Camera begin_face(int i, glm::vec3 origin);
    void finish_capture();
    void restore_capture_state();
    void run_prefilter();

    CubemapTarget raw_;                       // capture, full mip chain
    CubemapTarget out_;                       // prefiltered, kBridgeProbeMips
    std::unique_ptr<Shader> prefilter_;
    std::uint32_t vao_ = 0;
    std::uint32_t vbo_ = 0;
    bool raw_captured_ = false;               // raw_ holds a complete capture
    bool captured_ = false;                   // out_ is prefiltered from it
    std::unique_ptr<SavedState> saved_;       // live during a capture()
};

/// The split-sum BRDF LUT: kBridgeBrdfLutSize² GL_RG16F, x = NdotV,
/// y = roughness, rg = (A, B) so that specular IBL = prefiltered *
/// (F0 * A + B). Generated lazily by ensure() in the context current at that
/// time, and released by the destructor -- which therefore must run with that
/// same context current (its owner, e.g. the bridge pass, lives inside it).
/// No process-wide cache: a context's object names restart at 1 when a
/// window is recreated, so any handle held past its context is meaningless.
class BrdfLut {
public:
    BrdfLut() = default;
    ~BrdfLut();
    BrdfLut(const BrdfLut&) = delete;
    BrdfLut& operator=(const BrdfLut&) = delete;

    /// Generate the LUT if not yet generated. False without a current GL
    /// context or if the render target is incomplete. Restores GL state.
    bool ensure();
    std::uint32_t texture() const { return tex_; }

private:
    std::uint32_t tex_ = 0;
};

}  // namespace renderer
