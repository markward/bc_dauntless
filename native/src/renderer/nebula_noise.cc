// native/src/renderer/nebula_noise.cc
#include "renderer/nebula_noise.h"

#include <cmath>
#include <cstddef>

namespace renderer::nebula_noise {

namespace {
glm::vec3 fract3(glm::vec3 v) { return v - glm::floor(v); }
float smooth(float f) { return f * f * (3.0f - 2.0f * f); }
float mix(float a, float b, float t) { return a + (b - a) * t; }
}  // namespace

float hash13(glm::vec3 p3) {
    p3 = fract3(p3 * 0.1031f);
    p3 += glm::dot(p3, glm::vec3(p3.z, p3.y, p3.x) + 31.32f);
    const float v = (p3.x + p3.y) * p3.z;
    return v - std::floor(v);
}

float vnoise(glm::vec3 p) {
    const glm::vec3 i = glm::floor(p);
    const glm::vec3 f = p - i;
    const float ux = smooth(f.x), uy = smooth(f.y), uz = smooth(f.z);
    auto h = [&](float x, float y, float z) { return hash13(i + glm::vec3(x, y, z)); };
    return mix(mix(mix(h(0, 0, 0), h(1, 0, 0), ux), mix(h(0, 1, 0), h(1, 1, 0), ux), uy),
               mix(mix(h(0, 0, 1), h(1, 0, 1), ux), mix(h(0, 1, 1), h(1, 1, 1), ux), uy),
               uz);
}

std::vector<float> bake_hash_lattice(int n) {
    std::vector<float> out(static_cast<std::size_t>(n) * n * n);
    std::size_t k = 0;
    for (int z = 0; z < n; ++z)
        for (int y = 0; y < n; ++y)
            for (int x = 0; x < n; ++x)
                out[k++] = hash13(glm::vec3(x, y, z));
    return out;
}

float vnoise_lattice(const std::vector<float>& lattice, int n, glm::vec3 p) {
    const glm::vec3 c = glm::floor(p);
    const glm::vec3 f = p - c;
    const float ux = smooth(f.x), uy = smooth(f.y), uz = smooth(f.z);
    auto wrap = [n](float v) {
        const int m = static_cast<int>(v) % n;
        return m < 0 ? m + n : m;
    };
    const int x0 = wrap(c.x), y0 = wrap(c.y), z0 = wrap(c.z);
    const int x1 = (x0 + 1) % n, y1 = (y0 + 1) % n, z1 = (z0 + 1) % n;
    auto at = [&](int x, int y, int z) {
        return lattice[(static_cast<std::size_t>(z) * n + y) * n + x];
    };
    return mix(mix(mix(at(x0, y0, z0), at(x1, y0, z0), ux),
                   mix(at(x0, y1, z0), at(x1, y1, z0), ux), uy),
               mix(mix(at(x0, y0, z1), at(x1, y0, z1), ux),
                   mix(at(x0, y1, z1), at(x1, y1, z1), ux), uy),
               uz);
}

float fbm_lattice(const std::vector<float>& lattice, int n, glm::vec3 p) {
    float a = 0.5f, s = 0.0f;
    for (int k = 0; k < 5; ++k) {
        s += a * vnoise_lattice(lattice, n, p);
        p *= 2.02f;
        a *= 0.5f;
    }
    return s;
}

}  // namespace renderer::nebula_noise
