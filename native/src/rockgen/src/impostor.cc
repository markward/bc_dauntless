// native/src/rockgen/src/impostor.cc
//
// 16-view CPU impostor rasteriser. Single-threaded: correctness (a shared,
// per-view z-buffer resolving overlapping triangles) matters more here than
// bake speed, and a fixed triangle-then-pixel iteration order is already
// deterministic without needing disjoint row bands.
#include <rockgen/impostor.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <vector>

namespace rockgen {
namespace {

constexpr float kFibonacciAngle = 2.399963229728653f;

/// The orthonormal basis of a camera that LOOKS FROM `dir` toward the
/// origin: `right`/`up` span the screen plane, `dir` itself is "out of the
/// screen, toward the camera" (so depth = dot(p, dir) is larger for points
/// nearer the camera).
struct ViewBasis {
    glm::vec3 dir, right, up;
};

ViewBasis make_basis(const glm::vec3& dir) {
    const glm::vec3 up_ref = (std::abs(dir.y) > 0.99f) ? glm::vec3(1.0f, 0.0f, 0.0f)
                                                        : glm::vec3(0.0f, 1.0f, 0.0f);
    const glm::vec3 forward = -dir;   // the direction the camera looks
    const glm::vec3 right = glm::normalize(glm::cross(up_ref, forward));
    const glm::vec3 up = glm::cross(forward, right);
    return {dir, right, up};
}

struct Projected {
    glm::vec2 screen;         // pixel coordinates within one view_size cell
    float depth = 0.0f;       // larger == nearer the camera
    glm::vec2 uv;
    glm::vec3 normal_view;    // (right, up, dir) components of the vertex normal
};

Projected project(const glm::vec3& p, const glm::vec3& n, const glm::vec2& uv,
                  const ViewBasis& b, float half_extent, int view_size) {
    const float sx = glm::dot(p, b.right);
    const float sy = glm::dot(p, b.up);
    Projected out;
    out.screen = glm::vec2((sx + half_extent) / (2.0f * half_extent) * static_cast<float>(view_size),
                           (half_extent - sy) / (2.0f * half_extent) * static_cast<float>(view_size));
    out.depth = glm::dot(p, b.dir);
    out.uv = uv;
    out.normal_view = glm::vec3(glm::dot(n, b.right), glm::dot(n, b.up), glm::dot(n, b.dir));
    return out;
}

/// Nearest-texel sample of one channel of an interleaved image. `uv.x` wraps
/// (seam-split duplicate vertices carry u in [0, 2]); `uv.y` clamps (poles).
std::uint8_t sample_nearest(const assets::Image& img, const glm::vec2& uv, int channel, int channels) {
    float u = uv.x - std::floor(uv.x);
    float v = glm::clamp(uv.y, 0.0f, 1.0f);
    int x = std::min(static_cast<int>(u * static_cast<float>(img.width)), static_cast<int>(img.width) - 1);
    int y = std::min(static_cast<int>(v * static_cast<float>(img.height)), static_cast<int>(img.height) - 1);
    x = std::max(x, 0);
    y = std::max(y, 0);
    const size_t idx = (static_cast<size_t>(y) * img.width + static_cast<size_t>(x)) * static_cast<size_t>(channels)
                      + static_cast<size_t>(channel);
    return img.pixels[idx];
}

}  // namespace

std::vector<glm::vec3> impostor_view_dirs() {
    std::vector<glm::vec3> dirs;
    dirs.reserve(16);
    for (int i = 0; i < 16; ++i) {
        const float y = 1.0f - 2.0f * (static_cast<float>(i) + 0.5f) / 16.0f;
        const float r = std::sqrt(std::max(0.0f, 1.0f - y * y));
        const float phi = static_cast<float>(i) * kFibonacciAngle;
        dirs.emplace_back(std::cos(phi) * r, y, std::sin(phi) * r);
    }
    return dirs;
}

Impostor bake_impostor(const assets::MeshCpu& mesh, const RockSurface& s, int view_size) {
    Impostor out;
    out.view_dirs = impostor_view_dirs();
    out.grid = 4;
    out.view_size = view_size;
    const int canvas = 4 * view_size;

    out.albedo.width = out.albedo.height = static_cast<std::uint32_t>(canvas);
    out.albedo.format = assets::Image::Format::RGBA8;
    out.albedo.pixels.assign(static_cast<size_t>(canvas) * canvas * 4, 0);
    out.normal.width = out.normal.height = static_cast<std::uint32_t>(canvas);
    out.normal.format = assets::Image::Format::RGBA8;
    out.normal.pixels.assign(static_cast<size_t>(canvas) * canvas * 4, 0);

    float max_r = 0.0f;
    for (const auto& v : mesh.vertices) max_r = std::max(max_r, glm::length(v.position));
    const float half_extent = max_r * 1.02f;
    if (half_extent <= 0.0f) return out;

    for (int view = 0; view < 16; ++view) {
        const ViewBasis basis = make_basis(out.view_dirs[view]);
        std::vector<float> depth(static_cast<size_t>(view_size) * static_cast<size_t>(view_size),
                                 -std::numeric_limits<float>::infinity());
        const int ox = (view % 4) * view_size;
        const int oy = (view / 4) * view_size;

        for (size_t t = 0; t + 2 < mesh.indices.size(); t += 3) {
            const assets::MeshCpu::Vertex& v0 = mesh.vertices[mesh.indices[t + 0]];
            const assets::MeshCpu::Vertex& v1 = mesh.vertices[mesh.indices[t + 1]];
            const assets::MeshCpu::Vertex& v2 = mesh.vertices[mesh.indices[t + 2]];
            const Projected p0 = project(v0.position, v0.normal, v0.uv, basis, half_extent, view_size);
            const Projected p1 = project(v1.position, v1.normal, v1.uv, basis, half_extent, view_size);
            const Projected p2 = project(v2.position, v2.normal, v2.uv, basis, half_extent, view_size);

            const float minx = std::min({p0.screen.x, p1.screen.x, p2.screen.x});
            const float maxx = std::max({p0.screen.x, p1.screen.x, p2.screen.x});
            const float miny = std::min({p0.screen.y, p1.screen.y, p2.screen.y});
            const float maxy = std::max({p0.screen.y, p1.screen.y, p2.screen.y});
            const int x0 = std::max(0, static_cast<int>(std::floor(minx)));
            const int x1 = std::min(view_size - 1, static_cast<int>(std::ceil(maxx)));
            const int y0 = std::max(0, static_cast<int>(std::floor(miny)));
            const int y1 = std::min(view_size - 1, static_cast<int>(std::ceil(maxy)));
            if (x0 > x1 || y0 > y1) continue;

            // Barycentric weights (Cramer's rule solving P = w0*V0+w1*V1+w2*V2,
            // w0+w1+w2=1): sign-invariant under vertex-order swaps, so no
            // separate CW/CCW branch is needed.
            const float denom = (p1.screen.y - p2.screen.y) * (p0.screen.x - p2.screen.x)
                              + (p2.screen.x - p1.screen.x) * (p0.screen.y - p2.screen.y);
            if (std::abs(denom) < 1e-9f) continue;

            for (int py = y0; py <= y1; ++py) {
                for (int px = x0; px <= x1; ++px) {
                    const float sx = static_cast<float>(px) + 0.5f;
                    const float sy = static_cast<float>(py) + 0.5f;
                    const float w0 = ((p1.screen.y - p2.screen.y) * (sx - p2.screen.x)
                                    + (p2.screen.x - p1.screen.x) * (sy - p2.screen.y)) / denom;
                    const float w1 = ((p2.screen.y - p0.screen.y) * (sx - p2.screen.x)
                                    + (p0.screen.x - p2.screen.x) * (sy - p2.screen.y)) / denom;
                    const float w2 = 1.0f - w0 - w1;
                    if (w0 < 0.0f || w1 < 0.0f || w2 < 0.0f) continue;

                    const float d = w0 * p0.depth + w1 * p1.depth + w2 * p2.depth;
                    const size_t di = static_cast<size_t>(py) * static_cast<size_t>(view_size) + static_cast<size_t>(px);
                    if (d <= depth[di]) continue;
                    depth[di] = d;

                    const glm::vec2 uv = w0 * p0.uv + w1 * p1.uv + w2 * p2.uv;
                    glm::vec3 n = w0 * p0.normal_view + w1 * p1.normal_view + w2 * p2.normal_view;
                    const float len = glm::length(n);
                    if (len > 1e-9f) n /= len;

                    const size_t ax = static_cast<size_t>(ox + px);
                    const size_t ay = static_cast<size_t>(oy + py);
                    const size_t ai = (ay * static_cast<size_t>(canvas) + ax) * 4;

                    out.albedo.pixels[ai + 0] = sample_nearest(s.base_color, uv, 0, 3);
                    out.albedo.pixels[ai + 1] = sample_nearest(s.base_color, uv, 1, 3);
                    out.albedo.pixels[ai + 2] = sample_nearest(s.base_color, uv, 2, 3);
                    out.albedo.pixels[ai + 3] = 255;

                    out.normal.pixels[ai + 0] = static_cast<std::uint8_t>(glm::clamp(n.x * 0.5f + 0.5f, 0.0f, 1.0f) * 255.0f);
                    out.normal.pixels[ai + 1] = static_cast<std::uint8_t>(glm::clamp(n.y * 0.5f + 0.5f, 0.0f, 1.0f) * 255.0f);
                    out.normal.pixels[ai + 2] = static_cast<std::uint8_t>(glm::clamp(n.z * 0.5f + 0.5f, 0.0f, 1.0f) * 255.0f);
                    out.normal.pixels[ai + 3] = 255;
                }
            }
        }
    }
    return out;
}

}  // namespace rockgen
