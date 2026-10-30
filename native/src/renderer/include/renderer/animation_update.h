#pragma once
#include <cstdint>
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

/// Which non-space passes draw this frame. Bridge = the bridge pass runs (the
/// bridge view); comm = the viewscreen shows a comm feed, of `comm_set_id`
/// (0 = no set filter, as in BridgePass::render).
struct DrawnPasses {
    bool bridge = false;
    bool comm = false;
    std::uint32_t comm_set_id = 0;
};

/// True when `inst` is drawn by a pass that runs this frame, so its palette is
/// worth rebuilding. Space instances always are (no culling here). Bridge and
/// comm instances — the crew and the hail faces — are only drawn in the bridge
/// view, and a comm set only while the viewscreen shows it.
bool pose_this_frame(const scenegraph::Instance& inst, const DrawnPasses& drawn);

/// As above, but only for instances pose_this_frame accepts. A skipped instance
/// keeps its dirty flag and its last palette: channels sample the wall clock,
/// so the first frame it is drawn again poses it exactly as if it had never
/// been skipped.
void update_animations(scenegraph::World& world, const ModelLookup& lookup,
                       double now_wall_time, const DrawnPasses& drawn);
}
