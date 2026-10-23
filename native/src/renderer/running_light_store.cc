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

// Appends one entry's sprites. Returns false once the sprite cap is reached.
bool RunningLightStore::append_sprites(
        std::vector<RunningLightSprite>& out, const Entry& e, float level,
        const scenegraph::World& world, float game_time, const RunningLightDials& dials,
        const glm::vec3& cam_eye, float proj11, int viewport_h) {
    static bool warned_cap = false;
    if (level <= 0.0f) return true;
    // By id, NOT for_each_visible_in_pass: a cloaking hull is
    // set_visible(false) while its lights must still fade out.
    const scenegraph::Instance* inst = world.get(e.id);
    if (inst == nullptr) return true;
    const glm::mat4& M = inst->world;
    const glm::mat3 RS = glm::mat3(M);
    const float s = std::max(glm::length(glm::vec3(M[0])), 1e-6f);
    const glm::vec3 t = glm::vec3(M[3]);
    for (const auto& l : e.lights) {
        const float a = level *
            running_light_blink_alpha(game_time, l.period, l.duration, e.phase);
        if (a <= 0.0f) continue;
        if (out.size() >= kMaxRunningLightSprites) {
            if (!warned_cap) {
                std::fprintf(stderr, "[running_lights] sprite cap %zu reached; "
                             "extra lights skipped\n", kMaxRunningLightSprites);
                warned_cap = true;
            }
            return false;
        }
        RunningLightSprite sp;
        sp.world_pos = t + (RS * l.body_pos) / s;
        const float dist = glm::length(sp.world_pos - cam_eye);
        const float drawn = running_light_world_size(
            l.size, dials.size_gu_per_radius, dials.min_px, dist, proj11, viewport_h);
        sp.half_size = 0.5f * drawn;
        // Once the min_px floor wins the sprite stops shrinking on screen;
        // dim it by the area it was blown up by, so its energy keeps
        // falling as 1/d^2 instead of every light looking the same at
        // any range.
        const float true_size = std::max(0.0f, l.size) * dials.size_gu_per_radius;
        const float k = drawn > true_size ? true_size / drawn : 1.0f;
        sp.color = l.rgb * (dials.intensity * a * k * k);
        out.push_back(sp);
    }
    return true;
}

std::vector<RunningLightSprite> RunningLightStore::build_sprites(
        const scenegraph::World& world, float game_time, const RunningLightDials& dials,
        const glm::vec3& cam_eye, float proj11, int viewport_h) const {
    std::vector<RunningLightSprite> out;
    for (const auto& e : entries_)
        if (!append_sprites(out, e, e.level, world, game_time, dials, cam_eye, proj11,
                            viewport_h))
            break;
    return out;
}

std::vector<RunningLightSprite> RunningLightStore::build_sprites_for(
        scenegraph::InstanceId id, const scenegraph::World& world, float time,
        const RunningLightDials& dials, const glm::vec3& cam_eye, float proj11,
        int viewport_h, float level_override) const {
    std::vector<RunningLightSprite> out;
    // Same NaN rule as set_levels: anything not > 0 is dark.
    const float level = (level_override > 0.0f) ? std::min(level_override, 1.0f) : 0.0f;
    for (const auto& e : entries_)
        if (e.id == id) {
            append_sprites(out, e, level, world, time, dials, cam_eye, proj11, viewport_h);
            break;
        }
    return out;
}

}  // namespace renderer
