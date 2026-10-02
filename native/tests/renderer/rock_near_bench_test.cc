// native/tests/renderer/rock_near_bench_test.cc
// Rock fields spec §4 "Performance": REPORTS the near band's streaming cost
// at dash speed; asserts nothing about time (GPU is unmeasurable here, CPU
// time depends on the machine and its load).
#include <gtest/gtest.h>
#include <renderer/rock_near.h>
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <glm/gtc/matrix_transform.hpp>

using namespace renderer;

TEST(NearBench, StreamAt100kGups) {
    // A full-density, noise-free sphere wider than the whole run.
    far::DiscSource s; s.id = 3; s.seed = 99; s.shape = far::DiscSource::Shape::Sphere;
    s.sphere_radius_gu = 1.0e6f; s.sphere_edge_frac = 0.0f; s.view_space = true;
    rockfield::NearCatalogue cat;
    cat.small_rocks = {1, 2, 3}; cat.large_rocks = {10, 11};
    cat.small_bound_mu = {1.0f, 1.0f, 1.0f}; cat.large_bound_mu = {1.0f, 1.0f};
    cat.view_dirs_gltf = {{0, 0, 1}, {0, 0, -1}, {1, 0, 0}, {-1, 0, 0}, {0, 1, 0}, {0, -1, 0}};
    rockfield::NearField f;
    f.set_catalogue(cat);
    f.set_sources({s});

    constexpr int kSteps = 600;
    constexpr double kGups = 100000.0, kHz = 60.0;
    rockfield::NearBuildInput in;
    in.proj = glm::perspective(glm::radians(35.0f), 16.0f / 9.0f, 0.1f, 1.0e6f);
    in.viewport_h = 1080.0f;
    rockfield::NearOutput out;
    double stream_total = 0.0, stream_worst = 0.0, build_total = 0.0, build_worst = 0.0;
    int max_cells = 0, max_small = 0, max_large = 0;
    for (int step = 0; step < kSteps; ++step) {
        // View space IS system space (anchor 0); the eye flies along +y.
        const glm::dvec3 eye(0.0, -500000.0 + step * kGups / kHz, 0.0);
        auto t0 = std::chrono::steady_clock::now();
        f.stream(eye);
        const double ms_stream = std::chrono::duration<double, std::milli>(
            std::chrono::steady_clock::now() - t0).count();
        in.view = glm::lookAt(glm::vec3(eye), glm::vec3(eye) + glm::vec3(0, 1, 0),
                              glm::vec3(0, 0, 1));
        t0 = std::chrono::steady_clock::now();
        f.build(in, out);
        const double ms_build = std::chrono::duration<double, std::milli>(
            std::chrono::steady_clock::now() - t0).count();
        stream_total += ms_stream; stream_worst = std::max(stream_worst, ms_stream);
        build_total += ms_build; build_worst = std::max(build_worst, ms_build);
        const auto st = f.stats();
        max_cells = std::max(max_cells, st.cells);
        max_small = std::max(max_small, st.small);
        max_large = std::max(max_large, st.large);
    }
    std::printf("[near bench] %d steps at %.0f GU/s / %.0f Hz: stream mean=%.3f ms "
                "worst=%.3f ms; build mean=%.3f ms worst=%.3f ms; max cells=%d "
                "small=%d large=%d\n",
                kSteps, kGups, kHz, stream_total / kSteps, stream_worst,
                build_total / kSteps, build_worst, max_cells, max_small, max_large);
    EXPECT_GT(max_cells, 0);   // the run streamed at all (not a time assertion)
}
