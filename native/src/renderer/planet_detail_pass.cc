// native/src/renderer/planet_detail_pass.cc
#include "renderer/planet_detail_pass.h"

#include "renderer/planet_clipmap_atlas.h"

#include <assets/model.h>

#include <scenegraph/camera.h>
#include <scenegraph/world.h>

#include <algorithm>
#include <cmath>

namespace renderer::planet_detail {

namespace {

constexpr float kTwoPi = 6.28318530718f;
constexpr int kDefaultBcTexW = 256;
constexpr float kMinVisiblePxPerTexel = 2.0f;   // spec §5.5
constexpr float kHysteresis = 0.9f;             // switch only when >= 10% nearer

float altitude(const Candidate& c, const glm::vec3& cam_ws) {
    return glm::length(cam_ws - c.center_ws) - c.radius_gu;
}

bool visible(const Candidate& c, const glm::vec3& cam_ws, float focal_px) {
    const int w = c.bc_tex_w > 0 ? c.bc_tex_w : kDefaultBcTexW;
    const float texel_gu = kTwoPi * c.radius_gu / static_cast<float>(w);
    return texel_gu / std::max(altitude(c, cam_ws), 1.0f) * focal_px >= kMinVisiblePxPerTexel;
}

// Width of the sphere mesh's base texture: one BC texel's span on the surface.
int bc_texture_width(const assets::Model& m) {
    const int mi = m.sphere_map->mesh_index;
    if (mi < 0 || mi >= static_cast<int>(m.meshes.size())) return kDefaultBcTexW;
    const int mat = m.meshes[static_cast<std::size_t>(mi)].material_index();
    if (mat < 0 || mat >= static_cast<int>(m.materials.size())) return kDefaultBcTexW;
    const int ti = m.materials[static_cast<std::size_t>(mat)]
                       .stages[static_cast<std::size_t>(assets::Material::StageSlot::Base)]
                       .texture_index;
    if (ti < 0 || ti >= static_cast<int>(m.textures.size())) return kDefaultBcTexW;
    const auto w = m.textures[static_cast<std::size_t>(ti)].width();
    return w > 0 ? static_cast<int>(w) : kDefaultBcTexW;
}

}  // namespace

int pick_target(const std::vector<Candidate>& c, const glm::vec3& cam_ws, float focal_px,
                std::optional<scenegraph::InstanceId> current) {
    int best = -1;
    float best_d = 0.0f;
    int cur = -1;
    for (int i = 0; i < static_cast<int>(c.size()); ++i) {
        const Candidate& k = c[static_cast<std::size_t>(i)];
        if (!visible(k, cam_ws, focal_px)) continue;
        const float d = std::max(altitude(k, cam_ws), 0.0f);
        if (current && k.id == *current) cur = i;
        if (best < 0 || d < best_d) {
            best = i;
            best_d = d;
        }
    }
    if (cur >= 0 && best != cur) {
        const float cur_d = std::max(altitude(c[static_cast<std::size_t>(cur)], cam_ws), 0.0f);
        if (!(best_d < kHysteresis * cur_d)) return cur;
    }
    return best;
}

PlanetDetailPass::PlanetDetailPass() = default;
PlanetDetailPass::~PlanetDetailPass() = default;

void PlanetDetailPass::drop_target() {
    target_.reset();
    schedule_.reset();
    anchored_ = false;
    levels_ = 0;
    octaves_.clear();
}

void PlanetDetailPass::reset() {
    drop_target();
    atlas_.reset();
    last_cost_ = 0;
}

void PlanetDetailPass::update(const scenegraph::World& world, const scenegraph::Camera& cam,
                              int viewport_h, const Lookup& lookup) {
    last_cost_ = 0;

    // Candidates: visible Space-pass surface planets with a sphere map.
    std::vector<Candidate> cands;
    world.for_each_visible_in_pass(scenegraph::Pass::Space, [&](const scenegraph::Instance& inst) {
        if (inst.surface.type == 0) return;
        const assets::Model* m = lookup(inst.model_handle);
        if (m == nullptr || !m->sphere_map) return;
        const glm::vec3 c = glm::vec3(inst.world * glm::vec4(m->sphere_map->center_body, 1.0f));
        const float R = m->sphere_map->radius * glm::length(glm::vec3(inst.world[0]));
        cands.push_back(Candidate{inst.id, c, R, bc_texture_width(*m)});
    });

    const float focal_px = cam.proj_matrix()[1][1] * static_cast<float>(viewport_h) * 0.5f;
    const int pick = pick_target(cands, cam.eye, focal_px, target_);
    if (pick < 0) {
        if (target_) drop_target();   // CPU only: no GL work without a target
        return;
    }
    const scenegraph::InstanceId id = cands[static_cast<std::size_t>(pick)].id;
    if (!target_ || !(*target_ == id)) {
        drop_target();
        target_ = id;
    }

    const scenegraph::Instance& inst = *world.get(id);
    const assets::Model& m = *lookup(inst.model_handle);
    const scenegraph::Instance::Surface& surf = inst.surface;
    const SurfaceType type = static_cast<SurfaceType>(surf.type);
    const TypeParams& params = live_params(type);
    const std::uint32_t shape = shape_hash(params);
    const float scale_local = glm::length(glm::vec3(inst.world[0]));
    const float R = cands[static_cast<std::size_t>(pick)].radius_gu;
    const int levels = level_count_for(R, kTs0Gu);

    // The baked field's identity; any change restarts the clipmap.
    const bool same_field = schedule_ && surf.type == type_ && surf.scale == scale_ &&
                            surf.seed == seed_ && shape == shape_ && levels == levels_ &&
                            std::abs(R - R_) <= 1e-5f * R;
    if (!same_field) {
        type_ = surf.type;
        scale_ = surf.scale;
        seed_ = surf.seed;
        shape_ = shape;
        R_ = R;
        levels_ = levels;
        // ONE octave source: the bake uses it as-is; the schedule's cost
        // weights double it for gas (~2n+3 noise evaluations per texel).
        octaves_.clear();
        std::vector<int> weights;
        for (int L = 0; L < levels; ++L) {
            const int n = octaves_for_texel(params, surf.scale, kTs0Gu * std::exp2(float(L)));
            octaves_.push_back(n);
            weights.push_back(type == SurfaceType::Gas ? 2 * n : n);
        }
        schedule_ = std::make_unique<ClipmapSchedule>(kTs0Gu, std::move(weights));
        anchored_ = false;
    }
    if (!atlas_ || atlas_->levels() != levels) atlas_ = std::make_unique<ClipmapAtlas>(levels);
    surface_ = surf;
    scale_local_ = scale_local;

    // Camera in the planet's BODY frame, centre removed, scaled to GU.
    const glm::vec3 p = (glm::vec3(glm::inverse(inst.world) * glm::vec4(cam.eye, 1.0f)) -
                         m.sphere_map->center_body) * scale_local;
    const float plen = glm::length(p);
    if (!anchored_ || needs_reanchor(to_plane(anchor_, p), R)) {
        anchor_ = make_anchor(plen > 1e-6f ? p / plen : glm::vec3(0, 0, 1), R);
        anchored_ = true;
        schedule_->reset();
    }
    const glm::vec2 nadir = to_plane(anchor_, plen > 1e-6f ? p / plen * R : anchor_.A * R);

    const long long budget = budget_ * (schedule_->complete(nadir) ? 1 : 2);
    std::vector<BakeRect> rects;
    last_cost_ = schedule_->update(nadir, budget, rects);
    if (!rects.empty())
        atlas_->bake(rects, BakeParams{anchor_, type, params, surf.scale, surf.seed, kTs0Gu,
                                       octaves_});
}

SampleUniforms PlanetDetailPass::uniforms_for(scenegraph::InstanceId id) const {
    SampleUniforms u;
    if (!target_ || !(*target_ == id) || !schedule_ || !atlas_ || !anchored_) return u;
    u.enabled = true;
    u.atlas = atlas_->texture();
    u.levels = levels_;
    u.ts0 = kTs0Gu;
    for (int L = 0; L < levels_ && L < kMaxLevels; ++L) {
        const Rect& v = schedule_->valid(L);
        u.valid[static_cast<std::size_t>(L)] =
            v.empty() ? kEmptyValid
                      : glm::vec4(float(v.x0), float(v.y0), float(v.x1), float(v.y1));
    }
    u.A = anchor_.A;
    u.E = anchor_.E;
    u.N = anchor_.N;
    u.R = anchor_.R;
    u.scale_local = scale_local_;
    u.type = surface_.type;
    u.ocean = surface_.ocean;
    u.has_ocean = surface_.has_ocean;
    u.ocean_tol = surface_.ocean_tol;
    u.strength = surface_.strength;
    u.albedo = surface_.albedo;
    u.scale = surface_.scale;
    u.params = live_params(static_cast<SurfaceType>(surface_.type));
    u.debug = debug_ ? 1 : 0;
    return u;
}

long long PlanetDetailPass::debug_valid_area() const {
    if (!schedule_) return 0;
    long long a = 0;
    for (int L = 0; L < schedule_->levels(); ++L) a += schedule_->valid(L).area();
    return a;
}

unsigned PlanetDetailPass::debug_atlas_texture() const {
    return atlas_ ? static_cast<unsigned>(atlas_->texture()) : 0u;
}

}  // namespace renderer::planet_detail
