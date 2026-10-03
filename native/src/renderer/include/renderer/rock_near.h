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
    float density = 0.008f;     // rocks / GU^3 where field_density == 1
    float r_min = 0.05f, r_max = 0.5f, exponent = 2.5f;
    float cell_gu = 10.0f;
    float mesh_gu = 20.0f;      // mesh out to here (camera distance)
    float billboard_gu = 30.0f; // billboard out to here; streamed radius
    int max_instances = 4000;   // per camera build
};

struct NearDials {   // defaults MUST equal far_dials.py DEFAULTS near_* keys
    NearClassDials small{};
    NearClassDials large{1.0f / 8000.0f, 1.0f, 5.0f, 2.5f, 20.0f, 50.0f, 60.0f, 1000};
    float fade_gu = 4.0f;                 // dither band width at each tier edge
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
    // The impostor bake's view directions (glTF frame, as FarField's). Empty:
    // no billboards at all (far::make_impostor needs at least one).
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
    std::vector<far::ImpostorBin> billboards; // .rock = catalogue index
    int mesh_count = 0, billboard_count = 0;
};
struct NearWeights { float mesh = 0, billboard = 0; };
// Pure tier rule for camera distance d (spec §2): mesh 1 below mesh_gu - fade,
// ramps to 0 at mesh_gu; billboard = 1 - mesh up to billboard_gu - fade, then
// ramps to 0 at billboard_gu; nothing beyond. fade_gu <= 0 is a hard step.
NearWeights near_weights(float d, const NearClassDials& c, float fade_gu);

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
    void clear();                          // cells, contacts, sweep state, cooldowns, ghosts
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
private:
    struct Cell {
        NearClass cls;
        std::vector<NearRock> rocks;
        glm::dvec3 lo{0.0};              // system-space AABB min corner
        double size = 0.0;               // edge (the class's cell_gu when generated)
        bool pinned = false;             // the test cell: never streamed out
        std::vector<std::uint64_t> keys; // pinned only: explicit rock keys
        float r_max = 0.0f;              // largest rock radius (broad phase)
        // Large cells: the step that last saw this cell (0 = none) and how
        // many of its rocks it saw then -- a rock is "fresh" (ghost test)
        // unless the previous step saw it.
        std::uint64_t seen_step = 0;
        std::size_t seen_rocks = 0;
    };
    std::uint64_t key_of(std::uint64_t cell_key, const Cell& c, std::size_t i) const;
    void invalidate_stream_watch();
    // key: mix(source id, class, i, j, k); rock key = mix(cell key, index + 1)
    std::unordered_map<std::uint64_t, Cell> cells_;
    NearDials dials_;
    NearCatalogue cat_;
    std::vector<far::DiscSource> sources_;

    // Incremental streaming (rock-fields perf, 2026-10-03). After a full
    // pass at c_ref, only cells whose distance from c_ref lies within
    // kStreamWatchGu of a threshold can change state while the centre stays
    // within kStreamWatchGu of c_ref (distance to a box is 1-Lipschitz).
    struct GenWatch {                     // per (source, class)
        bool has_ref = false;             // c_ref is the last full pass's centre
        bool valid = false;               // ... and `shell` was recorded there
        glm::dvec3 c_ref{0.0};
        std::vector<glm::i64vec3> shell;  // R - w < dist(c_ref) <= R + w, (i, j, k) order
    };
    std::vector<GenWatch> gen_watch_;     // sources_.size() * 2
    bool drop_valid_ = false;
    glm::dvec3 drop_ref_{0.0};
    std::vector<std::uint64_t> drop_watch_;   // cells that may pass keep: near it, or new

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
