// native/src/renderer/include/renderer/running_light_store.h
// Per-ship running lights: body-frame emitters resolved against the hull's own
// world matrix each frame (same rule as resolve_attached_dynamic_lights).
#pragma once

#include <cstddef>
#include <utility>
#include <vector>

#include <glm/glm.hpp>
#include <scenegraph/world.h>

namespace renderer {

struct RunningLight { glm::vec3 body_pos{0}; glm::vec3 rgb{1}; float size = 0.1f, period = 3.0f, duration = 1.0f; };
// Spec §4.5 start values; mirrored by engine/appc/running_light_dials.py DEFAULTS.
struct RunningLightDials { float size_gu_per_radius = 0.02f, min_px = 2.5f, intensity = 4.0f; };
struct RunningLightSprite { glm::vec3 world_pos{0}; float half_size = 0.0f; glm::vec3 color{0}; };
constexpr std::size_t kMaxRunningLightSprites = 4096;

class RunningLightStore {
public:
    void set(scenegraph::InstanceId id, std::vector<RunningLight> lights, float phase); // empty => erase
    void set_levels(const std::vector<std::pair<scenegraph::InstanceId, float>>& levels);
    void erase(scenegraph::InstanceId id);
    void clear();
    std::size_t size() const noexcept;
    float level(scenegraph::InstanceId id) const noexcept;   // 0 when absent or unlisted
    std::vector<RunningLightSprite> build_sprites(const scenegraph::World& world, float game_time,
        const RunningLightDials& dials, const glm::vec3& cam_eye, float proj11, int viewport_h) const;
    // One instance only, with `level_override` in place of the stored level
    // (the Ship Property Viewer's frozen sim never pushes levels).
    std::vector<RunningLightSprite> build_sprites_for(scenegraph::InstanceId id,
        const scenegraph::World& world, float time, const RunningLightDials& dials,
        const glm::vec3& cam_eye, float proj11, int viewport_h, float level_override) const;

private:
    struct Entry {
        scenegraph::InstanceId id;
        std::vector<RunningLight> lights;
        float phase = 0.0f;
        float level = 0.0f;
    };
    static bool append_sprites(std::vector<RunningLightSprite>& out, const Entry& e,
        float level, const scenegraph::World& world, float game_time,
        const RunningLightDials& dials, const glm::vec3& cam_eye, float proj11,
        int viewport_h);
    std::vector<Entry> entries_;
};

}  // namespace renderer
