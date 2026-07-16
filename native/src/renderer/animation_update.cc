#include "renderer/animation_update.h"
#include "renderer/bone_palette.h"
#include "renderer/channel_binder.h"
#include <assets/model.h>

namespace renderer {

void update_animations(scenegraph::World& world, const ModelLookup& lookup,
                       double now_wall_time) {
    world.for_each_alive([&](scenegraph::Instance& inst) {
        // Nothing bound and no rest pose ⇒ not a skeletal-animated instance.
        if (!inst.anim.dirty) return;                    // settled: skip
        if (inst.anim.channels.empty() && !inst.anim.has_rest) return;
        const assets::Model* m = lookup(inst.model_handle);
        if (!m || m->skeleton.bones.empty()) return;
        std::vector<glm::mat4> locals = eval_channels(inst, *m, now_wall_time);
        inst.bone_palette = build_bone_palette(m->skeleton, &locals);
    });
}

}  // namespace renderer
