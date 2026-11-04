#pragma once

#include <cstdint>
#include <span>
#include <vector>

#include "dauntless/combat/mirror.h"
#include "dauntless/transform_store.h"

// The published-pose buffer (native motion phase 2, Task 6): at the end of
// each motion stage every ship row's pose and velocity is copied here, tagged
// with the stage's tick number, so later phases (render, hit tests, combat)
// can read the poses motion published for the tick. Nothing reads it in play
// yet. Each publish REPLACES the contents. Main thread only, GIL held (a
// short copy; the mirror is not written).
namespace dauntless::combat {

struct PublishedPose {
    int64_t object;   // the mirror's Object handle
    double pos[3];
    double rot[9];    // row-major, the store's layout
    double vel[3];    // the row's _velocity
};

class PublishedPoses {
public:
    // Replace the contents with `objects`' poses, tagged `tick`. Skips -1, a
    // stale or non-Object handle, and an invalid transform.
    void publish(const Mirror& m, const dauntless::TransformStore& store,
                 const std::vector<int64_t>& objects, int64_t tick);
    int64_t tick() const { return tick_; }
    const PublishedPose* find(int64_t object) const;
    std::span<const PublishedPose> all() const { return poses_; }
    void clear();

private:
    int64_t tick_ = 0;
    std::vector<PublishedPose> poses_;
};

PublishedPoses& published_poses();  // process-wide

}  // namespace dauntless::combat
