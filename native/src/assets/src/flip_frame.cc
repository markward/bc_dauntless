// native/src/assets/src/flip_frame.cc
#include <assets/flip_frame.h>

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

}  // namespace assets
