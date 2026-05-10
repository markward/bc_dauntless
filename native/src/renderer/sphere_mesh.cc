// native/src/renderer/sphere_mesh.cc
#include "sphere_mesh.h"

#include <cmath>

namespace renderer {

namespace {

constexpr float kPi = 3.14159265358979323846f;
constexpr float kTwoPi = 2.0f * kPi;

}  // namespace

assets::MeshCpu build_uv_sphere(int target_tris) {
    if (target_tris < 64) target_tris = 64;
    // Split target evenly across (lat × lon) quad grid such that
    // lon = 2 × lat (full azimuth × half elevation, matching a UV-sphere).
    // target_tris ≈ 2 × lat × lon = 2 × lat × (2 × lat) = 4 × lat² .
    int lat_segs = static_cast<int>(std::round(std::sqrt(target_tris / 4.0f)));
    if (lat_segs < 4) lat_segs = 4;
    int lon_segs = lat_segs * 2;

    assets::MeshCpu cpu;
    cpu.vertices.reserve((lat_segs + 1) * (lon_segs + 1));
    cpu.indices.reserve(lat_segs * lon_segs * 6);

    for (int i = 0; i <= lat_segs; ++i) {
        // theta: from -π/2 (south pole) to +π/2 (north pole)
        float v = static_cast<float>(i) / static_cast<float>(lat_segs);
        float theta = -kPi * 0.5f + v * kPi;
        float sin_t = std::sin(theta);
        float cos_t = std::cos(theta);
        for (int j = 0; j <= lon_segs; ++j) {
            float u = static_cast<float>(j) / static_cast<float>(lon_segs);
            float phi = u * kTwoPi;
            float sin_p = std::sin(phi);
            float cos_p = std::cos(phi);
            assets::MeshCpu::Vertex vert;
            vert.position = {cos_t * cos_p, cos_t * sin_p, sin_t};
            vert.normal   = vert.position;
            vert.uv       = {u, v};
            cpu.vertices.push_back(vert);
        }
    }

    // Indices: clockwise winding from OUTSIDE the sphere. Combined with
    // glFrontFace(GL_CW) + glCullFace(GL_FRONT) (we cull front faces in
    // BackdropPass), the inside of the sphere is what's drawn.
    for (int i = 0; i < lat_segs; ++i) {
        for (int j = 0; j < lon_segs; ++j) {
            std::uint32_t a = static_cast<std::uint32_t>( i      * (lon_segs + 1) + j     );
            std::uint32_t b = static_cast<std::uint32_t>( i      * (lon_segs + 1) + j + 1 );
            std::uint32_t c = static_cast<std::uint32_t>((i + 1) * (lon_segs + 1) + j     );
            std::uint32_t d = static_cast<std::uint32_t>((i + 1) * (lon_segs + 1) + j + 1 );
            // Quad (a, b, d, c) → two CW triangles from outside.
            cpu.indices.push_back(a); cpu.indices.push_back(b); cpu.indices.push_back(d);
            cpu.indices.push_back(a); cpu.indices.push_back(d); cpu.indices.push_back(c);
        }
    }

    return cpu;
}

}  // namespace renderer
