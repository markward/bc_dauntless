#include "renderer/animation_update.h"
#include "renderer/bone_palette.h"
#include "renderer/channel_binder.h"
#include <assets/model.h>

namespace renderer {

void update_animations(scenegraph::World& world, const ModelLookup& lookup,
                       double now_wall_time) {
    world.for_each_alive([&](scenegraph::Instance& inst) {
        // Settled instances are skipped — UNLESS a jaw is active. A speaking
        // officer standing idle at their station is settled (not dirty), so we
        // MUST re-pose them every frame or bridge_pass would draw the stale
        // cached palette and the mouth would never move (or stay stuck open).
        if (!inst.anim.dirty && !inst.jaw_active) return;
        // Nothing bound and no rest pose ⇒ not a skeletal-animated instance —
        // except a jaw-active officer, whom we still re-pose (eval_channels
        // falls back to bind locals) so the jaw drive has a palette to write.
        if (inst.anim.channels.empty() && !inst.anim.has_rest && !inst.jaw_active)
            return;
        const assets::Model* m = lookup(inst.model_handle);
        if (!m || m->skeleton.bones.empty()) return;
        std::vector<glm::mat4> locals = eval_channels(inst, *m, now_wall_time);
        // Drive the mouth: compose the openness-scaled jaw rotation onto
        // "Bip01 Ponytail1" before the palette is built. openness==0 is an
        // identity rotation (REST), so re-posing a settled jaw relaxes it shut.
        if (inst.jaw_active)
            apply_jaw_rotation(*m, locals, inst.jaw_openness);
        inst.bone_palette = build_bone_palette(m->skeleton, &locals);
    });
}

}  // namespace renderer
