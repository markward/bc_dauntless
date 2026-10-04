// native/src/renderer/include/renderer/rock_puffs.h
// Rock fields, far look as PUFFS (SPIKE, spike/rock-specks 2026-10-04): a
// few hundred large, soft, sun-lit billboards per tile field (and per belt),
// placed by
// rejection-sampling the field's own density (far::field_density), so the
// field's clumps and lumpy outline come from where the puffs land. Drawn in
// the main (MSAA) pass after every opaque writer, depth-tested without depth
// writes, so a hull in front antialiases against them like any geometry --
// unlike the volumetric haze, composited after the resolve.
// Placement is pure and deterministic (the source's seed); per-frame CPU is
// one uniform upload.
#pragma once
#include <cstdint>
#include <vector>
#include <glm/glm.hpp>
#include <renderer/far_field.h>

namespace renderer::rockfield {

struct PuffDials {   // defaults MUST equal far_dials.py DEFAULTS puff_* keys
    int count = 400;              // per tile field
    float size_frac = 0.18f;      // puff radius = size_frac x field radius x [0.6, 1.4]
    float opacity = 0.04698f; // Mark, live 2026-10-04 (was 0.35)       // peak alpha of one puff at full density
    float brightness = 8.0f;      // colour only (the haze needed ~9: albedo 0.4 x phase-lit)
    float start_gu = 800.0f;      // puffs fade in from here (camera distance) ...
    float ramp_gu = 800.0f;       // ... over this many GU
    float near_fade = 1.5f;       // and fade out within near_fade x their radius
    // Belts (disc sources): belt_count puffs per belt, each of radius
    // belt_size_h x the local scale height (a belt has no field radius).
    int belt_count = 2000;
    float belt_size_h = 1.2f;
};

struct PuffGpu {
    glm::vec3 pos;                // relative to PuffField::origin_sys()
    float radius;
    glm::vec3 albedo;
    float weight;                 // local density / its bound, in [0, 1]
};
static_assert(sizeof(PuffGpu) == 32, "PuffGpu is a 32-byte GPU instance");

// Pure: one source's puffs in SYSTEM coordinates (pos relative to (0,0,0)),
// rejection-sampled from far::field_density: a tile field (sphere) within
// its outer reach, a belt (disc) within its cylinder (last table row + outer
// fade, +-3 scale heights there).
std::vector<PuffGpu> place_puffs(const far::DiscSource& s, const PuffDials& d,
                                 std::vector<glm::dvec3>* pos_sys);

class PuffField {
public:
    void set_dials(const PuffDials&);
    const PuffDials& dials() const { return dials_; }
    void set_sources(const std::vector<far::DiscSource>& active);
    void clear();
    // True when instances() changed since the last call (re-upload).
    bool take_dirty() { const bool d = dirty_; dirty_ = false; return d; }
    const std::vector<PuffGpu>& instances() const { return instances_; }
    glm::dvec3 origin_sys() const { return origin_; }
private:
    void rebuild();
    PuffDials dials_;
    std::vector<far::DiscSource> sources_;
    std::vector<PuffGpu> instances_;
    glm::dvec3 origin_{0.0};
    bool dirty_ = true;
};

}  // namespace renderer::rockfield
