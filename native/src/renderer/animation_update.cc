#include "renderer/animation_update.h"
#include "renderer/bone_palette.h"
#include "renderer/pose_sampler.h"
#include <assets/model.h>
#include <cmath>

namespace renderer {

void update_animations(scenegraph::World& world, const ModelLookup& lookup,
                       double now_wall_time) {
    world.for_each_alive([&](scenegraph::Instance& inst) {
        auto& a = inst.animation;
        if (a.clip_index < 0) return;
        if (a.settled && !a.loop) return;            // frozen after hold
        const assets::Model* m = lookup(inst.model_handle);
        if (!m || a.clip_index >= static_cast<int>(m->animations.size())) return;
        const assets::AnimationClip& clip = m->animations[a.clip_index];
        const float dur = clip.duration_seconds;
        double elapsed = now_wall_time - a.start_wall_time;
        if (elapsed < 0.0) elapsed = 0.0;
        float t;
        if (a.loop) {
            t = dur > 0.0f ? static_cast<float>(std::fmod(elapsed, dur)) : 0.0f;
        } else if (elapsed >= dur) {
            t = dur;
            a.settled = true;                        // last rebuild, then freeze
        } else {
            t = static_cast<float>(elapsed);
        }
        std::vector<glm::mat4> pose = sample_pose(clip, m->skeleton, t);
        inst.bone_palette = build_bone_palette(m->skeleton, &pose);
    });
}

}  // namespace renderer
