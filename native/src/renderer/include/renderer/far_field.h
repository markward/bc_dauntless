// native/src/renderer/include/renderer/far_field.h
// Far tier (docs/superpowers/specs/2026-10-01-far-tier-design.md, §2-3).
#pragma once
#include <cstddef>
#include <cstdint>
#include <functional>
#include <optional>
#include <string>
#include <utility>
#include <vector>
#include <glm/glm.hpp>
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
    // false: not a belt (a tile field). Since rock-fields (2026-10-02) the
    // far tier generates no rocks for ANY source; the flag rides along for
    // the near/mid bands.
    bool procedural = true;
    // true: `centre` is in the viewed set's VIEW space and the source is
    // active whenever it was pushed, frame key or not (refresh_active puts it
    // into system coordinates as centre + anchor).
    bool view_space = false;
    float sphere_radius_gu = 0.0f;
    float sphere_edge_frac = 0.2f;
    float gain_scale = 1.0f;      // multiplies FarDials::haze_gain for this source
    float brightness = 1.0f;      // scales the haze COLOUR only (alpha unchanged)
    // Haze noise (every shape since rock-fields, 2026-10-02): the density is
    // a(x) * m(x), m = max(0, 1 + noise_contrast * (2 fbm(x_local /
    // noise_scale_gu) - 1)), x_local = x - centre (fixed to the field),
    // contrast clamped to [0, 1]. Off (m == 1, byte-identical) when scale <= 0,
    // contrast == 0 or octaves <= 0.
    float noise_scale_gu = 0.0f;
    float noise_contrast = 0.0f;
    int noise_octaves = 0;
    int steps = 0;                // haze march steps; 0 = FarDials::haze_steps
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
// An upper bound of density_a anywhere in the axis-aligned cube (centre
// `centre`, half-edge `half`), tested on the cube's bounding sphere. Disc:
// the table's max over the sphere's radial span times the Gaussian at its
// nearest |z|. Sphere: 1 when the bounding sphere reaches inside
// sphere_radius_gu, else 0. 0 means no point of the cube has density.
float a_bound(const DiscSource& s, const glm::dvec3& centre, double half);

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

// ---- Haze noise (every source; keep identical with far_haze.frag) --------

// 32-bit PCG output hash.
std::uint32_t haze_hash(std::uint32_t v);
// 3D value noise in [0, 1]: hashed lattice values (seeded), trilinear with a
// smoothstep fade.
float haze_value_noise(const glm::vec3& p, std::uint32_t seed);
// haze_value_noise with the seed already hashed (haze_hash(seed)):
// haze_value_noise(p, seed) == haze_value_noise_h(p, haze_hash(seed)).
float haze_value_noise_h(const glm::vec3& p, std::uint32_t hashed_seed);
// `octaves` octaves of haze_value_noise (lacunarity 2, gain 0.5), normalised
// to [0, 1]. octaves <= 0 gives 0.5.
float haze_fbm(const glm::vec3& p, int octaves, std::uint32_t seed);
// The density modulation m(x) at system point x (see DiscSource), for both
// shapes; exactly 1 when the noise is off. noise_contrast is clamped to
// [0, 1].
float haze_noise_m(const DiscSource& s, const glm::dvec3& x_sys);
// The ONE density every band samples (rock-fields spec R1): a(x) * m(x).
float field_density(const DiscSource& s, const glm::dvec3& x_sys);
// Upper bound of m for rejection sampling: 1 + clamp(noise_contrast, 0, 1)
// when the noise is on, else 1.
float noise_m_bound(const DiscSource& s);
// The march steps for `s`: its own `steps` clamped to [1, 64] when set, else
// `global_steps` unchanged.
int haze_steps_for(const DiscSource& s, int global_steps);

// ---- Per-camera build (spec §1-3) ----------------------------------------

struct CatalogueRock { glm::vec3 avg_albedo{0.4f}; bool has_impostor = false; };

// A mission/breakup rock that exists as a scenegraph instance.
struct FlaggedRock { std::uint64_t key; int index; /*-1 = no impostor*/ float radius_mu; };

struct FarDials {
    TierDials tiers;
    float slab_sigmas = 4.0f;
    float speck_gain = 4.0f;    // Mark, live 2026-10-02: "about 4"
    float haze_gain = 270.0f;   // R14: alpha ~0.15 forward from mid-band (spec §2)
    int haze_steps = 24;
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

// The impostor instance for a rock at render-space centre c, rotation R
// (rock -> render), radius r, seen from `eye`, with signed dither `dither`
// (0 = solid; >0 a mesh-side fade keeping the upper 1-d; <0 an impostor
// fading in keeping the lower |d|). Chooses the baked view nearest the eye.
// `view_dirs_gltf` must be non-empty.
ImpostorGpu make_impostor(const std::vector<glm::vec3>& view_dirs_gltf, const glm::vec3& eye,
                          const glm::vec3& c, const glm::mat3& R, float r, float dither);

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
    void clear();   // sources, rocks, frame; keeps catalogue
    void build(const BuildInput&, FarOutput&);

    std::size_t source_count() const { return sources_.size(); }
    std::size_t rock_count() const { return rocks_.size(); }
    const std::vector<DiscSource>& active_sources() const { return active_; }
    glm::dvec3 anchor() const { return anchor_; }

private:
    void refresh_active();

    FarDials dials_;
    std::vector<CatalogueRock> catalogue_;
    std::vector<glm::vec3> view_dirs_;
    std::vector<DiscSource> sources_;
    std::vector<DiscSource> active_;     // sources_ whose frame is the viewed one
    std::vector<FlaggedRock> rocks_;
    std::optional<std::string> frame_;
    glm::dvec3 anchor_{0.0};
};

}  // namespace renderer::far
