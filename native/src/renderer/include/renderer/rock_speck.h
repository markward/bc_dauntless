// native/src/renderer/include/renderer/rock_speck.h
// Rock fields, speck band (2026-10-04): the near
// band's LARGE rocks -- the same generator, cells and seeds, so the same
// rocks -- carried on past the large billboard edge as lit specks (the far
// tier's flux-conserving speck shading), thinned whole cell at a time with
// distance so the count stays bounded. The puffs carry the field beyond.
//
// Per-frame CPU is ~0: the instance buffer is rebuilt only when the stream
// centre has moved restream_gu -- on a worker thread, the old set drawing
// until the new one swaps in -- and each speck's on-screen radius and alpha
// (inner hand-off, thinning, outer fade) are computed in rock_speck.vert.
#pragma once
#include <atomic>
#include <cstdint>
#include <future>
#include <unordered_map>
#include <unordered_set>
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
    float keep_d0_gu = 420.0f;    // >= the large billboard edge (405): the hand-off stays the same rocks
    float keep_power = 3.0f;
    float keep_band = 0.25f;
    float restream_gu = 50.0f;    // rebuild the instance buffer after this much travel
    float gain = 0.25f;           // multiplies the far tier's speck_gain (4): net 1, the billboards' light
};

// One speck instance (GPU layout, rock_speck.vert): position relative to the
// band's origin_sys(), the rock's radius, its albedo, its cell's hash u, and
// its shape seed (speck_shape_seed of its SYSTEM position: the big specks'
// outline wobble and bump phases, the same across every restream).
struct RockSpeckGpu {
    glm::vec3 pos;
    float radius;
    glm::vec3 albedo;
    float u;
    glm::vec4 seed;
};
static_assert(sizeof(RockSpeckGpu) == 48, "RockSpeckGpu is a 48-byte GPU instance");

// keep(d) * (1 + band) - u, over band, clamped: the cell's thinning alpha.
// Mirrored in rock_speck.vert. Uses s.keep_d0_gu as given: callers pass the
// effective start (speck_keep_d0).
float speck_keep_alpha(float d, float u, const SpeckDials& s);
// Where thinning starts: keep_d0_gu, but never inside the large billboards'
// outer edge + fade (edge_gu + fade_gu), so every rock the billboards hand
// over is kept. The CPU rebuild and the shader uniform both use this.
float speck_keep_d0(const SpeckDials& s, float edge_gu, float fade_gu);
// The thinning hash u of large cell ijk of the source with this seed.
float speck_cell_u(std::uint32_t seed, const glm::i64vec3& ijk);
// The per-rock shape seed from its system position: xyz phases in [0, 2 pi),
// w in [0, 1). A pure function of the rock, never of the band's origin.
glm::vec4 speck_shape_seed(const glm::dvec3& pos_sys);
// A rebuild walks at most this many cells per axis per source: (out_gu +
// margin) is clamped to (kSpeckMaxCellsPerAxis - 1) / 2 cells, never the
// cells widened. 72: the smallest cap that leaves the default band (1500 GU
// + the largest margin, 200, over 50 GU cells) unclamped.
constexpr int kSpeckMaxCellsPerAxis = 72;

