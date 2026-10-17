// native/src/renderer/include/renderer/bridge_probe_array.h
#pragma once

#include <renderer/cubemap_target.h>

#include <scenegraph/camera.h>

#include <glm/glm.hpp>

#include <cstdint>
#include <memory>
#include <vector>

namespace renderer {

class Shader;

/// Every bridge reflection probe (each state's base and its animation
/// layers) in ONE cube-map array, so the bridge shader binds one unit and
/// indexes by layer. Each probe is kBridgeProbeFace², kBridgeProbeMips mips,
/// GL_R11F_G11F_B10F, GGX-prefiltered exactly as BridgeProbe is (mip k =
/// roughness k / (kBridgeProbeMips - 1); mip 0 a copy), with BridgeProbe's
/// face order and orientation (BackdropPass::bake's table).
///
/// A probe is captured in STEPS -- one cube face, the raw mip chain + mip 0,
/// one face of mip 1, or one of mips 2.. -- so no frame pays for a whole probe. The probe in flight is drawn into one
/// shared RGBA16F raw cube and prefiltered into a SPARE array layer; the
/// slot's old content keeps showing until the last step, which swaps the two
/// layers. So a slot's array layer moves: the shader must index by
/// layer_of(slot), re-read after every completed step.
///
/// GL objects are created in the context current at the first ensure() and
/// released by the destructor, which must run with that context current.
class BridgeProbeArray {
public:
    BridgeProbeArray();
    ~BridgeProbeArray();
    BridgeProbeArray(const BridgeProbeArray&) = delete;
    BridgeProbeArray& operator=(const BridgeProbeArray&) = delete;

    /// Make at least `slots` usable slots (plus the spare) exist, creating the
    /// GL objects on first use. Grows by allocating a bigger array and
    /// blitting every existing layer, face and mip into it (valid slots and an
    /// in-flight probe survive); never shrinks. False without a current GL
    /// context or if the array / raw cube cannot be allocated. Restores the
    /// caller's GL state.
    bool ensure(int slots);

    /// Free every slot from `slots` on (slots [0, slots) keep their content;
    /// the array is repacked so slot s sits in layer s). A probe in flight for
    /// a freed slot is abandoned. shrink_to(0) releases the array. No-op if
    /// `slots` >= capacity(). Restores the caller's GL state.
    void shrink_to(int slots);

    /// Usable slots (excludes the spare).
    int capacity() const { return static_cast<int>(layer_of_.size()); }

    /// Start a capture that will land in `slot` (0 <= slot < capacity(),
    /// otherwise ignored) on completion. Replaces any probe already in flight.
    void begin(int slot);

    /// Run ONE step of the probe in flight. Steps 0-5 each render one face of
    /// the raw cube: it is bound (viewport = kBridgeProbeFace², cleared to
    /// opaque black, depth cleared, scissor off) and `draw_face(const
    /// scenegraph::Camera&)` is called with a 90° square camera at `origin`
    /// looking down that face. Then, into the spare layer: one step builds the
    /// raw cube's mip chain and prefilters mip 0 (six faces); six steps
    /// prefilter mip 1 one face each (the costliest mip, ruling R9); one step
    /// each prefilters mips 2.. (six faces). The last swaps the spare in as the slot's layer
    /// and returns true; every other step, and any step with nothing in
    /// flight, returns false. If draw_face throws, that face is retried by the
    /// next step. The caller's FBO, viewport, clear colour, program, VAO,
    /// texture bindings and depth/blend/cull/scissor enables are restored on
    /// every exit.
    template <class DrawFace>
    bool step(glm::vec3 origin, DrawFace draw_face) {
        if (!in_flight()) return false;
        begin_step();
        struct Restore {
            BridgeProbeArray* p;
            ~Restore() { p->end_step(); }
        } restore{this};
        if (step_ < 6) {
            draw_face(begin_face(origin));
            ++step_;   // only once the face is drawn: a throw retries it
            return false;
        }
        return prefilter_step();
    }

    bool in_flight() const { return in_flight_slot_ >= 0; }
    /// The slot the probe in flight will land in; -1 when none.
    int in_flight_slot() const { return in_flight_slot_; }

    /// Drop the probe in flight (e.g. a new room): its slot keeps its layer
    /// and content.
    void abandon();

    /// Steps one probe takes: 6 faces + 1 (mip chain + mip 0) + 6 (mip 1, per
    /// face) + kBridgeProbeMips - 2 (mips 2..) = 17 at 6 mips.
    int steps_per_probe() const;

    /// The GL_TEXTURE_CUBE_MAP_ARRAY (0 before ensure() / after shrink_to(0)).
    std::uint32_t texture() const { return tex_; }
    /// Array (cube) layer currently holding `slot`; -1 out of range.
    int layer_of(int slot) const;
    /// True once a probe has completed into `slot`.
    bool valid(int slot) const;

private:
    struct SavedState;
    void begin_step();
    void end_step();
    scenegraph::Camera begin_face(glm::vec3 origin);
    bool prefilter_step();
    // Allocate an array of `layers` cube layers and blit old layer
    // copy_from[i] into new layer i for each i < copy_from.size().
    bool reallocate(int layers, const std::vector<int>& copy_from);

    CubemapTarget raw_;                       // shared capture scratch
    std::unique_ptr<Shader> prefilter_;
    std::uint32_t tex_ = 0;                   // the cube-map array
    std::uint32_t fbo_ = 0;                   // prefilter target
    std::uint32_t vao_ = 0;
    std::uint32_t vbo_ = 0;
    std::vector<int> layer_of_;               // slot -> cube layer
    std::vector<bool> valid_;                 // slot holds a completed probe
    int spare_layer_ = -1;
    int in_flight_slot_ = -1;
    int step_ = 0;                            // next step of the probe in flight
    std::unique_ptr<SavedState> saved_;       // live during a step()
};

}  // namespace renderer
