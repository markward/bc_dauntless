// native/src/renderer/include/renderer/rock_near.h
// Rock fields, near band (docs/superpowers/specs/2026-10-02-rock-fields-design.md):
// real rocks streamed in deterministic cells around a centre, sampled from
// the one density field every band shares (far::field_density).
#pragma once
#include <cstdint>
#include <functional>
#include <optional>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>
#include <glm/glm.hpp>
#include <renderer/far_field.h>
#include <renderer/minor_field.h>

namespace renderer::rockfield {

enum class NearClass : std::uint8_t { Small = 0, Large = 1 };

struct NearClassDials {
    // density 0.008 -> 0.010, mesh_gu 20 -> 15: Mark, live 2026-10-03
    // (slightly more small rocks, as billboards closer in).
    float density = 0.010f;     // rocks / GU^3 where field_density == 1
    float r_min = 0.05f, r_max = 0.5f, exponent = 2.5f;
    float cell_gu = 10.0f;
    float mesh_gu = 15.0f;      // mesh out to here (camera distance)
    float billboard_gu = 90.0f; // billboard out to here; streamed radius
    int max_instances = 4000;   // per camera build
};

struct NearDials {   // defaults MUST equal far_dials.py DEFAULTS near_* keys
    NearClassDials small{};
    // density 1.25e-4 -> 6.25e-5, mesh_gu 50 -> 60, billboard_gu 60 -> 90:
    // Mark, live 2026-10-03 (fewer big asteroids but visible a bit further).
    // cell_gu 20 -> 50, max_instances 1000 -> 4000: rock-real Part 1,
    // 2026-10-03 (streaming the large class out to large_far_gu in 20 GU
    // cells would hit the 33-per-axis cap -- this redefines which large rocks
    // exist, still deterministic). The 4000 cap at the 250 GU default: a
    // full-density field holds ~770 large rocks in a 60 degree 16:9 view out
    // to 250 GU and ~2,300 in a 90 degree one; 4000 also covers the live dial
    // at 400 GU (~3,200 at 60 degrees), which 1000 would cut nearest-first.
    NearClassDials large{1.0f / 16000.0f, 1.0f, 5.0f, 2.5f, 50.0f, 60.0f, 270.0f, 4000};
    float fade_gu = 4.0f;                 // outer (translucent) fade band at each billboard edge
    // Mesh <-> billboard hand-off width. 0 = a hard swap, no screen-door
    // dither (Mark, live 2026-10-03: the dithered hand-off read as rocks
    // "checkerboarding in"). > 0 = the old dithered crossfade.
    float handoff_fade_gu = 0.0f;
    // Multiplies every near rock's tumble rate (mesh and billboard alike, so
    // the hand-off stays matched). 0.05: interim while billboards snapped
    // between their 16 baked views (Mark, live 2026-10-03). Billboards now
    // blend between 64 views (rock-blend), so the dial may go back up live.
    float tumble_scale = 0.05f;
    // A stream whose centre moved more than this since the last one is a
    // dash: both classes' billboards collapse to the mesh range and regrow
    // once slow. <= 0 = off (Mark, 2026-10-04: dash streaming cost ~16 ms).
    float dash_collapse_step_gu = 25.0f;
    // Far shell (rock-real Part 1, 2026-10-03: every big-asteroid silhouette
    // is a real rock). With large_far_gu > large.billboard_gu the large
    // class's SAME rocks stream on past billboard_gu as billboards (no
    // fade at billboard_gu) out to large_far_gu, fading out translucent
    // over the last large_far_fade_gu. A large billboard whose on-screen
    // radius is at or below large_min_px draws nothing past mesh_gu +
    // fade_gu and fades in over the next kNearPixelFadeBand px (see
    // near_large_weights). large_far_gu <= large.billboard_gu: the shell is
    // off -- exactly the old rule. The drawn shell never passes the streamed
    // reach (NearField::large_reach_gu: clamped by the 33-cells-per-axis cap,
    // shrunk at dash speed).
    // 250, not the 400 GU target: in the Beol 4 inside bench (Debug) the
    // shell cost +1.5 ms CPU per frame at 400, +0.7 at 300, ~+0.4 at 250.
    float large_far_gu = 250.0f;
    float large_far_fade_gu = 40.0f;
    float large_min_px = 1.5f;
    // The same pixel floor for small rocks (Mark, live 2026-10-04: most small
    // billboards at 30-45 GU are under a pixel; skip them and their cells).
    float small_min_px = 2.5f;
    // The far shell at dash speed (rock-real review, 2026-10-03): visual
    // only, it flashes past, yet regenerating it every frame cost ~3 ms per
    // dash frame. A stream() whose centre moved more than
    // far_shell_max_step_gu since the last shrinks the large reach back to
    // billboard_gu (the pre-shell range, drawn by the old rule); each later
    // stream regrows it by at most far_shell_regrow_gu, so it comes back
    // over several frames, never in one hitch. 25 GU per stream is 1,500
    // GU/s at 60 Hz -- 3.75x in-system warp (400 GU/s = 6.7 GU per frame),
    // still above it down to 16 fps; a 100,000 GU/s dash is 1,667 GU/frame.
    float far_shell_max_step_gu = 25.0f;
    float far_shell_regrow_gu = 20.0f;
    float stream_margin_gu = 10.0f;       // keep cells this far past range (hysteresis)
    float collide_cooldown_s = 0.5f;      // per large rock, once the ship is clear (pen == 0)
    float collide_margin_gu = 0.0f;
};

struct NearRock {
    glm::dvec3 pos_sys{0.0};
    float radius = 0.0f;
    int rock = 0;                    // catalogue index (fragment for Small, major for Large)
    glm::vec3 tumble_axis{0, 0, 1};
    float tumble_rate = 0.0f, phase = 0.0f;
};

struct NearCatalogue {               // pushed with far_set_catalogue
    std::vector<int> small_rocks;    // catalogue indices of silicate-family fragments
    std::vector<int> large_rocks;    // catalogue indices of silicate-family majors
    // Model-unit bound radius at load scale 1, parallel to the index lists:
    // a mesh item's scale is radius / bound. A missing or non-positive bound
    // draws no mesh for that slot.
    std::vector<float> small_bound_mu, large_bound_mu;
    // The impostor bake's view directions (glTF frame, as FarField's): an
    // octahedral layout (a square count). Otherwise -- empty included -- no
    // billboards at all.
    std::vector<glm::vec3> view_dirs_gltf;
};

// Family codes in NearOutput::meshes bins, resolved by the host's FragmentLookup:
constexpr int kNearSmallFamily = 1000;   // slot = index into NearCatalogue::small_rocks
constexpr int kNearLargeFamily = 1001;   // slot = index into NearCatalogue::large_rocks

struct NearBuildInput {
    glm::mat4 view{1}, proj{1};
    float viewport_h = 720.0f;
    glm::dvec3 render_origin{0.0};   // view space of render space's origin
    glm::dvec3 anchor_sys{0.0};      // system position of view space's origin (FarField::anchor())
    double game_time = 0.0;
    float lod0_pixel_radius = 24.0f; // minors' dial: lod0 above, lod1 below
};
struct NearOutput {
    std::vector<minors::Bin> meshes;          // family kNearSmallFamily/kNearLargeFamily
    // .rock = catalogue index. Solid (weight 1, dither 0) and the mesh <->
    // billboard hand-off (screen-door dithered against its mesh).
    std::vector<far::ImpostorBin> billboards;
    // Rock fade (2026-10-03): billboards fading in from nothing at
    // billboard_gu, drawn TRANSLUCENT (FarPass::render_impostors_blended;
    // alpha = far::impostor_fade_alpha(axis_y_dither.w) = the billboard weight).
    // Far to near: the class with the larger billboard_gu first, then by
    // catalogue index; each bin's items farthest first.
    std::vector<far::ImpostorBin> billboards_fading;
    int mesh_count = 0;
    int billboard_count = 0;          // every billboard: billboards + billboards_fading
    int billboard_fading_count = 0;   // billboards_fading only
    // Diagnostics (tests, benches): cells whose per-cell broad phase ran and
    // rocks whose per-rock test ran in this build (both classes).
    int cells_tested = 0, rocks_tested = 0;
};
struct NearWeights { float mesh = 0, billboard = 0; };
// Pure tier rule for camera distance d (spec §2): mesh 1 below mesh_gu - fade,
// ramps to 0 at mesh_gu; billboard = 1 - mesh up to billboard_gu - fade, then
// ramps to 0 at billboard_gu; nothing beyond. fade_gu <= 0 is a hard step.
NearWeights near_weights(float d, const NearClassDials& c, float fade_gu);
// As above with a separate mesh <-> billboard hand-off width.
NearWeights near_weights(float d, const NearClassDials& c, float fade_gu, float handoff_fade_gu);
// Width of the pixel-floor fade-in (px above large_min_px).
constexpr float kNearPixelFadeBand = 1.0f;
// Pure tier rule of the LARGE class at camera distance d and on-screen
// radius px (pixels). Shell off (large_far_gu <= large.billboard_gu):
// near_weights(d, large, fade_gu). On: the mesh weight as near_weights; the
// billboard 1 - mesh up to large_far_gu - large_far_fade_gu, ramping to 0 at
// large_far_gu, times a pixel-floor factor that blends from 1 at mesh_gu to
// the pixel-floor ramp (0 at large_min_px, 1 at large_min_px +
// kNearPixelFadeBand) at mesh_gu + fade_gu -- so the hand-off (d < mesh_gu)
// is untouched and nothing pops where the mesh ends, at any viewport size.
NearWeights near_large_weights(float d, float px, const NearDials& dials);

// Pure: the rocks of one cell. Poisson(n_bound * L^3) candidates, each
// accepted with probability density * field_density(x) / n_bound, where
// n_bound = density * a_bound(cell) * noise_m_bound(s). Fixed draw order per
// candidate: position (3), accept, size, rock, tumble axis (2), rate, phase.
std::vector<NearRock> generate_near_cell(const far::DiscSource& s, NearClass cls,
                                         const glm::i64vec3& ijk, const NearDials& d,
                                         const NearCatalogue& cat);

struct NearStats { int cells = 0; int small = 0; int large = 0; int ghosted = 0; };

// One large-rock touch (spec §2 "Collisions"), drained by Python
// (engine/rocks/scenery_contact.py). VIEW space; normal points rock -> ship.
struct NearContact {
    glm::dvec3 point_view{0.0};        // closest point on the ship's contact shape at first touch
    glm::vec3 normal{0, 0, 1};
    glm::dvec3 rock_centre_view{0.0};
    float rock_radius = 0.0f;
    float rel_speed = 0.0f;            // GU/s, the ship's sweep speed this step
    float pen = 0.0f;                  // rock_radius - distance(centre, shape) at the CURRENT pose, >= 0
    std::uint64_t key = 0;             // the rock's key: NearField::rearm(key) clears its cooldown
};

struct NearStepInput {
    double game_time = 0.0;
    glm::dvec3 render_origin{0.0};
    glm::dvec3 anchor_sys{0.0};
    std::optional<minors::PlayerBox> player;   // RENDER space; unset: no contacts, sweep state reset
    float shield_inflate = 0.0f;               // > 0: the LARGE-rock box half extents x this (shields up)
    minors::Dials minor_dials;                 // shove + contact margin + teleport guard
};

class NearField {
public:
    void set_dials(const NearDials&);      // a generator change clears every cell
    const NearDials& dials() const { return dials_; }
    void set_catalogue(NearCatalogue);     // clears every cell
    // The far tier's active sources (FarField::active_sources(), system coords).
    void set_sources(const std::vector<far::DiscSource>& active);  // clears on change
    // Generate cells newly in range of `centre_sys`, drop cells out of range +
    // stream_margin_gu. Range per class = billboard_gu.
    void stream(const glm::dvec3& centre_sys);
    // The large class's current streamed reach = its drawn outer edge:
    // billboard_gu with the far shell off or shrunk at dash speed, else the
    // (regrowing) shell, never past the 33-cells-per-axis cap.
    float large_reach_gu() const;
    // The dials build() draws by: dials() with the large far shell set to
    // what is streamed (large_far_gu = large_reach_gu() when the shell is on).
    const NearDials& effective_dials() const { return eff_; }
    void clear();                          // cells, contacts, sweep state, cooldowns, ghosts, far-shell state
    NearStats stats() const;
    // Every rock currently streamed, per class (tests, build, contacts).
    void for_each(NearClass cls, const std::function<void(std::uint64_t key, const NearRock&)>& fn) const;
    // Per drawn camera: every streamed rock in ONE tier (mesh or billboard)
    // except inside a fade band, where both draw screen-door dithered (mesh
    // extra.x = 1 - w, billboard dither = -w; weight 1 => exactly 0).
    // Frustum-culled; per class at most max_instances items (meshes +
    // billboards together), nearest first. Const: never streams.
    void build(const NearBuildInput& in, NearOutput& out) const;

