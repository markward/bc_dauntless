// native/src/renderer/include/renderer/minor_field.h
// Minor rocks (docs/superpowers/specs/2026-10-01-minor-rocks-design.md, §1, §2).
#pragma once

#include <cstdint>
#include <functional>
#include <map>
#include <optional>
#include <unordered_map>
#include <vector>

#include <glm/glm.hpp>

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
    float orbit_rate = 0.0f;             // rad/s
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

struct Fragment { std::uint64_t lod0 = 0, lod1 = 0; float bound_radius_mu = 57.142857f; };

struct InstanceGpu { glm::vec4 row0, row1, row2; };   // rows of [R·s | t], render space

struct Bin { int family = 0; int slot = 0; int lod = 0; std::vector<InstanceGpu> items; };

using AnchorLookup = std::function<bool(std::uint64_t key, glm::vec3& out_render_pos)>;

// The player's contact box (spec §3): the hull AABB in model space, posed by
// the player's RENDER-space instance world (which includes scale).
struct PlayerBox {
    glm::mat4 world{1.0f};        // RENDER-space instance world (incl. scale)
    glm::vec3 center_mu{0.0f};    // model-space AABB centre
    glm::vec3 half_mu{1.0f};      // model-space AABB half extents
};

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
    Stats stats() const { return stats_; }
    // Touches since the last drain (moved out).
    std::vector<Contact> drain_contacts() { return std::move(contacts_); }
    void reset_player() { has_prev_ = false; }   // forget the previous pose
    // Test hook: render-space centre of minor `i` of cloud `id` after the last step.
    bool minor_position(std::uint32_t id, std::size_t i, glm::vec3& out) const;
private:
    struct Shove { glm::vec3 offset{0.0f}, vel{0.0f}; float spin = 0.0f, spin_rate = 0.0f;
                   double last_contact = -1e9; };
    struct Cloud {
        CloudDesc desc; std::vector<Minor> minors;
        std::unordered_map<std::uint32_t, Shove> shoves;
        double born = 0.0; bool fading_in = false;
        double fade_out_start = -1.0; float fade_out_seconds = 0.0f;
        std::vector<glm::vec3> pos;    // last step, render space
        glm::vec3 anchor_render{0.0f}; bool anchor_ok = false;
    };
    Dials dials_;
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
