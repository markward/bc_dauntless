#pragma once
#include <functional>
#include <scenegraph/world.h>
namespace assets { struct Model; }
namespace renderer {
/// Per-frame: for every alive instance with animation.clip_index >= 0, sample
/// its model's clip at (now - start) and rebuild bone_palette. Play-once-hold:
/// non-looping clips clamp at duration and set settled=true; a settled
/// non-looping instance is skipped on later frames. Looping clips wrap via fmod
/// and never settle. `lookup` resolves an instance's model_handle to its Model.
using ModelLookup = std::function<const assets::Model*(scenegraph::ModelHandle)>;
void update_animations(scenegraph::World& world, const ModelLookup& lookup,
                       double now_wall_time);
}
