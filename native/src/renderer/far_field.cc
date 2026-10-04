// native/src/renderer/far_field.cc
#include "renderer/far_field.h"
#include <renderer/glm_exact.h>
#include <algorithm>
#include <cmath>
#include <glm/gtc/matrix_access.hpp>

namespace renderer::far {
namespace {
// (rho, z) of x relative to the disc.
void disc_coords(const DiscSource& s, const glm::dvec3& x, double& rho, double& z) {
    const glm::dvec3 d = x - s.centre;
    const glm::dvec3 n(s.normal);
    z = glm::dot(d, n);
    rho = glm::length(d - n * z);
}

// Frustum planes (Gribb-Hartmann), normalised: as MinorField::build_bins.
struct Frustum {
    glm::vec4 planes[6];
    explicit Frustum(const glm::mat4& vp) {
        const glm::vec4 r0 = glm::row(vp, 0), r1 = glm::row(vp, 1),
                        r2 = glm::row(vp, 2), r3 = glm::row(vp, 3);
        planes[0] = r3 + r0; planes[1] = r3 - r0; planes[2] = r3 + r1;
        planes[3] = r3 - r1; planes[4] = r3 + r2; planes[5] = r3 - r2;
        for (auto& p : planes) p /= glm::length(glm::vec3(p));
    }
    // False when the sphere lies entirely outside any plane.
    bool sphere(const glm::vec3& c, float r) const {
        for (const auto& pl : planes)
            if (glm::dot(glm::vec3(pl), c) + pl.w < -r) return false;
        return true;
    }
};
}  // namespace

float table_a(const DiscSource& s, float rho) {
    const auto& t = s.table;
    if (t.empty()) return 0.0f;
    if (rho <= t.front().x) return t.front().y;
    for (std::size_t i = 1; i < t.size(); ++i)
        if (rho <= t[i].x) {
            const float span = t[i].x - t[i - 1].x;
            const float u = span > 0.0f ? (rho - t[i - 1].x) / span : 1.0f;
            return t[i - 1].y + (t[i].y - t[i - 1].y) * u;
        }
    if (!(s.outer_fade_gu > 0.0f)) return 0.0f;
    const float u = (rho - t.back().x) / s.outer_fade_gu;
    return u >= 1.0f ? 0.0f : t.back().y * (1.0f - u);
}

float scale_height(const DiscSource& s, float rho) {
    return std::max(s.scale_height_frac * rho, s.scale_height_min_gu);
}

// Sphere density (a tile field): 1 within R(1 - edge_frac), a linear
// ramp to 0 at R.
float sphere_warp_factor(const DiscSource& s, const glm::dvec3& x) {
    if (!(s.shape_warp > 0.0f) || !(s.shape_warp_scale_gu > 0.0f)) return 1.0f;
    const glm::vec3 local = glm::vec3(x - s.centre) / s.shape_warp_scale_gu;
    const float n = 2.0f * field_fbm(local, 2, s.seed ^ 0xA5A5A5A5u) - 1.0f;
    return 1.0f + std::min(s.shape_warp, 0.9f) * n;
}

float sphere_a(const DiscSource& s, const glm::dvec3& x) {
    const double R = s.sphere_radius_gu;
    const double d = glm::length(x - s.centre) * static_cast<double>(sphere_warp_factor(s, x));
    if (!(R > 0.0) || d >= R) return 0.0f;
    const double inner = R * (1.0 - std::clamp(static_cast<double>(s.sphere_edge_frac), 0.0, 1.0));
    if (d <= inner) return 1.0f;
    return static_cast<float>((R - d) / (R - inner));
}

float density_a(const DiscSource& s, const glm::dvec3& x) {
    if (s.shape == DiscSource::Shape::Sphere) return sphere_a(s, x);
    double rho, z;
    disc_coords(s, x, rho, z);
    const double H = scale_height(s, static_cast<float>(rho));
    return table_a(s, static_cast<float>(rho)) * static_cast<float>(std::exp(-0.5 * z * z / (H * H)));
}

float a_bound(const DiscSource& s, const glm::dvec3& c, double h) {
    const double hd = h * std::sqrt(3.0);   // the cube's bounding-sphere radius
    if (s.shape == DiscSource::Shape::Sphere) {
        const double R = sphere_outer_r(s);
        return (R > 0.0 && glm::length(c - s.centre) - hd < R) ? 1.0f : 0.0f;
    }
    double rho, z;
    disc_coords(s, c, rho, z);
    const float lo = static_cast<float>(std::max(0.0, rho - hd));
    const float hi = static_cast<float>(rho + hd);
    float amax = std::max(table_a(s, lo), table_a(s, hi));
    for (const auto& row : s.table)
        if (row.x >= lo && row.x <= hi) amax = std::max(amax, row.y);
    const double zmin = std::max(0.0, std::fabs(z) - hd);
    const double H = scale_height(s, hi);
    return amax * static_cast<float>(std::exp(-0.5 * zmin * zmin / (H * H)));
}

// ---- Field noise (every source): the density modulation m and the sphere
// shape warp.
namespace {
constexpr int kMaxNoiseOctaves = 8;      // fbm octave cap

// `hs` is the PRE-HASHED seed (field_hash(seed)), hashed once per octave by
// the caller rather than in each of the 8 lattice calls per noise sample.
float lattice(std::int32_t x, std::int32_t y, std::int32_t z, std::uint32_t hs) {
    const std::uint32_t h =
        field_hash(static_cast<std::uint32_t>(x) ^
                  field_hash(static_cast<std::uint32_t>(y) ^
                            field_hash(static_cast<std::uint32_t>(z) ^ hs)));
    return static_cast<float>(h >> 8) / 16777215.0f;
}
float lerp(float a, float b, float t) { return a + (b - a) * t; }
}  // namespace

std::uint32_t field_hash(std::uint32_t v) {
    const std::uint32_t state = v * 747796405u + 2891336453u;
    const std::uint32_t word = ((state >> ((state >> 28u) + 4u)) ^ state) * 277803737u;
    return (word >> 22u) ^ word;
}

float field_value_noise(const glm::vec3& p, std::uint32_t seed) {
    return field_value_noise_h(p, field_hash(seed));
}

float field_value_noise_h(const glm::vec3& p, std::uint32_t seed) {
    const glm::vec3 fl = glm::floor(p);
    const glm::vec3 f = p - fl;
    const glm::vec3 u = f * f * (3.0f - 2.0f * f);
    const auto x = static_cast<std::int32_t>(fl.x), y = static_cast<std::int32_t>(fl.y),
               z = static_cast<std::int32_t>(fl.z);
    const float x00 = lerp(lattice(x, y, z, seed), lattice(x + 1, y, z, seed), u.x);
    const float x10 = lerp(lattice(x, y + 1, z, seed), lattice(x + 1, y + 1, z, seed), u.x);
    const float x01 = lerp(lattice(x, y, z + 1, seed), lattice(x + 1, y, z + 1, seed), u.x);
    const float x11 = lerp(lattice(x, y + 1, z + 1, seed), lattice(x + 1, y + 1, z + 1, seed), u.x);
    return lerp(lerp(x00, x10, u.y), lerp(x01, x11, u.y), u.z);
}

float field_fbm(const glm::vec3& p, int octaves, std::uint32_t seed) {
    const int n = std::min(octaves, kMaxNoiseOctaves);
    if (n <= 0) return 0.5f;
    float sum = 0.0f, norm = 0.0f, amp = 1.0f;
    glm::vec3 q = p;
    for (int o = 0; o < n; ++o) {
        const std::uint32_t hs = field_hash(seed + static_cast<std::uint32_t>(o) * 0x9E3779B9u);
        sum += amp * field_value_noise_h(q, hs);
        norm += amp;
        amp *= 0.5f;
        q *= 2.0f;
    }
    return sum / norm;
}

float field_noise_m(const DiscSource& s, const glm::dvec3& x) {
    if (!(s.noise_scale_gu > 0.0f) || s.noise_contrast == 0.0f || s.noise_octaves <= 0)
        return 1.0f;
    const float contrast = std::clamp(s.noise_contrast, 0.0f, 1.0f);
    const glm::vec3 local = glm::vec3(x - s.centre) / s.noise_scale_gu;
    float fbm = field_fbm(local, s.noise_octaves, s.seed);
    if (s.noise_sharpness != 1.0f) fbm = std::clamp(0.5f + (fbm - 0.5f) * s.noise_sharpness, 0.0f, 1.0f);
    return std::max(0.0f, 1.0f + contrast * (2.0f * fbm - 1.0f));
}

float field_density(const DiscSource& s, const glm::dvec3& x) {
    return density_a(s, x) * field_noise_m(s, x);
}

float noise_m_bound(const DiscSource& s) {
    if (!(s.noise_scale_gu > 0.0f) || s.noise_contrast == 0.0f || s.noise_octaves <= 0)
        return 1.0f;
    return 1.0f + std::clamp(s.noise_contrast, 0.0f, 1.0f);
}

double sphere_outer_r(const DiscSource& s) {
    const double w = std::clamp(static_cast<double>(s.shape_warp), 0.0, 0.9);
    return s.shape_warp_scale_gu > 0.0f ? s.sphere_radius_gu / (1.0 - w) : s.sphere_radius_gu;
}

bool same_density(const DiscSource& a, const DiscSource& b) {
    return a.seed == b.seed && a.shape == b.shape && a.centre == b.centre &&
           a.sphere_radius_gu == b.sphere_radius_gu && a.sphere_edge_frac == b.sphere_edge_frac &&
           a.noise_scale_gu == b.noise_scale_gu && a.noise_contrast == b.noise_contrast &&
           a.noise_octaves == b.noise_octaves && a.noise_sharpness == b.noise_sharpness &&
           a.shape_warp == b.shape_warp && a.shape_warp_scale_gu == b.shape_warp_scale_gu &&
           a.normal == b.normal && a.table == b.table && a.outer_fade_gu == b.outer_fade_gu &&
           a.scale_height_frac == b.scale_height_frac &&
           a.scale_height_min_gu == b.scale_height_min_gu &&
           a.explicit_regions == b.explicit_regions;
}

ViewBasis make_view_basis(const glm::vec3& dir) {
    // Copy of native/src/rockgen/src/impostor.cc:make_basis — the bake's rule.
    const glm::vec3 up_ref = (std::abs(dir.y) > 0.99f) ? glm::vec3(1.0f, 0.0f, 0.0f)
                                                        : glm::vec3(0.0f, 1.0f, 0.0f);
    const glm::vec3 forward = -dir;   // the direction the bake camera looks
    const glm::vec3 right = glm::normalize(glm::cross(up_ref, forward));
    const glm::vec3 up = glm::cross(forward, right);
    return {dir, right, up};
}

glm::mat3 gltf_to_bc() {
    return glm::mat3(glm::vec3(-1, 0, 0), glm::vec3(0, 0, 1), glm::vec3(0, 1, 0));
}

ImpostorGpu make_impostor(const std::vector<glm::vec3>& view_dirs_gltf, const glm::vec3& eye,
                          const glm::vec3& c, const glm::mat3& R, float r, float dither) {
    return make_impostor(make_impostor_views(view_dirs_gltf), eye, c, R, r, dither);
}

int impostor_grid_for(std::size_t view_count) {
    if (view_count < 4) return 0;
    const int g = static_cast<int>(std::lround(std::sqrt(static_cast<double>(view_count))));
    return static_cast<std::size_t>(g) * static_cast<std::size_t>(g) == view_count ? g : 0;
}

namespace {
float sgn_nz(float v) { return v >= 0.0f ? 1.0f : -1.0f; }   // sign, +1 at 0
}  // namespace

glm::vec2 oct_encode(const glm::vec3& d) {
    const float l1 = std::abs(d.x) + std::abs(d.y) + std::abs(d.z);
    const glm::vec3 p = l1 > 0.0f ? d / l1 : glm::vec3(0, 1, 0);
    if (p.y >= 0.0f) return glm::vec2(p.x, p.z);
    return glm::vec2((1.0f - std::abs(p.z)) * sgn_nz(p.x), (1.0f - std::abs(p.x)) * sgn_nz(p.z));
}

glm::vec3 oct_decode(const glm::vec2& f) {
    // Copied in native/src/rockgen/src/impostor.cc and the impostor shader.
    glm::vec3 n(f.x, 1.0f - std::abs(f.x) - std::abs(f.y), f.y);
    if (n.y < 0.0f) {
        const float x = (1.0f - std::abs(f.y)) * sgn_nz(f.x);
        const float z = (1.0f - std::abs(f.x)) * sgn_nz(f.y);
        n.x = x;
        n.z = z;
    }
    n = glm::normalize(n);
    return n + glm::vec3(0.0f);   // -0 -> +0: mirror twins stay bit-identical
}

glm::vec3 oct_view_dir(int view, int grid) {
    // (2i - (grid-1)) / (grid-1): exactly -1 and 1 at the ends and exactly
    // antisymmetric, so mirror twins decode from exactly negated points.
    const int i = view % grid, j = view / grid;
    const float span = static_cast<float>(grid - 1);
    return oct_decode(glm::vec2(static_cast<float>(2 * i - (grid - 1)) / span,
                                static_cast<float>(2 * j - (grid - 1)) / span));
}

std::vector<glm::vec3> oct_view_dirs(int grid) {
    std::vector<glm::vec3> v;
    if (grid < 2) return v;
    v.reserve(static_cast<std::size_t>(grid * grid));
    for (int k = 0; k < grid * grid; ++k) v.push_back(oct_view_dir(k, grid));
    return v;
}

ViewBlend view_blend(const glm::vec3& eye_dir_gltf, int grid) {
    ViewBlend b;
    if (grid < 2) return b;
    const glm::vec2 f = oct_encode(eye_dir_gltf);
    const float span = static_cast<float>(grid - 1);
    const float gx = std::clamp((f.x * 0.5f + 0.5f) * span, 0.0f, span);
    const float gy = std::clamp((f.y * 0.5f + 0.5f) * span, 0.0f, span);
    const int i0 = std::min(static_cast<int>(gx), grid - 2);
    const int j0 = std::min(static_cast<int>(gy), grid - 2);
    const float fx = gx - static_cast<float>(i0), fy = gy - static_cast<float>(j0);
    auto idx = [grid](int i, int j) { return j * grid + i; };
    if (fx + fy <= 1.0f) {   // lower-left triangle of the cell
        b.view[0] = idx(i0, j0);         b.w[0] = 1.0f - fx - fy;
        b.view[1] = idx(i0 + 1, j0);     b.w[1] = fx;
        b.view[2] = idx(i0, j0 + 1);     b.w[2] = fy;
    } else {                 // upper-right
        b.view[0] = idx(i0 + 1, j0 + 1); b.w[0] = fx + fy - 1.0f;
        b.view[1] = idx(i0, j0 + 1);     b.w[1] = 1.0f - fx;
        b.view[2] = idx(i0 + 1, j0);     b.w[2] = 1.0f - fy;
    }
    // Rounding residue (an encoded baked direction lands a few ulps off its
    // grid point) is dropped, so a baked direction is exactly one view. The
    // step this adds is below 1e-5 of a weight -- invisible in 8 bits.
    float kept = 0.0f;
    for (float& w : b.w) { if (w < 1e-5f) w = 0.0f; kept += w; }
    for (float& w : b.w) w /= kept;   // kept >= 1 - 2e-5: one weight is >= 1/3
    // The heaviest view first (FarPass may skip near-zero tails).
    for (int a = 0; a < 2; ++a)
        for (int c = a + 1; c < 3; ++c)
            if (b.w[c] > b.w[a]) { std::swap(b.w[a], b.w[c]); std::swap(b.view[a], b.view[c]); }
    return b;
}

float impostor_fade_alpha(float dither) {
    if (dither < 0.0f) return -dither;          // fading in: keeps the lower |d|
    if (dither > 0.0f) return 1.0f - dither;    // fading out: keeps the upper 1 - d
    return 1.0f;                                // solid
}

ImpostorViews make_impostor_views(const std::vector<glm::vec3>& view_dirs_gltf) {
    ImpostorViews v;
    v.dirs = view_dirs_gltf;
    v.grid = impostor_grid_for(view_dirs_gltf.size());
    // view_blend picks views by their place in the oct grid, never by these
    // directions: a square count in any other order or layout would sample
    // the wrong views, so it is as unusable as a non-square count. (The
    // catalogue's dirs round-trip through JSON: a loose tolerance.)
    for (int k = 0; v.grid >= 2 && k < v.grid * v.grid; ++k) {
        const glm::vec3 e = view_dirs_gltf[static_cast<std::size_t>(k)] - oct_view_dir(k, v.grid);
        if (!(e.x * e.x + e.y * e.y + e.z * e.z <= 1.0e-6f)) v.grid = 0;
    }
    return v;
}

ImpostorGpu make_impostor(const ImpostorViews& views, const glm::vec3& eye, const glm::vec3& c,
                          const glm::mat3& R, float r, float dither) {
    // The rock's glTF axes in render space: Q = R * gltf_to_bc(), whose
    // columns are -R[0], R[2], R[1] ((x,y,z)_gltf -> (-x,z,y)_BC).
    const glm::vec3 qx(-R[0].x, -R[0].y, -R[0].z);
    const glm::vec3& qy = R[2];
    const glm::vec3& qz = R[1];
    const float wx = eye.x - c.x, wy = eye.y - c.y, wz = eye.z - c.z;
    glm::vec3 e(qx.x * wx + qx.y * wy + qx.z * wz, qy.x * wx + qy.y * wy + qy.z * wz,
                qz.x * wx + qz.y * wy + qz.z * wz);   // transpose(Q) * (eye - c)
    const float len = std::sqrt(e.x * e.x + e.y * e.y + e.z * e.z);
    e = len > 0.0f ? glm::vec3(e.x / len, e.y / len, e.z / len) : glm::vec3(0.0f, 1.0f, 0.0f);
    const ViewBlend b = view_blend(e, views.grid);
    return ImpostorGpu{glm::vec4(c, r * 1.02f), glm::vec4(qx, static_cast<float>(views.grid)),
                       glm::vec4(qy, dither),
                       glm::vec4(static_cast<float>(b.view[0]), static_cast<float>(b.view[1]),
                                 static_cast<float>(b.view[2]), 0.0f),
                       glm::vec4(b.w[0], b.w[1], b.w[2], 0.0f)};
}

void FarField::set_dials(const FarDials& d) { dials_ = d; }

void FarField::set_catalogue(std::vector<CatalogueRock> cat, std::vector<glm::vec3> view_dirs_gltf) {
    catalogue_ = std::move(cat);
    views_ = make_impostor_views(view_dirs_gltf);
}

void FarField::set_sources(std::vector<DiscSource> s) {
    sources_ = std::move(s);
    refresh_active();
}

void FarField::set_rocks(std::vector<FlaggedRock> r) { rocks_ = std::move(r); }

void FarField::set_frame(std::optional<std::string> system, const glm::dvec3& anchor_sys) {
    frame_ = std::move(system);
    anchor_ = anchor_sys;
    refresh_active();
}

void FarField::clear() {
    sources_.clear();
    active_.clear();
    rocks_.clear();
    frame_.reset();
    anchor_ = glm::dvec3(0.0);
}

void FarField::refresh_active() {
    active_.clear();
    for (const auto& s : sources_) {
        if (s.view_space) {
            // View space -> system: + anchor (0 for an unmapped set).
            active_.push_back(s);
            active_.back().centre = s.centre + anchor_;
        } else if (frame_ && s.frame == *frame_) {
            active_.push_back(s);
        }
    }
}

void FarField::drop_impostor(int index) {
    if (index >= 0 && static_cast<std::size_t>(index) < catalogue_.size())
        catalogue_[static_cast<std::size_t>(index)].has_impostor = false;
}

void FarField::build(const BuildInput& in, FarOutput& out) {
    out.impostors.clear();
    out.specks.clear();
    out.fades.clear();

    const float k = pixels_per_gu(in.proj, in.viewport_h);
    const glm::vec3 eye = glm::vec3(glm::inverse(in.view)[3]);
    const Frustum frustum(in.proj * in.view);
    const TierDials& td = dials_.tiers;

    std::vector<std::vector<ImpostorGpu>> bins(catalogue_.size());
    auto albedo_of = [&](int index) {
        return index >= 0 && static_cast<std::size_t>(index) < catalogue_.size()
                   ? catalogue_[static_cast<std::size_t>(index)].avg_albedo
                   : glm::vec3(0.4f);
    };
    auto has_impostor = [&](int index) {
        return index >= 0 && static_cast<std::size_t>(index) < catalogue_.size() &&
               catalogue_[static_cast<std::size_t>(index)].has_impostor;
    };
    // Step 3: the baked views around the eye in the rock's own frame, blended.
    auto emit_impostor = [&](int index, const glm::vec3& c, const glm::mat3& R, float r, float w) {
        if (!has_impostor(index) || views_.grid < 2) return;
        bins[static_cast<std::size_t>(index)].push_back(make_impostor(views_, eye, c, R, r, -w));
    };

    // Step 2: flagged (explicit) rocks.
    // Every flagged rock gets a fade entry; one we cannot place is mesh-only
    // (0), so the host never keeps a stale fade that hides the mesh.
    for (const auto& fr : rocks_) {
        glm::mat4 W(1.0f);
        const bool placed = in.world_of && in.world_of(fr.key, W);
        const float s = placed ? glm::length(glm::vec3(W[0])) : 0.0f;
        if (!(s > 0.0f)) { out.fades.emplace_back(fr.key, 0.0f); continue; }
        const glm::vec3 c(W[3]);
        const glm::mat3 R = glm::mat3(W) / s;
        const float r = fr.radius_mu * s;
        const float d = glm::length(c - eye);
        const float p = r * k / std::max(d, 1e-3f);
        const Kind kind = has_impostor(fr.index) ? Kind::Explicit : Kind::ExplicitNoImpostor;
        const TierWeights w = tier_weights(p, kind, td);
        out.fades.emplace_back(fr.key, 1.0f - w.mesh);   // culled ones too: fade stays current
        if (!frustum.sphere(c, r)) continue;
        if (w.impostor > 0.0f) emit_impostor(fr.index, c, R, r, w.impostor);
        if (w.speck > 0.0f) out.specks.push_back(SpeckGpu{c, p, albedo_of(fr.index), w.speck});
    }

    for (std::size_t i = 0; i < bins.size(); ++i)
        if (!bins[i].empty())
            out.impostors.push_back(ImpostorBin{static_cast<int>(i), std::move(bins[i])});
}

}  // namespace renderer::far
