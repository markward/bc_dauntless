// native/src/rockgen/src/impostor.cc
//
// 64-view (8x8 octahedral) CPU impostor rasteriser. Single-threaded: correctness (a shared,
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

// Barycentric weights near a shared triangle edge can independently round to
// a hair on the WRONG side of zero in each of the two triangles that share
// it (their edge-function formulas differ -- each uses its own third,
// non-shared vertex), so a plain ">= 0" inclusion test can have BOTH
// triangles reject the same pixel: a 1-pixel transparent crack along the
// seam. kEdgeEpsilon treats any weight within this band of zero as "on the
// edge" rather than "outside", and owns_tie() below deterministically
// assigns that boundary pixel to exactly one of the two triangles.
constexpr float kEdgeEpsilon = 1e-4f;

/// Deterministic tie-break for a pixel on (or within kEdgeEpsilon of) the
/// line through directed edge a->b: this edge "owns" boundary pixels if it
/// points toward decreasing screen Y, or -- if exactly horizontal -- toward
/// decreasing screen X. A mesh's shared interior edge is walked in OPPOSITE
/// directions by its two owning triangles (consistent mesh winding, see
/// shape.cc's `Shape.OutwardWinding`), so `owns_tie(a, b)` and
/// `owns_tie(b, a)` are never both true (nor both false): exactly one
/// triangle claims the boundary.
bool owns_tie(const glm::vec2& a, const glm::vec2& b) {
    if (a.y != b.y) return b.y < a.y;
    return b.x < a.x;
}

/// Whether a triangle vertex's (opposite-edge) barycentric weight `w` puts a
/// pixel inside this triangle across that edge (a->b, in the triangle's own
/// vertex order).
bool covers(float w, const glm::vec2& a, const glm::vec2& b) {
    if (w > kEdgeEpsilon) return true;
    if (w < -kEdgeEpsilon) return false;
    return owns_tie(a, b);
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

namespace {
float sgn_nz(float v) { return v >= 0.0f ? 1.0f : -1.0f; }

/// Copy of native/src/renderer/far_field.cc:oct_decode (not linked): the unit
/// direction of octahedral-map point (a, b), glTF frame, pole axis +y.
glm::vec3 oct_decode(float a, float b) {
    glm::vec3 n(a, 1.0f - std::abs(a) - std::abs(b), b);
    if (n.y < 0.0f) {
        const float x = (1.0f - std::abs(b)) * sgn_nz(a);
        const float z = (1.0f - std::abs(a)) * sgn_nz(b);
        n.x = x;
        n.z = z;
    }
    n = glm::normalize(n);
    return n + glm::vec3(0.0f);   // -0 -> +0: mirror twins stay bit-identical
}
}  // namespace

std::vector<glm::vec3> impostor_view_dirs() {
    // renderer::far::oct_view_dir's layout: view v = j * grid + i at oct
    // ((2i - (grid-1)) / (grid-1), (2j - (grid-1)) / (grid-1)).
    constexpr int grid = kImpostorGrid;
    const float span = static_cast<float>(grid - 1);
    std::vector<glm::vec3> dirs;
    dirs.reserve(grid * grid);
    for (int v = 0; v < grid * grid; ++v) {
        const int i = v % grid, j = v / grid;
        dirs.push_back(oct_decode(static_cast<float>(2 * i - (grid - 1)) / span,
                                  static_cast<float>(2 * j - (grid - 1)) / span));
    }
    return dirs;
}

Impostor bake_impostor(const assets::MeshCpu& mesh, const RockSurface& s, int view_size) {
    return bake_impostor_parts({{&mesh, &s, glm::mat4(1.0f)}}, view_size);
}

Impostor bake_impostor_parts(const std::vector<ImpostorPart>& parts, int view_size) {
    Impostor out;
    out.view_dirs = impostor_view_dirs();
    out.grid = kImpostorGrid;
    out.view_size = view_size;
    const int canvas = kImpostorGrid * view_size;

    out.albedo.width = out.albedo.height = static_cast<std::uint32_t>(canvas);
    out.albedo.format = assets::Image::Format::RGBA8;
    out.albedo.pixels.assign(static_cast<size_t>(canvas) * canvas * 4, 0);
    out.normal.width = out.normal.height = static_cast<std::uint32_t>(canvas);
    out.normal.format = assets::Image::Format::RGBA8;
    out.normal.pixels.assign(static_cast<size_t>(canvas) * canvas * 4, 0);

    // Every part's vertices in the bake frame. An identity xform is
    // exact (x*1 + y*0 + z*0 + 0), so a one-part identity bake sees the very
    // positions bake_impostor always rasterised. Normals take the linear part
    // un-normalised: the per-pixel normalise below absorbs a uniform scale.
    std::vector<std::vector<assets::MeshCpu::Vertex>> placed(parts.size());
    float max_r = 0.0f;
    for (size_t pi = 0; pi < parts.size(); ++pi) {
        const ImpostorPart& part = parts[pi];
        const glm::mat3 lin(part.xform);
        placed[pi] = part.mesh->vertices;
        for (auto& v : placed[pi]) {
            v.position = glm::vec3(part.xform * glm::vec4(v.position, 1.0f));
            v.normal = lin * v.normal;
            max_r = std::max(max_r, glm::length(v.position));
        }
    }
    const float half_extent = max_r * 1.02f;
    if (half_extent <= 0.0f) return out;

    for (int view = 0; view < kImpostorGrid * kImpostorGrid; ++view) {
        const ViewBasis basis = make_basis(out.view_dirs[view]);
        std::vector<float> depth(static_cast<size_t>(view_size) * static_cast<size_t>(view_size),
                                 -std::numeric_limits<float>::infinity());
        const int ox = (view % kImpostorGrid) * view_size;
        const int oy = (view / kImpostorGrid) * view_size;

        for (size_t pi = 0; pi < parts.size(); ++pi) {
            const assets::MeshCpu& mesh = *parts[pi].mesh;
            const RockSurface& s = *parts[pi].surface;
            const std::vector<assets::MeshCpu::Vertex>& verts = placed[pi];
            for (size_t t = 0; t + 2 < mesh.indices.size(); t += 3) {
                const assets::MeshCpu::Vertex& v0 = verts[mesh.indices[t + 0]];
                const assets::MeshCpu::Vertex& v1 = verts[mesh.indices[t + 1]];
                const assets::MeshCpu::Vertex& v2 = verts[mesh.indices[t + 2]];
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
                        if (!covers(w0, p1.screen, p2.screen)) continue;
                        if (!covers(w1, p2.screen, p0.screen)) continue;
                        if (!covers(w2, p0.screen, p1.screen)) continue;

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
    }
    return out;
}

}  // namespace rockgen
