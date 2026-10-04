// native/src/renderer/include/renderer/rock_speck.h
// Rock fields, speck band (SPIKE, spike/rock-specks, 2026-10-04): the near
// band's LARGE rocks -- the same generator, cells and seeds, so the same
// rocks -- carried on past the large billboard edge as lit specks (the far
// tier's flux-conserving speck shading), thinned whole cell at a time with
// distance so the count stays bounded. The haze takes over beyond.
//
// Per-frame CPU is ~0: the instance buffer is rebuilt only when the stream
// centre has moved restream_gu -- on a worker thread, the old set drawing
// until the new one swaps in -- and each speck's on-screen radius and alpha
// (inner hand-off, thinning, outer fade) are computed in rock_speck.vert.
#pragma once
#include <cstdint>
#include <future>
#include <unordered_map>
#include <vector>
#include <glm/glm.hpp>
#include <renderer/far_field.h>
#include <renderer/rock_near.h>

namespace renderer::rockfield {

struct SpeckDials {   // defaults MUST equal far_dials.py DEFAULTS speck_* keys
    float out_gu = 1500.0f;       // specks end here (camera distance) ...
    float out_fade_gu = 400.0f;   // ... fading out over this band
    // Thinning: a cell at distance d is kept while its hash u < keep(d) =
    // min(1, (keep_d0_gu / d)^keep_power), fading over keep_band of u. Every
    // rock is kept inside keep_d0_gu, so the hand-off from the billboards is
    // the same rocks. Power 2: on-screen density per unit depth flat (count
    // linear in range); 3: count grows as log(range).
    float keep_d0_gu = 350.0f;
    float keep_power = 3.0f;
    float keep_band = 0.25f;
    float restream_gu = 50.0f;    // rebuild the instance buffer after this much travel
    float gain = 0.25f;           // multiplies the far tier's speck_gain (4): net 1, the billboards' light
};

// One speck instance (GPU layout, rock_speck.vert): position relative to the
// band's origin_sys(), the rock's radius, its albedo, and its cell's hash u.
struct RockSpeckGpu {
    glm::vec3 pos;
    float radius;
    glm::vec3 albedo;
    float u;
};
static_assert(sizeof(RockSpeckGpu) == 32, "RockSpeckGpu is a 32-byte GPU instance");

// keep(d) * (1 + band) - u, over band, clamped: the cell's thinning alpha.
// Mirrored in rock_speck.vert.
float speck_keep_alpha(float d, float u, const SpeckDials& s);

class SpeckBand {
public:
    ~SpeckBand();
    void set_dials(const SpeckDials&);
    const SpeckDials& dials() const { return dials_; }
    // The near band's dials: the large class's generator and its billboard
    // edge (where specks begin). A generator change drops every cell.
    void set_near_dials(const NearDials&);
    void set_catalogue(const NearCatalogue&, std::vector<glm::vec3> large_albedo);
    void set_sources(const std::vector<far::DiscSource>& active);
    void clear();
    // Re-stream around centre_sys when it has moved restream_gu since the
    // last stream (or anything changed), on a worker thread. True when
    // instances() changed (a finished rebuild swapped in). A stream step
    // above dash_step_gu hides the band until it is slow again.
    bool stream(const glm::dvec3& centre_sys, float dash_step_gu);
    // Tests: block on a rebuild in flight and swap it in. True if it did.
    bool finish();
    bool hidden() const { return hidden_; }
    const std::vector<RockSpeckGpu>& instances() const { return instances_; }
    glm::dvec3 origin_sys() const { return origin_; }
    float in_gu() const { return near_.large.billboard_gu; }
    float fade_gu() const { return near_.fade_gu; }
    int cells() const { return static_cast<int>(cells_.size()); }
    int last_stream_cells_generated() const { return last_generated_; }
private:
    struct Cell { std::vector<RockSpeckGpu> rocks; std::vector<glm::dvec3> pos_sys; float u = 0; bool live = false; };
    using CellMap = std::unordered_map<std::uint64_t, Cell>;
    struct Job {                          // everything a rebuild reads, by value
        SpeckDials dials; NearDials near; NearCatalogue cat;
        std::vector<glm::vec3> albedo; std::vector<far::DiscSource> sources;
        glm::dvec3 centre{0.0}; CellMap cells;
    };
    struct Result { CellMap cells; std::vector<RockSpeckGpu> instances; glm::dvec3 origin{0.0}; int generated = 0; };
    static Result rebuild(Job job);
    bool take_result();                   // swap a finished rebuild in (if still current)
    std::future<Result> job_;
    std::uint64_t generation_ = 0;        // bumped by anything that invalidates the cache
    std::uint64_t job_generation_ = 0;
    SpeckDials dials_;
    NearDials near_;
    NearCatalogue cat_;
    std::vector<glm::vec3> albedo_;     // per catalogue index
    std::vector<far::DiscSource> sources_;
    CellMap cells_;
    std::vector<RockSpeckGpu> instances_;
    glm::dvec3 origin_{0.0};
    bool dirty_ = true;
    bool hidden_ = false;
    bool has_last_ = false;
    glm::dvec3 last_frame_centre_{0.0};
    int last_generated_ = 0;
};

}  // namespace renderer::rockfield