    // Contacts (spec §2 "Collisions"). Per frame: advances small-rock shoves,
    // then sweeps the player's box from its previous pose to its current one.
    // Large rocks: solid, fixed, player only -- a touch is reported every
    // step the rock still penetrates the box at the current pose (pen > 0;
    // Python's receding gate debounces), else at most once per
    // collide_cooldown_s per rock; a rock that streams in (or is met on the
    // first posed step) already overlapping the box is ghosted until a step
    // finds the box clear of it. shield_inflate widens only this box. Small
    // rocks: the minors' harmless shove, against the bare hull box.
    void step(const NearStepInput& in);
    std::vector<NearContact> drain_large_contacts() { return std::exchange(large_contacts_, {}); }
    std::vector<minors::Contact> drain_small_contacts() { return std::exchange(small_contacts_, {}); }
    void reset_player() { has_prev_ = false; }   // forget the previous pose
    // Clear one large rock's touch cooldown, so its next touching step
    // reports again. Python calls it when it rejects a reported touch for
    // geometry (a shield-bubble miss: the inflated box touched, the
    // ellipsoid did not), so the rock is not silenced for the cooldown while
    // the ship closes on it. An unknown key is a no-op.
    void rearm(std::uint64_t key) { large_last_.erase(key); }
    // TEST-ONLY: add a rock with an explicit key to a dedicated per-class
    // test cell that stream() never drops (only clear() removes it).
    void debug_add_rock(NearClass cls, std::uint64_t key, const NearRock& r);
    // Diagnostics: full (non-incremental) stream passes run so far, per
    // (source, class). Tests assert the live call pattern stays incremental.
    std::uint64_t full_stream_passes() const { return full_stream_passes_; }
    // Diagnostics: cells whose distance the last stream() tested (the drop
    // and the generation passes together).
    int last_stream_cells_tested() const { return last_stream_cells_tested_; }
    // Diagnostics: large cells the last posed step tested rock by rock (the
    // rest were rejected whole by the cell broad phase).
    int last_step_large_cells_tested() const { return last_step_large_cells_tested_; }
    // Diagnostics: cells (either class) the last posed step examined at all.
    int last_step_cells_examined() const { return last_step_cells_examined_; }
private:
    struct Cell {
        NearClass cls;
        std::vector<NearRock> rocks;
        glm::dvec3 lo{0.0};              // system-space AABB min corner
        double size = 0.0;               // edge (the class's cell_gu when generated)
        bool pinned = false;             // the test cell: never streamed out
        std::vector<std::uint64_t> keys; // pinned only: explicit rock keys
        float r_max = 0.0f;              // largest rock radius (broad phase)
        // Large cells: a rock is "fresh" (ghost test) unless the previous
        // step saw it. Every step sees every large cell, so a streamed cell
        // was seen by step S exactly when S > born (the step clock when it
        // was generated; one less when it was regenerated before the next
        // step had a chance to miss it -- the old eager per-step stamp, kept
        // lazily). The pinned test cell, whose rocks grow, keeps the stamp:
        // the step that last saw it (0 = none) and how many rocks it saw then.
        std::uint64_t born = 0;
        std::uint64_t seen_step = 0;
        std::size_t seen_rocks = 0;
        glm::i64vec3 ijk{0};             // streamed cells: the cell index
        std::uint64_t block = 0;         // streamed cells: its block's key ...
        std::size_t block_slot = 0;      // ... and its index in Block::cells
        // Streamed cells of at most 16 rocks (nearly all): rock indices,
        // largest radius first, packed 4 bits each -- build's pixel-floor
        // early-out (no allocation per cell: thousands are generated per
        // dash frame). ordered = false: no order (the pinned test cell, or
        // more than 16 rocks), every rock is tested.
        bool ordered = false;
        std::uint64_t by_radius4 = 0;
    };
    // Streamed cells grouped per class into blocks of 4^3 small / 2^3 large
    // cells (aligned in cell index space, every source together), so build and
    // step reject far-away cells a block at a time. A block's box and r_max
    // only grow while it lives (conservative); an empty block is erased.
    struct Block {
        glm::dvec3 lo{0.0}, hi{0.0};     // system-space AABB of its cells
        float r_max = 0.0f;              // largest rock radius of its cells
        std::vector<std::pair<std::uint64_t, Cell*>> cells;   // unordered
    };
    std::unordered_map<std::uint64_t, Block> blocks_[2];      // per class
    std::vector<std::uint64_t> pinned_;                       // the test cells' keys
    void block_add(std::uint64_t key, Cell& c);
    void block_remove(std::uint64_t key, const Cell& c);
    std::uint64_t key_of(std::uint64_t cell_key, const Cell& c, std::size_t i) const;
    void invalidate_stream_watch();
    // key: mix(source id, class, i, j, k); rock key = mix(cell key, index + 1)
    std::unordered_map<std::uint64_t, Cell> cells_;
    NearDials dials_;
    NearDials eff_;                       // dials_ with the streamed far shell
    float shell_far_ = -1.0f;             // the streamed shell edge; < 0: not yet streamed
    // Billboard reach at dash speed (Mark, 2026-10-04: the 3x ranges cost
    // ~16 ms/frame regenerating ~46k rocks per dash frame). 1 = full
    // billboard ranges; a dash-speed stream drops it to 0 (both classes
    // stream only to mesh_gu); slow streams regrow it by kDashRegrowPerStream.
    float dash_frac_ = 1.0f;
    bool has_last_centre_ = false;
    glm::dvec3 last_centre_{0.0};
    void update_effective();
    NearCatalogue cat_;
    far::ImpostorViews views_;   // make_impostor_views(cat_.view_dirs_gltf)
    std::vector<far::DiscSource> sources_;

