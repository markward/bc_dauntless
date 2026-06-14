// native/src/renderer/include/renderer/placement_map.h
#pragma once
#include <optional>
#include <string>
#include <string_view>

namespace renderer {

struct Placement {
    std::string nif_path;
    bool hidden = false;
    /// True when the clip is a "station-to-staging" MOVEMENT clip (e.g.
    /// db_StoL1_S = "Science to L1"): the officer is AT the station at the
    /// clip START (t=0), and walks away by the end. Static placement must
    /// sample t=0, not t=duration. "stand" clips leave this false (settled
    /// standing pose is at t=duration).
    bool sample_at_start = false;
};

/// Resolve a CharacterClass GetLocation() string to its placement-animation
/// NIF and whether the location is a hidden staging spot. nullopt if unknown.
///
/// Data transcribed from BC's `Bridge/Characters/CommonAnimations.SetPosition`
/// (every `GetLocation() == "..."` branch). `hidden` is true iff that branch
/// also calls `pCharacter.SetHidden(1)`.
std::optional<Placement> placement_for_location(std::string_view location);

}  // namespace renderer
