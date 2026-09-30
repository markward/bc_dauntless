// native/src/rockgen/src/surface.cc
//
// Per-family surface bake: a tileable-in-longitude base colour + tangent-
// space normal map, ported from feat/procedural-asteroids
// (asteroid_gen.cc's generate_asteroid_surface); the per-variant procedural
// tint is replaced by the recipe's color_a/color_b palette plus a large-scale
// fbm tint, and the height field's parameters (detail_octaves, detail_scale,
// normal_strength) come from the family instead of fixed constants.
//
// The height field is sampled through uv_sphere.h's uv_to_direction, the
// EXACT inverse of shape.cc's direction_to_uv, so a texel and the mesh vertex
// that lands on it via the same UV always agree on what "height" means there.
#include <rockgen/surface.h>

#include "noise.h"
#include "uv_sphere.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <thread>
#include <vector>

namespace rockgen {
namespace {

constexpr float kPiF = 3.14159265358979323846f;

// XOR offsets decorrelate the detail-height field from the large-scale tint
// field and from shape.cc's own displacement noise (which XORs nothing extra
// -- see draw_params in shape.cc), even though all three ultimately derive
// from the same per-rock seed.
constexpr std::uint32_t kDetailSeedOffset = 0x5bf03635u;
constexpr std::uint32_t kTintSeedOffset = 0xa1b2c3d4u;

// The tint is "large-scale": one full sphere wrap sees only a couple of
// bumps, well below the detail field's own frequency (family detail_scale,
// authored around 7 in the catalogue recipe).
constexpr float kTintScale = 0.6f;
constexpr int kTintOctaves = 3;
constexpr float kTintStrength = 0.10f;   // +-10%

std::uint32_t fold_seed(std::uint64_t seed) {
    return static_cast<std::uint32_t>(seed) ^ static_cast<std::uint32_t>(seed >> 32);
}

float height_at(float u, float v, std::uint32_t seed, const FamilyParams& f) {
    const glm::vec3 dir = detail::uv_to_direction(u, v);
    return detail::fbm(dir * f.detail_scale, seed ^ kDetailSeedOffset, f.detail_octaves);
}

float tint_at(float u, float v, std::uint32_t seed) {
    const glm::vec3 dir = detail::uv_to_direction(u, v);
    return detail::fbm(dir * kTintScale, seed ^ kTintSeedOffset, kTintOctaves);
}

/// Bakes texel rows [y0, y1) of both images. Each thread gets a disjoint
/// row range and touches no pixel outside it, so the result does not depend
/// on how many threads ran or in what order they finished.
void bake_rows(assets::Image& base, assets::Image& normal, int y0, int y1,
               const FamilyParams& f, std::uint32_t seed, int n) {
    const float du = 1.0f / static_cast<float>(n);
    for (int y = y0; y < y1; ++y) {
        const float v = (static_cast<float>(y) + 0.5f) / static_cast<float>(n);
        for (int x = 0; x < n; ++x) {
            const float u = (static_cast<float>(x) + 0.5f) / static_cast<float>(n);
            const size_t i = (static_cast<size_t>(y) * n + x) * 3;

            const float h = height_at(u, v, seed, f);
            const float tint = 1.0f + (tint_at(u, v, seed) - 0.5f) * 2.0f * kTintStrength;

            glm::vec3 color = glm::mix(f.color_a, f.color_b, h) * tint;
            color = glm::clamp(color, 0.0f, 1.0f);
            base.pixels[i + 0] = static_cast<std::uint8_t>(color.r * 255.0f);
            base.pixels[i + 1] = static_cast<std::uint8_t>(color.g * 255.0f);
            base.pixels[i + 2] = static_cast<std::uint8_t>(color.b * 255.0f);

            // Central differences, wrapping in u so the seam stays continuous
            // (v is a pole; clamp rather than wrap there).
            const float u0 = u - du < 0.0f ? u - du + 1.0f : u - du;
            const float u1 = u + du > 1.0f ? u + du - 1.0f : u + du;
            const float hl = height_at(u0, v, seed, f);
            const float hr = height_at(u1, v, seed, f);
            const float hd = height_at(u, glm::clamp(v - du, 0.0f, 1.0f), seed, f);
            const float hu = height_at(u, glm::clamp(v + du, 0.0f, 1.0f), seed, f);

            glm::vec3 nrm(-(hr - hl) * f.normal_strength,
                          -(hu - hd) * f.normal_strength,
                          1.0f);
            nrm = glm::normalize(nrm);
            normal.pixels[i + 0] = static_cast<std::uint8_t>(glm::clamp(nrm.x * 0.5f + 0.5f, 0.0f, 1.0f) * 255.0f);
            normal.pixels[i + 1] = static_cast<std::uint8_t>(glm::clamp(nrm.y * 0.5f + 0.5f, 0.0f, 1.0f) * 255.0f);
            normal.pixels[i + 2] = static_cast<std::uint8_t>(glm::clamp(nrm.z * 0.5f + 0.5f, 0.0f, 1.0f) * 255.0f);
        }
    }
}

}  // namespace

RockSurface generate_rock_surface(const RockSpec& spec) {
    const FamilyParams& f = *spec.family;
    const int n = spec.kind->texture_size;
    const std::uint32_t seed = fold_seed(spec.seed);

    RockSurface out;
    out.base_color.width = out.base_color.height = static_cast<std::uint32_t>(n);
    out.base_color.format = assets::Image::Format::RGB8;
    out.base_color.pixels.assign(static_cast<size_t>(n) * n * 3, 0);
    out.normal.width = out.normal.height = static_cast<std::uint32_t>(n);
    out.normal.format = assets::Image::Format::RGB8;
    out.normal.pixels.assign(static_cast<size_t>(n) * n * 3, 0);

    // Fixed disjoint row bands: however many threads run, every texel is
    // written by exactly one of them and the bands never overlap.
    const unsigned hw = std::max(1u, std::thread::hardware_concurrency());
    const int n_threads = static_cast<int>(std::min<unsigned>(hw, static_cast<unsigned>(n)));
    const int rows_per = (n + n_threads - 1) / n_threads;
    std::vector<std::thread> threads;
    threads.reserve(static_cast<size_t>(n_threads));
    for (int t = 0; t < n_threads; ++t) {
        const int y0 = t * rows_per;
        const int y1 = std::min(n, y0 + rows_per);
        if (y0 >= y1) continue;
        threads.emplace_back(bake_rows, std::ref(out.base_color), std::ref(out.normal),
                             y0, y1, std::cref(f), seed, n);
    }
    for (std::thread& th : threads) th.join();

    // avg_albedo: mean base colour weighted by cos(latitude), the sphere's
    // area element under this equirectangular parameterisation.
    glm::dvec3 accum(0.0);
    double weight_sum = 0.0;
    for (int y = 0; y < n; ++y) {
        const float v = (static_cast<float>(y) + 0.5f) / static_cast<float>(n);
        const float lat = (v - 0.5f) * kPiF;
        const double w = static_cast<double>(std::cos(lat));
        for (int x = 0; x < n; ++x) {
            const size_t i = (static_cast<size_t>(y) * n + x) * 3;
            accum.r += w * out.base_color.pixels[i + 0] / 255.0;
            accum.g += w * out.base_color.pixels[i + 1] / 255.0;
            accum.b += w * out.base_color.pixels[i + 2] / 255.0;
            weight_sum += w;
        }
    }
    if (weight_sum > 0.0) accum /= weight_sum;
    out.avg_albedo = glm::vec3(accum);

    return out;
}

}  // namespace rockgen