    // Incremental streaming (rock-fields perf, 2026-10-03; rock-perf2,
    // 2026-10-04). After a full pass at c_ref, only cells whose distance from
    // c_ref lies within the watch width w (rock_near.cc watch_gu) of a
    // threshold can change state while the centre stays within w of c_ref
    // (distance to a box is 1-Lipschitz). Each such cell -- and every
    // streamed cell, for the keep threshold -- waits in a min-heap keyed by
    // the path length (path_s_, the centre's summed travel) at which it could
    // first cross its next threshold, so a frame re-tests only the cells its
    // own travel reached. (At dash speed the drop pass tests every cell and
    // keeps no heap.)
    struct Due {
        double due;                       // path_s_ at which to re-test
        std::uint64_t id;                 // shell index (generation) or cell key (drop)
        bool operator>(const Due& o) const { return due > o.due; }
    };
    struct GenWatch {                     // per (source, class)
        bool has_ref = false;             // c_ref is the last full pass's centre
        bool valid = false;               // ... and `shell` was recorded there
        glm::dvec3 c_ref{0.0};
        std::vector<glm::i64vec3> shell;  // R - w < dist(c_ref) <= R + w, (i, j, k) order
        std::vector<Due> heap;            // over shell indices
        // Every cell within R of (and in the box of) c_prev exists: the last
        // stream() that tested this watch left it so.
        bool prev_complete = false;
        glm::dvec3 c_prev{0.0};
    };
    std::vector<GenWatch> gen_watch_;     // sources_.size() * 2
    bool drop_valid_ = false;             // drop_heap_ holds every non-pinned cell
    std::vector<Due> drop_heap_;          // over cell keys
    double path_s_ = 0.0;                 // the centre's travel since the last invalidation
    std::uint64_t full_stream_passes_ = 0;
    int last_stream_cells_tested_ = 0;
    int last_step_large_cells_tested_ = 0;
    int last_step_cells_examined_ = 0;

