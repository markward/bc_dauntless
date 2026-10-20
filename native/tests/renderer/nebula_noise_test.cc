// The system nebula's haze-lane noise read from a baked hash lattice
// (renderer/nebula_noise.h): the CPU twin of system_nebula.frag's
// vnoise_lattice / fbm_lattice. Inside the lattice's first period the field
// is exactly the procedural value noise it replaced; past it, it repeats.
#include <gtest/gtest.h>

#include <renderer/nebula_noise.h>

#include <glm/glm.hpp>

#include <cmath>
#include <vector>

namespace nn = renderer::nebula_noise;

TEST(NebulaNoise, LatticeHoldsTheHashOfEveryCell) {
    const int n = nn::kLatticeN;
    const std::vector<float> lat = nn::bake_hash_lattice(n);
    ASSERT_EQ(lat.size(), static_cast<std::size_t>(n) * n * n);
    for (int z = 0; z < n; z += 7)
        for (int y = 0; y < n; y += 5)
            for (int x = 0; x < n; x += 3) {
                const float v = lat[(static_cast<std::size_t>(z) * n + y) * n + x];
                EXPECT_EQ(v, nn::hash13(glm::vec3(x, y, z))) << x << "," << y << "," << z;
                EXPECT_GE(v, 0.0f);
                EXPECT_LT(v, 1.0f);
            }
}

TEST(NebulaNoise, InsideTheFirstPeriodItIsTheProceduralNoise) {
    const int n = nn::kLatticeN;
    const std::vector<float> lat = nn::bake_hash_lattice(n);
    // Cells [0, n-1): no corner wraps, so every corner is the same hash the
    // procedural noise uses.
    for (int k = 0; k < 500; ++k) {
        const glm::vec3 p(std::fmod(k * 7.31f, n - 1.0f),
                          std::fmod(k * 3.17f + 1.3f, n - 1.0f),
                          std::fmod(k * 5.73f + 2.9f, n - 1.0f));
        EXPECT_NEAR(nn::vnoise_lattice(lat, n, p), nn::vnoise(p), 1e-5f)
            << p.x << "," << p.y << "," << p.z;
    }
}

TEST(NebulaNoise, RepeatsWithThePeriodAndJoinsAcrossTheSeam) {
    const int n = nn::kLatticeN;
    const std::vector<float> lat = nn::bake_hash_lattice(n);
    const float N = static_cast<float>(n);
    for (int k = 0; k < 200; ++k) {
        const glm::vec3 p(k * 0.913f - 40.0f, k * 0.377f + 3.1f, k * -0.551f);
        EXPECT_NEAR(nn::vnoise_lattice(lat, n, p),
                    nn::vnoise_lattice(lat, n, p + glm::vec3(N, -2.0f * N, 3.0f * N)),
                    1e-5f);
    }
    // Continuous across the wrap: just below the seam reaches cell 0's value.
    const glm::vec3 seam(N - 1e-4f, 10.0f, 20.0f);
    EXPECT_NEAR(nn::vnoise_lattice(lat, n, seam),
                nn::vnoise_lattice(lat, n, glm::vec3(0.0f, 10.0f, 20.0f)), 1e-3f);
}

TEST(NebulaNoise, FbmSumsFiveOctavesOfTheLatticeNoise) {
    const int n = nn::kLatticeN;
    const std::vector<float> lat = nn::bake_hash_lattice(n);
    const glm::vec3 p(1.37f, 0.52f, 0.91f);   // all 5 octaves stay inside [0, n-1)
    float s = 0.0f, a = 0.5f;
    glm::vec3 q = p;
    for (int k = 0; k < 5; ++k) { s += a * nn::vnoise(q); q *= 2.02f; a *= 0.5f; }
    EXPECT_NEAR(nn::fbm_lattice(lat, n, p), s, 1e-5f);
}
