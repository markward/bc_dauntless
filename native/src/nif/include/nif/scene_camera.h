// native/src/nif/include/nif/scene_camera.h
//
// Extract the first NiCamera from a parsed set NIF and compose its world
// transform from the parent NiNode chain. Used by the host's
// parse_set_camera binding to feed MissionLib.SetupBridgeSet's embedded-
// camera path. Pure: no GL, no asset cache.
#pragma once

#include <nif/file.h>

#include <array>
#include <optional>

namespace nif {

struct SetCamera {
    std::array<float, 3> position{0, 0, 0};   // world translation, model frame
    std::array<float, 9> rotation{1, 0, 0, 0, 1, 0, 0, 0, 1};  // row-major
    std::array<float, 4> frustum{0, 0, 0, 0}; // left, right, top, bottom
    float near_distance = 0.0f;
    float far_distance = 0.0f;
};

/// First NiCamera in the file with its world transform composed from the
/// root down its parent NiNode chain, or nullopt if the file has no camera.
std::optional<SetCamera> find_first_camera(const File& f);

}  // namespace nif