    // Contact state (cleared by clear()). Per-rock state carries its CELL
    // key, so pruning asks "is the cell still streamed" instead of
    // re-collecting every streamed rock's key each step.
    struct Shove { minors::ShoveState s; std::uint64_t cell = 0; };
    struct Touch { double t = 0.0; std::uint64_t cell = 0; };
    double last_time_ = 0.0;
    bool stepped_ = false;                       // last_time_ is valid
    bool has_prev_ = false;
    glm::dvec3 prev_center_sys_{0.0};            // player box centre, SYSTEM space
    std::uint64_t step_count_ = 1;               // Cell::seen_step clock (0 = never)
    // Large cells dropped since the last step that had seen them: a cell
    // regenerated before the next step keeps its "seen" state (as the rock
    // keys did when seen-ness was a key set).
    std::unordered_map<std::uint64_t, std::size_t> dropped_seen_;
    std::unordered_map<std::uint64_t, std::uint64_t> ghosts_;   // rock key -> cell key
    std::unordered_map<std::uint64_t, Touch> large_last_;       // last reported touch
    std::unordered_map<std::uint64_t, Shove> shoves_;           // small rocks
    std::vector<NearContact> large_contacts_;
    std::vector<minors::Contact> small_contacts_;
};

}  // namespace renderer::rockfield
