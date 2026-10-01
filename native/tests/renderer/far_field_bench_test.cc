// native/tests/renderer/far_field_bench_test.cc
// Far tier spec §5: REPORTS FarField::build cost; asserts nothing about time.
#include <gtest/gtest.h>
#include <renderer/far_field.h>
#include <glm/gtc/matrix_transform.hpp>
#include <chrono>
#include <cstdio>

namespace far = renderer::far;

TEST(FarFieldBench, ReportsBuildTimeInsideTheBandAndDashing) {
    far::FarField f;
    std::vector<far::CatalogueRock> cat(16);
    for (auto& c : cat) c.has_impostor = true;
    f.set_catalogue(cat, {{0, 0, 1}});
    far::DiscSource s;
    s.id = 1; s.frame = "Vesuvi"; s.seed = 3;
    s.table = {{0.0f, 0.05f}, {226000.0f, 0.5f}, {330000.0f, 0.5f}, {340000.0f, 0.05f}};
    far::Population m; m.kind = 0; m.density_at_1 = 9.67e-8f; m.size = {0.05f, 0.7f, 2.5f};
    m.rocks = {8, 9}; m.weights = {1, 1};
    s.pops = {m};
    f.set_sources({s});
    far::BuildInput in;
    in.view = glm::lookAt(glm::vec3(0), glm::vec3(0, 1, 0), glm::vec3(0, 0, 1));
    in.proj = glm::perspective(glm::radians(35.0f), 16.0f / 9.0f, 1.0f, 1.8e6f);
    in.viewport_h = 1080.0f;
    far::FarOutput out;
    for (const double speed : {0.0, 100000.0}) {
        double y = 0.0, worst = 0.0, total = 0.0;
        for (int frame = 0; frame < 120; ++frame) {
            f.set_frame(std::string("Vesuvi"), {280000.0, y, 0.0});
            const auto t0 = std::chrono::steady_clock::now();
            f.build(in, out);
            const double ms = std::chrono::duration<double, std::milli>(
                std::chrono::steady_clock::now() - t0).count();
            worst = std::max(worst, ms); total += ms;
            y += speed / 60.0;
        }
        std::printf("[far bench] speed=%.0f GU/s mean=%.3f ms worst=%.3f ms generated=%d cells=%d specks=%zu\n",
                    speed, total / 120.0, worst, out.generated, out.cells, out.specks.size());
    }
    SUCCEED();
}
