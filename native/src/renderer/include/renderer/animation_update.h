#pragma once
#include <functional>
#include <scenegraph/world.h>
namespace assets { struct Model; }
namespace renderer {
/// Per-frame: for every alive instance whose per-bone channel table is dirty,
/// call eval_channels (which samples each bone's current BoneChannel at now and
/// clears anim.dirty when all channels have settled) and rebuild bone_palette.
/// Settled instances (anim.dirty == false) and instances with no channels and
/// no rest pose are skipped. `lookup` resolves an instance's model_handle to its
/// Model.
using ModelLookup = std::function<const assets::Model*(scenegraph::ModelHandle)>;
void update_animations(scenegraph::World& world, const ModelLookup& lookup,
                       double now_wall_time);
}
