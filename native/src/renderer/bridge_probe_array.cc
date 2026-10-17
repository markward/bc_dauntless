// native/src/renderer/bridge_probe_array.cc
#include "renderer/bridge_probe_array.h"
#include "renderer/bridge_lighting_tuning.h"
#include "renderer/shader.h"
#include "probe_capture_gl.h"

#include "embedded_probe_prefilter_vs.h"
#include "embedded_probe_prefilter_fs.h"

#include <glad/glad.h>

#include <numeric>
#include <utility>

namespace renderer {

namespace {

// The prefiltered probes need no alpha and are never negative: 4 B/texel,
// half of RGBA16F (spec §4.6).
constexpr GLenum kProbeFormat = GL_R11F_G11F_B10F;

void attach_layer(GLenum target, GLuint tex, int mip, int cube_layer, int face) {
    glFramebufferTextureLayer(target, GL_COLOR_ATTACHMENT0, tex, mip, cube_layer * 6 + face);
}

}  // namespace

struct BridgeProbeArray::SavedState { probe_gl::GlState gl; };

BridgeProbeArray::BridgeProbeArray() = default;

BridgeProbeArray::~BridgeProbeArray() {
    // raw_ releases its own cube, depth and FBO; prefilter_ its program.
    if (tex_) { GLuint t = tex_; glDeleteTextures(1, &t); }
    if (fbo_) { GLuint f = fbo_; glDeleteFramebuffers(1, &f); }
    if (vbo_) { GLuint b = vbo_; glDeleteBuffers(1, &b); }
    if (vao_) { GLuint v = vao_; glDeleteVertexArrays(1, &v); }
}

bool BridgeProbeArray::ensure(int slots) {
    if (slots < 0) slots = 0;
    if (tex_ && prefilter_ && raw_.valid() && slots <= capacity()) return true;
    if (!probe_gl::have_context()) return false;
    probe_gl::GlState s;
    s.save();
    // Allocation binds on the ACTIVE unit: use unit 0, which the saved state
    // restores, so the caller's unit N keeps its binding.
    glActiveTexture(GL_TEXTURE0);
    // The shared raw capture: one allocated level, its chain built by
    // generate_mips() before each probe's prefilter (pdf-driven sample level).
    bool ok = raw_.allocate(kBridgeProbeFace);
    if (ok && !prefilter_) {
        prefilter_ = std::make_unique<Shader>(shader_src::probe_prefilter_vs,
                                              shader_src::probe_prefilter_fs);
    }
    if (ok && !vao_) {
        GLuint vao = 0, vbo = 0;
        probe_gl::make_triangle(vao, vbo);
        vao_ = vao;
        vbo_ = vbo;
    }
    if (ok && !fbo_) {
        GLuint f = 0;
        glGenFramebuffers(1, &f);
        fbo_ = f;
    }
    if (ok && (tex_ == 0 || slots > capacity())) {
        // Existing layers keep their indices (so layer_of_ and the spare stay
        // put, and a probe in flight survives); the new slots take the new
        // layers at the end.
        const int old_layers = tex_ ? capacity() + 1 : 0;
        std::vector<int> copy_from(static_cast<size_t>(old_layers));
        std::iota(copy_from.begin(), copy_from.end(), 0);
        const int want = std::max(slots, capacity());
        ok = reallocate(want + 1, copy_from);
        if (ok) {
            int next = old_layers;
            for (int slot = capacity(); slot < want; ++slot) {
                layer_of_.push_back(next++);
                valid_.push_back(false);
            }
            if (spare_layer_ < 0) spare_layer_ = next;
        }
    }
    s.restore();
    return ok;
}

void BridgeProbeArray::shrink_to(int slots) {
    if (slots < 0) slots = 0;
    if (slots >= capacity()) return;
    if (in_flight_slot_ >= slots) abandon();
    if (!probe_gl::have_context()) return;
    if (slots == 0) {
        // Nothing left to keep, and nothing in flight (abandoned above).
        GLuint t = tex_;
        glDeleteTextures(1, &t);
        tex_ = 0;
        layer_of_.clear();
        valid_.clear();
        spare_layer_ = -1;
        return;
    }
    probe_gl::GlState s;
    s.save();
    glActiveTexture(GL_TEXTURE0);
    // Repack: slot i -> layer i, the spare (it may hold a probe in flight)
    // after them.
    std::vector<int> copy_from(layer_of_.begin(), layer_of_.begin() + slots);
    copy_from.push_back(spare_layer_);
    if (reallocate(slots + 1, copy_from)) {
        layer_of_.resize(static_cast<size_t>(slots));
        std::iota(layer_of_.begin(), layer_of_.end(), 0);
        valid_.resize(static_cast<size_t>(slots));
        spare_layer_ = slots;
    }
    s.restore();
}

bool BridgeProbeArray::reallocate(int layers, const std::vector<int>& copy_from) {
    GLuint tex = 0;
    glGenTextures(1, &tex);
    glBindTexture(GL_TEXTURE_CUBE_MAP_ARRAY, tex);
    for (int mip = 0; mip < kBridgeProbeMips; ++mip) {
        const int sz = probe_gl::mip_size(mip);
        glTexImage3D(GL_TEXTURE_CUBE_MAP_ARRAY, mip, static_cast<GLint>(kProbeFormat),
                     sz, sz, layers * 6, 0, GL_RGB, GL_FLOAT, nullptr);
    }
    glTexParameteri(GL_TEXTURE_CUBE_MAP_ARRAY, GL_TEXTURE_BASE_LEVEL, 0);
    glTexParameteri(GL_TEXTURE_CUBE_MAP_ARRAY, GL_TEXTURE_MAX_LEVEL, kBridgeProbeMips - 1);
    glTexParameteri(GL_TEXTURE_CUBE_MAP_ARRAY, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR);
    glTexParameteri(GL_TEXTURE_CUBE_MAP_ARRAY, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_CUBE_MAP_ARRAY, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_CUBE_MAP_ARRAY, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_CUBE_MAP_ARRAY, GL_TEXTURE_WRAP_R, GL_CLAMP_TO_EDGE);

    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, fbo_);
    attach_layer(GL_DRAW_FRAMEBUFFER, tex, 0, 0, 0);
    const bool ok =
        glCheckFramebufferStatus(GL_DRAW_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
    if (ok && tex_ && !copy_from.empty()) {
        // No glCopyImageSubData on GL 4.1: one blit per (layer, face, mip).
        probe_gl::full_screen_state();   // a blit honours the scissor test
        GLuint read = 0;
        glGenFramebuffers(1, &read);
        glBindFramebuffer(GL_READ_FRAMEBUFFER, read);
        for (size_t to = 0; to < copy_from.size(); ++to) {
            for (int face = 0; face < 6; ++face) {
                for (int mip = 0; mip < kBridgeProbeMips; ++mip) {
                    const int sz = probe_gl::mip_size(mip);
                    attach_layer(GL_READ_FRAMEBUFFER, tex_, mip, copy_from[to], face);
                    attach_layer(GL_DRAW_FRAMEBUFFER, tex, mip, static_cast<int>(to), face);
                    glBlitFramebuffer(0, 0, sz, sz, 0, 0, sz, sz,
                                      GL_COLOR_BUFFER_BIT, GL_NEAREST);
                }
            }
        }
        glBindFramebuffer(GL_READ_FRAMEBUFFER, 0);
        glDeleteFramebuffers(1, &read);
    }
    glFramebufferTexture(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, 0, 0);
    if (!ok) {
        glDeleteTextures(1, &tex);
        return false;
    }
    if (tex_) { GLuint old = tex_; glDeleteTextures(1, &old); }
    tex_ = tex;
    return true;
}

void BridgeProbeArray::begin(int slot) {
    if (slot < 0 || slot >= capacity()) return;
    in_flight_slot_ = slot;
    step_ = 0;
}

void BridgeProbeArray::abandon() {
    in_flight_slot_ = -1;
    step_ = 0;
}

int BridgeProbeArray::steps_per_probe() const {
    // Faces, the raw chain + mip 0, mip 1 per face, the remaining mips.
    return 6 + 1 + 6 + (kBridgeProbeMips - 2);
}

int BridgeProbeArray::layer_of(int slot) const {
    if (slot < 0 || slot >= capacity()) return -1;
    return layer_of_[static_cast<size_t>(slot)];
}

bool BridgeProbeArray::valid(int slot) const {
    if (slot < 0 || slot >= capacity()) return false;
    return valid_[static_cast<size_t>(slot)];
}

void BridgeProbeArray::begin_step() {
    saved_ = std::make_unique<SavedState>();
    saved_->gl.save();
    glEnable(GL_TEXTURE_CUBE_MAP_SEAMLESS);   // as BridgeProbe; left on
}

void BridgeProbeArray::end_step() {
    if (saved_) saved_->gl.restore();
    saved_.reset();
}

scenegraph::Camera BridgeProbeArray::begin_face(glm::vec3 origin) {
    raw_.bind_face(step_);
    glDisable(GL_SCISSOR_TEST);   // the clear must cover the whole face
    return probe_gl::clear_face_and_camera(step_, origin);
}

bool BridgeProbeArray::prefilter_step() {
    // Steps after the faces: [6] the raw chain + mip 0, [7, 13) mip 1 one
    // face each (the costliest mip by far, ruling R9), then mips 2.. whole.
    const int p = step_ - 6;
    const int mip = p == 0 ? 0 : (p <= 6 ? 1 : p - 5);
    if (mip == 0) {
        // All six faces are in: the raw chain for the pdf-driven sample level.
        glActiveTexture(GL_TEXTURE0);
        raw_.generate_mips();
    }
    probe_gl::begin_prefilter(*prefilter_, raw_.texture(), vao_);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo_);
    const int sz = probe_gl::mip_size(mip);
    const auto bind = [&](int face) {
        attach_layer(GL_FRAMEBUFFER, tex_, mip, spare_layer_, face);
        glViewport(0, 0, sz, sz);
    };
    if (mip == 1) probe_gl::prefilter_face(*prefilter_, mip, p - 1, bind);
    else probe_gl::prefilter_mip(*prefilter_, mip, bind);
    glFramebufferTexture(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, 0, 0);
    ++step_;
    if (step_ < steps_per_probe()) return false;
    // Complete: the spare becomes the slot's layer, its old layer the spare.
    std::swap(layer_of_[static_cast<size_t>(in_flight_slot_)], spare_layer_);
    valid_[static_cast<size_t>(in_flight_slot_)] = true;
    abandon();
    return true;
}

}  // namespace renderer
