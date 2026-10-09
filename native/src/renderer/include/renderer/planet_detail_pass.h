// native/src/renderer/include/renderer/planet_detail_pass.h
#pragma once

#include <functional>
#include <memory>
#include <optional>
#include <vector>

#include <glm/glm.hpp>

#include <scenegraph/instance.h>

#include "renderer/planet_clipmap_schedule.h"
#include "renderer/planet_detail_noise.h"
#include "renderer/planet_detail_uniforms.h"

// The planet surface-detail driver (spec 2026-10-08 §5.5): once per frame,
// for the MAIN camera only, it picks ONE target planet, anchors the clipmap
// at the camera's nadir (re-anchoring past 0.5·R), schedules strips under a
// fixed cost budget and bakes them, and hands the target's draw its sampling
// uniforms. Every other draw (and every other camera's bake) is untouched.
//
// Everything planet-local is in the planet's BODY frame (rotation and centre
// removed) scaled to GU, exactly opaque.frag's pd_p: a rotating planet keeps
// its detail attached to its surface.
namespace assets { struct Model; }
namespace scenegraph { class World; struct Camera; }

namespace renderer::planet_detail {

class ClipmapAtlas;

struct Candidate {
    scenegraph::InstanceId id;
    glm::vec3 center_ws;
    float radius_gu;
    int bc_tex_w;
};

/// Index of the candidate to detail, or -1. Visible = nadir px per BC texel
/// >= 2: (2*pi*R / bc_tex_w) / max(altitude, 1) * focal_px >= 2. Nearest by
/// surface distance (altitude, floored at 0) wins. Hysteresis: keep
/// `current` (while visible) unless another candidate's surface distance is
/// < 0.9 x current's.
int pick_target(const std::vector<Candidate>& c, const glm::vec3& cam_ws, float focal_px,
                std::optional<scenegraph::InstanceId> current);

class PlanetDetailPass {
public:
    using Lookup = std::function<const assets::Model*(scenegraph::ModelHandle)>;

    PlanetDetailPass();
    ~PlanetDetailPass();
    PlanetDetailPass(const PlanetDetailPass&) = delete;
    PlanetDetailPass& operator=(const PlanetDetailPass&) = delete;

    /// Once per frame, main camera only. Picks the target, (re)anchors,
    /// schedules and bakes under the budget. GL current. With no visible
    /// candidate it does no GL work at all.
    void update(const scenegraph::World& world, const scenegraph::Camera& cam, int viewport_h,
                const Lookup& lookup);

    /// Uniforms for drawing instance `id` (enabled only when id is the target).
    SampleUniforms uniforms_for(scenegraph::InstanceId id) const;
    std::optional<scenegraph::InstanceId> target() const { return target_; }

    void reset();                                   // drop target + clipmap (GL current)
    void set_budget(long long cost_units) { budget_ = cost_units; }   // default 65536*8
    void set_debug(bool on) { debug_ = on; }
    long long last_cost() const { return last_cost_; }

    /// Test/diagnostic: summed area (texels) of every level's valid rect.
    long long debug_valid_area() const;
    /// Test/diagnostic: the atlas texture, 0 when none has been created.
    unsigned debug_atlas_texture() const;

    static constexpr float kTs0Gu = 0.1f;
    static constexpr long long kDefaultBudget = 65536LL * 8;

private:
    void drop_target();   // CPU only: forget target + schedule, keep the atlas

    std::optional<scenegraph::InstanceId> target_;
    // The baked field's identity: a change resets the clipmap.
    int type_ = 0;
    float scale_ = 1.0f;
    std::uint32_t seed_ = 0;
    std::uint32_t shape_ = 0;
    float R_ = 0.0f;
    int levels_ = 0;
    std::vector<int> octaves_;            // one source: bake AND (x2 gas) cost weights
    std::unique_ptr<ClipmapSchedule> schedule_;
    std::unique_ptr<ClipmapAtlas> atlas_;
    bool anchored_ = false;
    Anchor anchor_{};
    scenegraph::Instance::Surface surface_{};
    float scale_local_ = 1.0f;
    long long budget_ = kDefaultBudget;
    bool debug_ = false;
    long long last_cost_ = 0;
};

}  // namespace renderer::planet_detail
