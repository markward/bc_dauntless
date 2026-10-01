// native/tests/renderer/minor_field_bench_test.cc
// Reports a step-time number for 20,000 live minors (minor-rocks task 12,
// spec §5 perf budget). Asserts nothing about time -- CI machines vary too
// much for a hard ms budget here; it is read by a human from the printed
// line, as instructed by the task brief.
#include <chrono>
#include <cstdio>
#include <gtest/gtest.h>
#include <glm/gtc/matrix_transform.hpp>
#include <renderer/minor_field.h>

using namespace renderer::minors;

TEST(MinorFieldBench, ReportsStepTimeAt20kMinors) {
    MinorField f;
    f.set_fragments(0, {Fragment{1, 2, 57.142857f}, Fragment{3, 4, 57.142857f}});
    for (std::uint32_t i = 0; i < 50; ++i) {
        CloudDesc d; d.id = i + 1; d.anchor = Anchor::Point;
        d.point = {double(i % 10) * 40.0, double(i / 10) * 40.0, -200.0};
        d.shell_inner = 4; d.shell_outer = 12; d.count = 400;
        d.r_min = 0.03f; d.r_max = 0.6f; d.seed = i; d.orbit_rate = 0.02f;
        f.add_cloud(d, 0.0);
    }
    StepInput in;
    in.view = glm::lookAt(glm::vec3(200, 200, 100), glm::vec3(200, 200, -200), glm::vec3(0, 1, 0));
    in.proj = glm::perspective(glm::radians(60.0f), 16.0f / 9.0f, 0.1f, 1e6f);
    in.viewport_h = 1080.0f;
    PlayerBox p; p.world = glm::translate(glm::mat4(1.0f), {200, 200, -200}) *
                           glm::scale(glm::mat4(1.0f), glm::vec3(0.01f));
    p.half_mu = {60, 320, 40};
    in.player = p;
    const int frames = 120;
    const auto t0 = std::chrono::steady_clock::now();
    for (int i = 0; i < frames; ++i) { in.game_time = i / 60.0; f.step(in); f.drain_contacts(); }
    const double ms = std::chrono::duration<double, std::milli>(
        std::chrono::steady_clock::now() - t0).count() / frames;
    std::printf("[minor bench] 20,000 minors: %.3f ms/step (drawn %d, bins %d)\n",
                ms, f.stats().drawn, f.stats().bins);
    EXPECT_EQ(f.stats().minors, 20000);
}
