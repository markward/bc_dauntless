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
    glm::vec3 albedo{0.4f};       // mean avg_albedo of `rocks` (puff colour)
};

struct DiscSource {
    // Disc: a belt (table + scale height). Sphere: a BC tile field
    // (AsteroidField) -- a(x) = 1 within sphere_radius_gu * (1 -
    // sphere_edge_frac) of the centre, a linear ramp to 0 at sphere_radius_gu
    // (table / scale height unused). Added 2026-10-02.
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
    // Field noise (every shape since rock-fields, 2026-10-02): the density is
    // a(x) * m(x), m = max(0, 1 + noise_contrast * (2 fbm(x_local /
    // noise_scale_gu) - 1)), x_local = x - centre (fixed to the field),
    // contrast clamped to [0, 1]. Off (m == 1, byte-identical) when scale <= 0,
    // contrast == 0 or octaves <= 0.
    float noise_scale_gu = 0.0f;
    float noise_contrast = 0.0f;
    int noise_octaves = 0;
    // spike/rock-specks (2026-10-04), both off by default (byte-identical):
    // noise_sharpness stretches the fbm about 0.5 before m (clamped to
    // [0, 1]), so > 1 opens voids and packs clumps; m's bound is unchanged.
    // shape_warp (sphere only, < 0.9) scales the distance from the centre by
    // 1 + shape_warp * (2 fbm(x_local / shape_warp_scale_gu, 2 octaves) - 1),
    // so the outline is lumpy instead of a sphere; the field then reaches out
    // to sphere_radius_gu / (1 - shape_warp) (sphere_outer_r).
    float noise_sharpness = 1.0f;
    float shape_warp = 0.0f;
    float shape_warp_scale_gu = 0.0f;
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
// An upper bound of density_a anywhere in the axis-aligned cube (centre
// `centre`, half-edge `half`), tested on the cube's bounding sphere. Disc:
// the table's max over the sphere's radial span times the Gaussian at its
// nearest |z|. Sphere: 1 when the bounding sphere reaches inside
// sphere_radius_gu, else 0. 0 means no point of the cube has density.
float a_bound(const DiscSource& s, const glm::dvec3& centre, double half);

// ---- Field noise (every source) ------------------------------------------

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
// A sphere source's outermost reach: sphere_radius_gu / (1 - shape_warp).
double sphere_outer_r(const DiscSource& s);

// ---- Per-camera build (spec §1-3) ----------------------------------------

struct CatalogueRock { glm::vec3 avg_albedo{0.4f}; bool has_impostor = false; };

// A mission/breakup rock that exists as a scenegraph instance.
struct FlaggedRock { std::uint64_t key; int index; /*-1 = no impostor*/ float radius_mu; };

struct FarDials {
    TierDials tiers;
    float speck_gain = 4.0f;    // Mark, live 2026-10-02: "about 4"
};

// One impostor instance (rock-blend, 2026-10-03). The shader draws a
// camera-facing quad and samples the three blended views at the rock-frame
// point each fragment's view ray crosses that view's image plane, so it needs
// the rock's own axes, not a per-view basis.
struct ImpostorGpu {
    glm::vec4 centre_half;     // xyz render, w half-size GU (the bake's half extent)
    glm::vec4 axis_x_grid;     // xyz: the rock's glTF +x axis in render space; w: atlas grid (views per side)
    glm::vec4 axis_y_dither;   // xyz: the rock's glTF +y axis in render space; w: signed dither
    glm::vec4 views;           // xyz: the three blended view indices (far::view_blend); w: 0
    glm::vec4 weights;         // xyz: their weights (sum 1, heaviest first); w: 0
};
static_assert(sizeof(ImpostorGpu) == 80, "ImpostorGpu is an 80-byte GPU instance");

struct ImpostorBin { int rock = 0; std::vector<ImpostorGpu> items; };

// Rock fade (2026-10-03): a TRANSLUCENT impostor (FarPass::
// render_impostors_blended) keeps its signed dither in axis_y_dither.w and draws
// with alpha = the coverage that dither's screen door would have kept: -d
// fading in (d < 0), 1 - d fading out (d > 0), 1 when solid (d == 0).
// opaque.frag's blend path computes exactly this; keep the two identical.
float impostor_fade_alpha(float dither);

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

// ---- Octahedral view layout + blend (rock-blend, 2026-10-03) --------------
// The impostor bake's views are the grid points of an octahedral map of the
// sphere (glTF frame, pole axis +y), CORNER-sampled: view v = j * grid + i
// sits at oct (a, b) = (-1 + 2i/(grid-1), -1 + 2j/(grid-1)) and is atlas cell
// (i, j). Corner sampling puts grid points ON the map's folds (the square's
// border and its corners), so the border views come in mirror pairs with
// bit-identical directions -- the price of a lookup with no search: the
// eye's oct point lies in one grid cell, and the cell's triangle around it
// gives the 3 views and their barycentric weights. Continuous everywhere,
// including across the folds (on a fold the weights reduce to the
// edge-linear blend of two border views, the same from either side).
// Copied in native/src/rockgen/src/impostor.cc (oct_decode), not linked.

// sqrt(view_count) if it is a whole number >= 2, else 0 (no usable layout).
int impostor_grid_for(std::size_t view_count);
// The oct-map point of unit direction d (glTF frame), in [-1, 1]^2.
glm::vec2 oct_encode(const glm::vec3& d);
// The unit direction of oct-map point f (the inverse of oct_encode).
glm::vec3 oct_decode(const glm::vec2& f);
// View `view`'s direction (glTF frame) for a grid x grid layout.
glm::vec3 oct_view_dir(int view, int grid);
std::vector<glm::vec3> oct_view_dirs(int grid);

// Up to three baked views and weights (>= 0, summing to 1) for an eye in
// unit direction `eye_dir_gltf` from the rock's centre (rock glTF frame).
// Exactly one weight is 1 at a baked direction. Unused slots weigh 0.
struct ViewBlend { int view[3] = {0, 0, 0}; float w[3] = {1.0f, 0.0f, 0.0f}; };
ViewBlend view_blend(const glm::vec3& eye_dir_gltf, int grid);

// The impostor instance for a rock at render-space centre c, rotation R
// (rock -> render), radius r, seen from `eye`, with signed dither `dither`
// (0 = solid; >0 a mesh-side fade keeping the upper 1-d; <0 an impostor
// fading in keeping the lower |d|). Blends the baked views around the eye
// (far::view_blend). `view_dirs_gltf` must be an oct layout (square count).
ImpostorGpu make_impostor(const std::vector<glm::vec3>& view_dirs_gltf, const glm::vec3& eye,
                          const glm::vec3& c, const glm::mat3& R, float r, float dither);

// The per-view-set part of make_impostor, computed once per view-direction
// set (rock fields: per catalogue / view-dirs push, not per sprite).
struct ImpostorViews {
    std::vector<glm::vec3> dirs;   // glTF frame
    int grid = 0;                  // impostor_grid_for(dirs.size()); 0: unusable, draw no impostors
};
ImpostorViews make_impostor_views(const std::vector<glm::vec3>& view_dirs_gltf);
// Identical to make_impostor(views.dirs, ...); views.grid must be >= 2.
// Scalar for the Debug build's hot loops.
ImpostorGpu make_impostor(const ImpostorViews& views, const glm::vec3& eye, const glm::vec3& c,
                          const glm::mat3& R, float r, float dither);

class FarField {
public:
    void set_dials(const FarDials&);
    const FarDials& dials() const { return dials_; }
    void set_catalogue(std::vector<CatalogueRock>, std::vector<glm::vec3> view_dirs_gltf);
    const std::vector<CatalogueRock>& catalogue() const { return catalogue_; }
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
    ImpostorViews views_;
    std::vector<DiscSource> sources_;
    std::vector<DiscSource> active_;     // sources_ whose frame is the viewed one
    std::vector<FlaggedRock> rocks_;
    std::optional<std::string> frame_;
    glm::dvec3 anchor_{0.0};
};

}  // namespace renderer::far