class SpeckBand {
public:
    ~SpeckBand();
    void set_dials(const SpeckDials&);
    const SpeckDials& dials() const { return dials_; }
    // The near band's dials: the large class's generator and its billboard
    // edge (where specks begin). A generator change drops every cell.
    void set_near_dials(const NearDials&);
    void set_catalogue(const NearCatalogue&, std::vector<glm::vec3> large_albedo);
    // A change (far::same_density, or the source list) drops every cell.
    void set_sources(const std::vector<far::DiscSource>& active);
    // Rock promotion (final review M1): LARGE near-rock keys (near_rock_key)
    // promoted to real objects or destroyed -- the list rockfield_set_promoted
    // pushes. No speck is drawn for them. A changed set re-streams in place
    // (copied into the rebuild, never shared with the worker); dropped by clear().
    void set_excluded(std::unordered_set<std::uint64_t> keys);
    const std::unordered_set<std::uint64_t>& excluded() const { return excluded_; }
    // Drops every cell and the drawn set (version() moves), and cancels a
    // rebuild in flight.
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
    // Bumped whenever instances() changes (a swap or a clear): the host
    // uploads when it differs from the version it last uploaded.
    std::uint64_t version() const { return version_; }
    glm::dvec3 origin_sys() const { return origin_; }
    float in_gu() const { return near_.large.billboard_gu; }
    float fade_gu() const { return near_.fade_gu; }
    int cells() const { return static_cast<int>(cells_.size()); }
    int last_stream_cells_generated() const { return last_generated_; }
    // The margin the next rebuild covers (see rebuild_margin_gu in the .cc).
    double next_margin_gu() const;
    // TEST-ONLY: a finished rebuild is swapped in no sooner than this many
    // stream() calls after its launch (a worst-case worker latency, in frames).
    void debug_set_min_job_frames(int n) { debug_min_job_frames_ = n; }
    // TEST-ONLY: the next rebuilds throw inside the worker (M6).
    void debug_fail_jobs(bool on) { debug_fail_jobs_ = on; }
    // TEST-ONLY: whether the last rebuild taken stopped on the cancel flag.
    bool debug_last_job_cancelled() const { return last_cancelled_; }
private:
    struct Cell {
        std::vector<RockSpeckGpu> rocks; std::vector<glm::dvec3> pos_sys;
        std::vector<std::uint64_t> keys;  // near_rock_key per rock (the exclusion)
        float u = 0; bool live = false;
    };
    using CellMap = std::unordered_map<std::uint64_t, Cell>;
    struct Job {                          // everything a rebuild reads, by value
        SpeckDials dials; NearDials near; NearCatalogue cat;
        std::vector<glm::vec3> albedo; std::vector<far::DiscSource> sources;
        std::unordered_set<std::uint64_t> excluded;   // a copy: the worker owns it
        glm::dvec3 centre{0.0}; CellMap cells;
        double margin = 0.0;              // rebuild_margin_gu at launch
        bool fail = false;                // debug_fail_jobs
    };
    struct Result {
        CellMap cells; std::vector<RockSpeckGpu> instances; glm::dvec3 origin{0.0};
        int generated = 0; bool cancelled = false;
    };
    static Result rebuild(Job job, const std::atomic<bool>& cancel);
    static Result run_job(Job job, const std::atomic<bool>* cancel);   // rebuild, exceptions caught
    bool take_result();                   // swap a finished rebuild in (if still current)
    void invalidate();                    // ++generation_, cancel a rebuild in flight
    std::future<Result> job_;
    std::atomic<bool> cancel_{false};
    std::uint64_t generation_ = 0;        // bumped by anything that invalidates the cache
    std::uint64_t job_generation_ = 0;
    std::uint64_t version_ = 1;
    SpeckDials dials_;
    NearDials near_;
    NearCatalogue cat_;
    std::vector<glm::vec3> albedo_;     // per catalogue index
    std::vector<far::DiscSource> sources_;
    std::unordered_set<std::uint64_t> excluded_;
    CellMap cells_;
    std::vector<RockSpeckGpu> instances_;
    glm::dvec3 origin_{0.0};
    bool dirty_ = true;
    bool hidden_ = false;
    bool has_last_ = false;
    glm::dvec3 last_frame_centre_{0.0};
    int last_generated_ = 0;
    // Worker latency, measured in stream() calls (frames): the margin.
    int job_frames_ = 0;                  // stream() calls since the job in flight launched
    int last_job_frames_ = 1;             // the last taken job's
    double step_peak_ = 0.0;              // the largest per-call step since the last launch
    double last_step_ = 0.0;
    int debug_min_job_frames_ = 0;
    bool debug_fail_jobs_ = false;
    bool last_cancelled_ = false;
};

}  // namespace renderer::rockfield
