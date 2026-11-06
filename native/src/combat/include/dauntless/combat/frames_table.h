#pragma once

#include <cstdint>
#include <unordered_map>

#include "dauntless/combat/mirror.h"

// The frames table the native render feeds read (beam_feed.h,
// torpedo_feed.h): engine/systems/frames.py's frame_of for every registered
// Set, sent per frame by native_combat._beam_frames.

namespace dauntless::combat {

// frames.frame_of(set): the frame's key as a small id (two sets share a
// frame exactly when their ids are equal) and its anchor_gu.
struct BeamFrame {
    int64_t id;
    Vec3 anchor;
};

// Set handle -> its frame.
using FrameTable = std::unordered_map<int64_t, BeamFrame>;

}  // namespace dauntless::combat
