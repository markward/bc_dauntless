// native/src/assets/include/assets/flip_frame.h
#pragma once

namespace assets {

/// Compute the active frame index for a looping NiFlipController-style
/// animation at wall time `t`. Mirrors BC's runtime semantics for a
/// looping flip controller:
///
///   local_t = (t - start_time) * frequency + phase
///   raw     = floor(local_t / delta)
///   frame   = ((raw % num_sources) + num_sources) % num_sources
///
/// Defensive returns 0 when num_sources <= 0 or delta <= 0.
int compute_flip_frame_index(double t,
                             double start_time,
                             double frequency,
                             double phase,
                             double delta,
                             int    num_sources);

}  // namespace assets
