// native/src/renderer/include/renderer/rock_mid.h
// Rock fields, mid band (docs/superpowers/specs/2026-10-02-rock-fields-design.md
// §3): one baked rock-collection sprite per tile, in three nested tile levels
// fixed in system coordinates, chosen from the same density field the near
// band samples (far::field_density).
#pragma once
#include <vector>
#include <glm/glm.hpp>
#include <renderer/far_field.h>

namespace renderer::rockfield {

struct MidDials {   // defaults MUST equal far_dials.py mid_* / haze_handoff_* keys
    float l0_tile_gu = 150.0f, l1_tile_gu = 600.0f, l2_tile_gu = 2400.0f;
    float in_lo_gu = 80.0f, in_hi_gu = 150.0f;     // L0 fades in over [in_lo, in_hi]
    float l0_out_gu = 600.0f, l1_out_gu = 2400.0f; // level boundaries
    float xfade_frac = 0.25f;                      // boundary b crossfades over [b(1-f), b]
    float handoff_gu = 8000.0f, handoff_band_gu = 2000.0f;  // L2 fades out over [handoff-band, handoff]
    float fill = 1.0f;                             // chance = clamp(density * fill, 0, 1)
    float sprite_scale = 1.0f;                     // sprite diameter = tile * sprite_scale * (0.8 + 0.4 u)
    int max_sprites = 4000;                        // per camera build, nearest first
};

struct MidCollection { int atlas_index; int variant; };   // variant 0 sparse, 1 medium, 2 dense

// Pure: the weight of level `lvl` (0..2) at camera distance d (0..1). Linear
// ramps: each level is lower(d) * (1 - upper(d)); L0's lower ramp is
// [in_lo, in_hi], a boundary b's ramp [b(1-f), b], L2's upper ramp
// [handoff - band, handoff]. With the defaults the three sum to 1 everywhere
// in [in_hi, handoff - band].
float mid_level_weight(int lvl, float d, const MidDials& m);
// Pure: the signed screen-door dither of level `lvl` at d (far::make_impostor's
// convention): -w while the level fades IN (its lower ramp), +(1 - w) while it
// fades OUT (its upper ramp), exactly 0 at w == 1 (and 0 where w == 0).
float mid_level_dither(int lvl, float d, const MidDials& m);

struct MidBuildInput {
    glm::mat4 view{1}, proj{1};
    float viewport_h = 720;
    glm::dvec3 render_origin{0};   // view space of render space's origin
    glm::dvec3 anchor_sys{0};      // system position of view space's origin (FarField::anchor())
};
struct MidOutput {
    std::vector<far::ImpostorBin> sprites;   // .rock = atlas index, ascending
    int count = 0;                           // sprites emitted (after the cap)
    int tiles = 0;                           // tiles examined: in a level's range and in the frustum
};

class MidField {
public:
    void set_dials(const MidDials&);
    const MidDials& dials() const { return dials_; }
    void set_collections(std::vector<MidCollection>);   // atlas_index = FarPass atlas slot
    // The collection bake's view directions (glTF frame, as FarField's).
    // Empty: build() emits nothing (far::make_impostor needs at least one).
    void set_view_dirs(std::vector<glm::vec3> view_dirs_gltf);
    // The far tier's active sources (FarField::active_sources(), system coords).
    void set_sources(const std::vector<far::DiscSource>& active);
    // Per drawn camera: every present tile of every level whose weight is
    // > 0 at its (jittered) SPRITE's distance, never a sprite nearer than
    // in_lo_gu, frustum-culled, at most max_sprites nearest first. Selection
    // is keyed by the tile. Pure in its inputs (no state changes).
    void build(const MidBuildInput& in, MidOutput& out) const;

private:
    MidDials dials_;
    std::vector<MidCollection> collections_;
    std::vector<glm::vec3> view_dirs_;
    std::vector<far::DiscSource> sources_;
};

}  // namespace renderer::rockfield
