// native/src/renderer/include/renderer/far_field.h
// Far tier (docs/superpowers/specs/2026-10-01-far-tier-design.md, §2-3).
#pragma once
#include <cstddef>
#include <cstdint>
#include <functional>
#include <optional>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>
#include <glm/glm.hpp>
#include <glm/gtc/type_precision.hpp>
#include <renderer/far_math.h>
#include <renderer/speck.h>

namespace renderer::far {

struct Population {
    int kind = 0;                 // 0 = minor (catalogue fragment), 1 = major
    float density_at_1 = 0.0f;    // rocks / GU^3 at a == 1
    float a_lo = 0.0f, a_hi = 1.0f;   // n = density_at_1 * clamp((a-a_lo)/(a_hi-a_lo))
    PowerLaw size;
    std::vector<int> rocks;       // catalogue indices
    std::vector<float> weights;   // parallel to rocks
    glm::vec3 albedo{0.4f};       // mean avg_albedo of `rocks` (haze colour)
};

struct DiscSource {
    // Disc: a belt (table + scale height). Sphere: a BC tile field
    // (AsteroidField) -- a(x) = 1 within sphere_radius_gu * (1 -
    // sphere_edge_frac) of the centre, a linear ramp to 0 at sphere_radius_gu
    // (table / scale height unused). Tile-field haze, added 2026-10-02.
    enum class Shape : std::uint8_t { Disc, Sphere };
    std::uint32_t id = 0;
    std::string frame;            // system name; active only when it is the viewed frame
    glm::dvec3 centre{0.0};       // system coordinates (view coordinates when view_space)
    Shape shape = Shape::Disc;
    bool procedural = true;       // false: FarField::build generates no rocks for it
    // true: `centre` is in the viewed set's VIEW space and the source is
    // active whenever it was pushed, frame key or not (refresh_active puts it
    // into system coordinates as centre + anchor).
    bool view_space = false;
    float sphere_radius_gu = 0.0f;
    float sphere_edge_frac = 0.2f;
    float gain_scale = 1.0f;      // multiplies FarDials::haze_gain for this source
    float brightness = 1.0f;      // scales the haze COLOUR only (alpha unchanged)
    glm::vec3 normal{0.0f, 0.0f, 1.0f};
    std::vector<glm::vec2> table; // (r_gu, a), sorted by r
    float outer_fade_gu = 20000.0f;
    float scale_height_frac = 0.03f, scale_height_min_gu = 1000.0f;
    std::uint32_t seed = 0;
    std::vector<glm::dvec4> explicit_regions;   // xyz centre (system), w radius
    std::vector<Population> pops;
};

float table_a(const DiscSource& s, float rho);
float scale_height(const DiscSource& s, float rho);
float density_a(const DiscSource& s, const glm::dvec3& x_sys);
float pop_density(const Population& p, float a);

// ---- Haze (spec §2 "Haze") ------------------------------------------------

struct HazeSample { glm::vec3 rgb{0}; float alpha = 0; };

// The ray interval [t0, t1] (t from `origin_sys` along unit `dir`) inside the
// disc's slab (|z| <= slab_sigmas * H at the outer radius) and its outer
// radius (last table row + outer_fade_gu), clipped to [0, t_max]. False when
// empty (or the table is). far_haze.frag MUST compute exactly the same
// interval (same slab at the outer radius, same cylinder): change both or
// neither -- FarPassGLTest.HazeShaderMatchesTheCpuReference pins them.
bool haze_interval(const DiscSource& s, const glm::dvec3& origin_sys, const glm::vec3& dir,
                   float t_max, float slab_sigmas, double& t0, double& t1);

// CPU twin of far_haze.frag (spec §2 "Haze"): march `steps` midpoint samples
// over the ray's interval inside the source (disc slab + outer radius, or the
// sphere), from t=0 to t_max; at each, dtau = gain * s.gain_scale * sum_pop
// n(a) * mean_cross_section(size) * dt; rgb += T * (1 - exp(-dtau)) *
// albedo_mix * light * s.brightness; T *= exp(-dtau). Returns premultiplied
// rgb and alpha = 1 - T (brightness touches the colour only). albedo_mix is
// the populations' albedo weighted by n * sigma at the sample. No pixel cut
// (ruling R16): the whole cross-section at every distance, so the result does
// not depend on the camera's k -- it also covers speck-tier rocks, a
// negligible double count accepted for resolution independence.
HazeSample haze_column(const DiscSource& s, const glm::dvec3& origin_sys,
                       const glm::vec3& dir, float t_max, float slab_sigmas, int steps,
                       float gain, const glm::vec3& light);

struct GenParams { float k_ref = 1713.0f, p_min = 0.25f; int size_classes = 4, cells_per_range = 4; };

struct ClassBin { float r_lo = 0, r_hi = 0, share = 0, cell_gu = 1; };
std::vector<ClassBin> size_classes(const Population& p, const GenParams& g);

struct FarRock {
    glm::dvec3 pos_sys{0.0};
    float radius = 0.0f;
    int rock = 0;                 // catalogue index
    glm::vec3 tumble_axis{0.0f, 0.0f, 1.0f};
    float tumble_rate = 0.0f;     // rad/s
    float phase = 0.0f;           // rad
};

std::vector<FarRock> generate_cell(const DiscSource& s, int pop, int cls,
                                   const glm::i64vec3& ijk, const GenParams& g);

// ---- Per-camera build (spec §1-3) ----------------------------------------

struct CatalogueRock { glm::vec3 avg_albedo{0.4f}; bool has_impostor = false; };

// A mission/breakup rock that exists as a scenegraph instance.
struct FlaggedRock { std::uint64_t key; int index; /*-1 = no impostor*/ float radius_mu; };

struct FarDials {
    TierDials tiers;
    GenParams gen;
    int max_far_rocks = 60000;
    int cell_cache_max = 32768;
    float slab_sigmas = 4.0f;
    float speck_gain = 1.0f;
    float haze_gain = 270.0f;   // R14: alpha ~0.15 forward from mid-band (spec §2)
    int haze_steps = 24;
    int max_cells_per_axis = 17;   // per class: enumeration spans at most this many cells per axis
};

struct ImpostorGpu {
    glm::vec4 centre_half;   // xyz render, w half-size GU
    glm::vec4 right_view;    // xyz right_w, w = view index
    glm::vec4 up_dither;     // xyz up_w, w = signed dither
};
static_assert(sizeof(ImpostorGpu) == 48, "ImpostorGpu is a 48-byte GPU instance");

struct ImpostorBin { int rock = 0; std::vector<ImpostorGpu> items; };

struct FarOutput {
    std::vector<ImpostorBin> impostors;   // ascending catalogue index
    std::vector<SpeckGpu> specks;
    std::vector<std::pair<std::uint64_t, float>> fades;   // per flagged rock: 1 - mesh weight
    int generated = 0;   // rocks fetched from walked cells
    int cells = 0;       // cells walked
};

using InstanceLookup = std::function<bool(std::uint64_t key, glm::mat4& world)>;

struct BuildInput {
    glm::mat4 view{1}, proj{1};
    float viewport_h = 720;
    glm::dvec3 render_origin{0.0};
    double game_time = 0.0;
    InstanceLookup world_of;
};

// The impostor bake's view basis: identical rule to
// native/src/rockgen/src/impostor.cc:make_basis (copied, not linked).
struct ViewBasis { glm::vec3 dir, right, up; };
ViewBasis make_view_basis(const glm::vec3& dir);

// glTF -> BC model axes: (x,y,z) -> (-x,z,y). Proper (det +1) and its own inverse.
glm::mat3 gltf_to_bc();

class FarField {
public:
    void set_dials(const FarDials&);
    const FarDials& dials() const { return dials_; }
    void set_catalogue(std::vector<CatalogueRock>, std::vector<glm::vec3> view_dirs_gltf);
    // Catalogue rock `index` has no usable impostor (its atlas failed to
    // load): flagged rocks of it keep their mesh to speck_hi. Out of range: no-op.
    void drop_impostor(int index);
    void set_sources(std::vector<DiscSource>);
    void set_rocks(std::vector<FlaggedRock>);
    void set_frame(std::optional<std::string> system, const glm::dvec3& anchor_sys);
    void clear();   // sources, rocks, frame, cache; keeps catalogue
    void build(const BuildInput&, FarOutput&);

    std::size_t source_count() const { return sources_.size(); }
    std::size_t rock_count() const { return rocks_.size(); }
    std::size_t cached_cells() const { return cache_.size(); }
    const std::vector<DiscSource>& active_sources() const { return active_; }
    glm::dvec3 anchor() const { return anchor_; }

private:
    struct CachedCell { std::vector<FarRock> rocks; std::uint64_t last_used = 0; };
    const std::vector<FarRock>& fetch(const DiscSource& s, int pop, int cls, const glm::i64vec3& ijk);
    void evict();
    void refresh_active();

    FarDials dials_;
    std::vector<CatalogueRock> catalogue_;
    std::vector<glm::vec3> view_dirs_;
    std::vector<DiscSource> sources_;
    std::vector<DiscSource> active_;     // sources_ whose frame is the viewed one
    std::vector<FlaggedRock> rocks_;
    std::optional<std::string> frame_;
    glm::dvec3 anchor_{0.0};
    std::unordered_map<std::uint64_t, CachedCell> cache_;
    std::uint64_t frame_counter_ = 0;
};

}  // namespace renderer::far
