// native/src/renderer/running_light_store.cc
#include "renderer/running_light_store.h"

#include "renderer/running_light_math.h"

#include <algorithm>
#include <cstdio>

namespace renderer {

void RunningLightStore::set(scenegraph::InstanceId id, std::vector<RunningLight> lights,
                            float phase) {
    if (lights.empty()) { erase(id); return; }
    for (auto& e : entries_) {
        if (e.id == id) { e.lights = std::move(lights); e.phase = phase; return; }
    }
    entries_.push_back(Entry{id, std::move(lights), phase, 0.0f});
}

void RunningLightStore::set_levels(
        const std::vector<std::pair<scenegraph::InstanceId, float>>& levels) {
    for (auto& e : entries_) e.level = 0.0f;   // unlisted this frame => dark
    for (const auto& [id, level] : levels)
        for (auto& e : entries_)
            // Not std::clamp: it passes NaN through, and a NaN level would
            // survive build_sprites' "level <= 0" skip. Anything not > 0 is dark.
            if (e.id == id) e.level = (level > 0.0f) ? std::min(level, 1.0f) : 0.0f;
}

void RunningLightStore::erase(scenegraph::InstanceId id) {
    entries_.erase(std::remove_if(entries_.begin(), entries_.end(),
                                  [&](const Entry& e) { return e.id == id; }),
                   entries_.end());
}

void RunningLightStore::clear() { entries_.clear(); }

std::size_t RunningLightStore::size() const noexcept { return entries_.size(); }

float RunningLightStore::level(scenegraph::InstanceId id) const noexcept {
    for (const auto& e : entries_) if (e.id == id) return e.level;
    return 0.0f;
}

std::vector<RunningLightSprite> RunningLightStore::build_sprites(
        const scenegraph::World& world, float game_time, const RunningLightDials& dials,
        const glm::vec3& cam_eye, float proj11, int viewport_h) const {
    std::vector<RunningLightSprite> out;
    static bool warned_cap = false;
    for (const auto& e : entries_) {
        if (e.level <= 0.0f) continue;
        // By id, NOT for_each_visible_in_pass: a cloaking hull is
        // set_visible(false) while its lights must still fade out.
        const scenegraph::Instance* inst = world.get(e.id);
        if (inst == nullptr) continue;
        const glm::mat4& M = inst->world;
        const glm::mat3 RS = glm::mat3(M);
        const float s = std::max(glm::length(glm::vec3(M[0])), 1e-6f);
        const glm::vec3 t = glm::vec3(M[3]);
        for (const auto& l : e.lights) {
            const float a = e.level *
                running_light_blink_alpha(game_time, l.period, l.duration, e.phase);
            if (a <= 0.0f) continue;
            if (out.size() >= kMaxRunningLightSprites) {
                if (!warned_cap) {
                    std::fprintf(stderr, "[running_lights] sprite cap %zu reached; "
                                 "extra lights skipped\n", kMaxRunningLightSprites);
                    warned_cap = true;
                }
                return out;
            }
            RunningLightSprite sp;
            sp.world_pos = t + (RS * l.body_pos) / s;
            const float dist = glm::length(sp.world_pos - cam_eye);
            sp.half_size = 0.5f * running_light_world_size(
                l.size, dials.size_gu_per_radius, dials.min_px, dist, proj11, viewport_h);
            sp.color = l.rgb * (dials.intensity * a);
            out.push_back(sp);
        }
    }
    return out;
}

}  // namespace renderer
