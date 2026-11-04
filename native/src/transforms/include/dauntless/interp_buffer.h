#pragma once

#include <cstdint>
#include <unordered_map>

#include "dauntless/transform_store.h"

namespace dauntless {

// A set-local pose: position plus row-major rotation (column c = body axis c,
// column 1 forward), the transform store's own layout.
using Pose = TransformStore::Transform;

// engine/core/interpolate.py:lerp_transform's twin, operation for operation:
// lerp_point, then nlerp_rotation (blend the columns, forward primary,
// Gram-Schmidt up, right = forward x up, the same 1e-9 eps and fallbacks:
// endpoint column cur then prev, then the defaults, then _any_perpendicular).
// Compiled with -ffp-contract=off so it rounds exactly as CPython does
// (tests/host/test_native_interp_twin.py pins it at 1e-12).
Pose lerp_pose(const Pose& prev, const Pose& cur, double alpha);

// engine/core/transform_buffer.py:TransformBuffer's twin: the last two
// snapshots of each key, sampled at lerp(prev, cur, alpha).
class InterpBuffer {
public:
    using Key = std::uint64_t;  // (index << 32) | generation

    bool has(Key k) const;
    // prev = cur, every key (start of a tick batch).
    void roll();
    // cur = p; prev = p as well for a key not yet tracked (no first-frame smear).
    void capture(Key k, const Pose& p);
    // Re-seat prev for a tracked key; an untracked key is ignored.
    void set_previous(Key k, const Pose& p);
    // prev = cur = p: a discontinuity for this one key.
    void snap(Key k, const Pose& p);
    void erase(Key k);
    void clear();
    // lerp(prev, cur, alpha) into `out`; false (out untouched) for an unknown key.
    bool sample(Key k, double alpha, Pose& out) const;

private:
    struct Entry {
        Pose prev;
        Pose cur;
    };
    std::unordered_map<Key, Entry> entries_;
};

// engine/core/handover_smoother.py:HandoverSmoother's twin: blend from a
// frozen pose to the true one over kHandoverSeconds, smoothstep-eased.
inline constexpr double kHandoverSeconds = 0.36;

struct HandoverBlend {
    // True while a handover is still being eased out.
    bool active() const;
    // Freeze `frozen` and restart the window (re-freezes when already active).
    void begin(const Pose& frozen);
    // Move the window on by dt; nothing without a frozen pose.
    void advance(double dt);
    // Drop the frozen pose (scene discontinuity).
    void cancel();
    // The pose to draw: `truth` itself when inactive.
    Pose blend(const Pose& truth) const;

private:
    bool has_frozen_ = false;
    Pose frozen_{};
    double elapsed_ = 0.0;
};

}  // namespace dauntless
