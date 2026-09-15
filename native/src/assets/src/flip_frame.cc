// native/src/assets/src/flip_frame.cc
#include <assets/flip_frame.h>

#include <assets/model.h>
#include <nif/legacy_constants.h>

#include <cmath>

namespace assets {

int compute_flip_frame_index(double t,
                             double start_time,
                             double frequency,
                             double phase,
                             double delta,
                             int    num_sources)
{
    if (num_sources <= 0 || delta <= 0.0) return 0;
    const double local_t = (t - start_time) * frequency + phase;
    const double cycle   = static_cast<double>(num_sources) * delta;
    double m = std::fmod(local_t, cycle);
    if (m < 0.0) m += cycle;
    // Bias toward the next frame by a small epsilon — matches BC's
    // runtime fudge that prevents float drift from holding a frame
    // index back by one tick when m / delta lands just shy of an
    // integer (e.g. 1/6 * 7 / (1/6) = 6.9999...).
    int frame = static_cast<int>(m / delta + nif::legacy::kFlipControllerIndexFudge);
    if (frame < 0)             frame = 0;
    if (frame >= num_sources)  frame = frame % num_sources;
    return frame;
}

int animated_base_texture(const Model& model, const Material& mat, double t)
{
    const int base_tex = mat.stages[
        static_cast<std::size_t>(Material::StageSlot::Base)
    ].texture_index;
    if (mat.animation_index < 0 ||
        mat.animation_index >= static_cast<int>(model.texture_animations.size()))
        return base_tex;
    const auto& anim = model.texture_animations[mat.animation_index];
    if (anim.texture_indices.empty()) return base_tex;
    const int frame = compute_flip_frame_index(
        t, anim.start_time, anim.frequency, anim.phase, anim.delta,
        static_cast<int>(anim.texture_indices.size()));
    return anim.texture_indices[frame];
}

}  // namespace assets
