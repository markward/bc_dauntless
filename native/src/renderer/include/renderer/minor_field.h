// native/src/renderer/include/renderer/minor_field.h
// Minor rocks (docs/superpowers/specs/2026-10-01-minor-rocks-design.md, §1, §2).
#pragma once

#include <cstdint>
#include <functional>
#include <map>
#include <optional>
#include <unordered_map>
#include <utility>
#include <vector>

#include <glm/glm.hpp>

#include <renderer/speck.h>

namespace renderer::minors {

enum class Anchor : std::uint8_t { Instance, Point, Free };

struct DebrisSpec {            // a breakup minor (Free clouds only)
    glm::vec3 offset{0.0f};    // GU, relative to the cloud anchor at t0
    glm::vec3 v0{0.0f};        // GU/s outward, decays (debris_damp_seconds)
    float radius = 0.1f;       // GU
    std::uint32_t seed = 0;
};

struct CloudDesc {
    std::uint32_t id = 0;
    Anchor anchor = Anchor::Point;
    std::uint64_t instance_key = 0;      // Anchor::Instance: (index<<32)|generation
    glm::dvec3 point{0.0};               // VIEW space: Point position / Free p0
    glm::vec3 velocity{0.0f};            // Free: GU/s
    double t0 = 0.0;                     // Free: game time of p0
    float shell_inner = 0.0f, shell_outer = 1.0f, falloff = 0.0f;
    int count = 0;
    float r_min = 0.05f, r_max = 0.5f, size_exponent = 2.5f;
    int family = 0;
    std::uint32_t seed = 0;
    float orbit_rate = 0.0f;             // rad/s; a Free cloud freezes it at t0
    bool fade_in = false;
    std::vector<DebrisSpec> debris;
};

struct Minor {                 // one generated instance (immutable after build)
    glm::vec3 offset{0.0f};    // cloud-local GU (orbit/halo/tile); debris: start
    glm::vec3 v0{0.0f};        // debris only
    float radius = 0.1f;       // GU
    glm::vec3 tumble_axis{0.0f, 0.0f, 1.0f};
    float tumble_u = 0.0f;     // [0,1): rate = mix(tumble_min, tumble_max, u)
    float phase = 0.0f;        // initial rotation angle, radians
    float orbit_u = 1.0f;      // [0.5,1], or 0 for debris (no orbit)
    std::uint32_t mesh_u = 0;  // mesh slot = mesh_u % fragment count
    bool debris = false;
};

std::vector<Minor> generate(const CloudDesc& d);   // deterministic, pure

struct Dials {   // defaults MUST equal engine/rocks/minor_dials.py DEFAULTS
    float min_pixel_radius = 1.5f, lod0_pixel_radius = 24.0f;
    float tumble_min = 0.05f, tumble_max = 0.6f;
    float cloud_fade_in_seconds = 1.5f;
    float contact_margin_gu = 0.1f, shove_transfer = 0.6f, shove_min_gups = 0.3f;
    float shove_damp_seconds = 4.0f, shove_tumble = 1.5f;
    int   max_shoves_per_frame = 64;
    float teleport_gu = 20000.0f, contact_cooldown_s = 0.5f;
    float debris_damp_seconds = 6.0f;
};

struct Fragment {
    std::uint64_t lod0 = 0, lod1 = 0;
    float bound_radius_mu = 57.142857f;
    glm::vec3 albedo{0.4f};    // catalogue avg_albedo: the colour of its speck
};

// rows of [R·s | t], render space; `extra.x` is the signed screen-door dither
// (opaque.frag's v_dither: 0 = solid, byte-identical; yzw reserved, 0).
struct InstanceGpu { glm::vec4 row0, row1, row2; glm::vec4 extra{0.0f}; };
static_assert(sizeof(InstanceGpu) == 64, "InstanceGpu is four tightly packed vec4s");

struct Bin { int family = 0; int slot = 0; int lod = 0; std::vector<InstanceGpu> items; };

using AnchorLookup = std::function<bool(std::uint64_t key, glm::vec3& out_render_pos)>;

// The player's contact box (spec §3): the hull AABB in model space, posed by
// the player's RENDER-space instance world (which includes scale).
struct PlayerBox {
    glm::mat4 world{1.0f};        // RENDER-space instance world (incl. scale)
    glm::vec3 center_mu{0.0f};    // model-space AABB centre
    glm::vec3 half_mu{1.0f};      // model-space AABB half extents
};

// The player's oriented contact box in RENDER space for one step.
struct SweepBox {
    glm::vec3 axes[3];     // unit
    glm::vec3 half;        // GU, already inflated by any margin
    float bound = 0.0f;    // |half|
};
// Axes and half extents of `box` posed by its world (which carries scale);
// `inflate` scales the half extents before `margin_gu` is added.
SweepBox sweep_box_of(const PlayerBox& box, float margin_gu, float inflate = 1.0f);
// Closest point on the box centred at `centre`.
glm::vec3 closest_on_box(const SweepBox& b, const glm::vec3& centre, const glm::vec3& p);
// Exact swept distance (golden-section; f is convex for a fixed orientation):
// the minimum over s in [0,1] of |p - closest_on_box(seg0 + seg*s)|; `s_out`
// gets the minimiser (ties prefer s = 1, the current pose).
float sweep_min_distance(const SweepBox& b, const glm::vec3& seg0, const glm::vec3& seg,
                         const glm::vec3& p, float& s_out);

// A shoved minor's persistent response (spec §3).
struct ShoveState { glm::vec3 offset{0.0f}, vel{0.0f}; float spin = 0.0f, spin_rate = 0.0f;
                    double last_contact = -1e9; };
// One touch: velocity along unit `push_dir` from the closing speed
// `rel_speed` (= v_player . push_dir; receding clamps to the floor), spin
// raised to at least shove_tumble, and the contact clock restarted when the
// cooldown has run out. The caller moves `offset` (the positional push).
void apply_shove(ShoveState&, const glm::vec3& push_dir, float rel_speed, double now,
                 const Dials&);
// Integrate one step: the offset persists, velocity and spin decay.
void advance_shove(ShoveState&, float dt, const Dials&);

// One player/minor touch, drained by Python (engine/rocks/minor_contact.py).
struct Contact { glm::dvec3 point_view{0.0}; float radius = 0.0f; float rel_speed = 0.0f; };

struct StepInput {
    double game_time = 0.0;
    glm::dvec3 render_origin{0.0};
    glm::mat4 view{1.0f}, proj{1.0f};
    float viewport_h = 720.0f;
    AnchorLookup anchor_of;              // may be empty: Instance clouds then skip
    std::optional<PlayerBox> player;     // unset: no contact test this step
};

struct Stats { int clouds = 0; int minors = 0; int drawn = 0; int bins = 0; };

class MinorField {
public:
    void set_dials(const Dials& d) { dials_ = d; }
    const Dials& dials() const { return dials_; }
    void set_fragments(int family, std::vector<Fragment> f);
    const std::vector<Fragment>& fragments(int family) const;
    void add_cloud(const CloudDesc& d, double now);   // replaces same id
    void remove_cloud(std::uint32_t id);
    // Instance -> Free, keeping instances and shove state; appends debris.
    void detach(std::uint32_t id, const glm::dvec3& p0_view, const glm::vec3& v,
                double t0, const std::vector<DebrisSpec>& debris);
    void fade_out(std::uint32_t id, float seconds, double now);
    void clear();
    void step(const StepInput& in);
    const std::vector<Bin>& bins() const { return bins_; }
    // Cull, LOD-pick and bin the poses of the last step() against ANY camera,
    // into `out` (cleared first). Reads only cached state, so the host can
    // bin once per drawn target (main view, bridge viewscreen RTT) with that
    // target's own camera and height. `drawn` (optional) gets the instance
    // count. step() bins into bins() through this same function.
    // `specks` (optional, cleared first): with set_specks(true, p_min), every
    // in-frustum minor with p_min <= pixel_r < min_pixel_radius -- the band
    // culled otherwise -- becomes one far-tier speck (far-tier spec §3).
    void build_bins(const glm::mat4& view, const glm::mat4& proj, float viewport_h,
                    std::vector<Bin>& out, int* drawn = nullptr,
                    std::vector<SpeckGpu>* specks = nullptr) const;
    // Far tier: draw the sub-min_pixel_radius band as specks (off by default).
    void set_specks(bool on, float p_min) { specks_on_ = on; speck_p_min_ = p_min; }
    Stats stats() const { return stats_; }
    // Clouds held right now (stats().clouds is as of the last step).
    std::size_t cloud_count() const { return clouds_.size(); }
    // Touches since the last drain (moved out).
    std::vector<Contact> drain_contacts() { return std::exchange(contacts_, {}); }
    // Forget the previous pose. The host MUST call this whenever the player
    // changes or disappears, or the next step sweeps from the stale pose (Task 8).
    void reset_player() { has_prev_ = false; }
    // Test hook: render-space centre of minor `i` of cloud `id` after the last step.
    bool minor_position(std::uint32_t id, std::size_t i, glm::vec3& out) const;
    // TEST-ONLY: overwrite minor `i`'s generated initial rotation angle, so a
    // test can pose a minor exactly (minor_pass_test.cc). No-op when absent.
    void debug_set_phase(std::uint32_t id, std::size_t i, float phase);
private:
    using Shove = ShoveState;
    struct Cloud {
        CloudDesc desc; std::vector<Minor> minors;
        std::unordered_map<std::uint32_t, Shove> shoves;
        double born = 0.0; bool fading_in = false;
        double fade_out_start = -1.0; float fade_out_seconds = 0.0f;
        std::vector<glm::vec3> pos;    // last step, render space
        glm::vec3 anchor_render{0.0f}; bool anchor_ok = false;
    };
    Dials dials_;
    bool specks_on_ = false;
    float speck_p_min_ = 0.25f;
    std::unordered_map<int, std::vector<Fragment>> fragments_;
    std::map<std::uint32_t, Cloud> clouds_;     // ordered: deterministic bins
    std::vector<Bin> bins_;
    Stats stats_;
    void step_contact(const PlayerBox& box, const glm::dvec3& render_origin,
                      double t, double dt, float tau);
    double last_time_ = -1.0;
    bool stepped_ = false;                // last_time_ is valid
    std::vector<Contact> contacts_;
    bool has_prev_ = false;
    glm::dvec3 prev_center_view_{0.0};    // player box centre, VIEW space
};

}  // namespace renderer::minors
