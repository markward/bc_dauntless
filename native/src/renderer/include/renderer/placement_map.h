#pragma once
#include <optional>
#include <string>
#include <string_view>

namespace renderer {

struct Placement {
    std::string nif_path;
    bool hidden;
};

/// Resolve a CharacterClass GetLocation() string to its placement-animation
/// NIF and whether the location is a hidden staging spot. nullopt if unknown.
///
/// Data transcribed from BC's `Bridge/Characters/CommonAnimations.SetPosition`
/// (every `GetLocation() == "..."` branch). `hidden` is true iff that branch
/// also calls `pCharacter.SetHidden(1)`.
std::optional<Placement> placement_for_location(std::string_view location);

}  // namespace renderer
