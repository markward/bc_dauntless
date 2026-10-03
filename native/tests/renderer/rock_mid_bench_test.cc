// native/tests/renderer/rock_mid_bench_test.cc
// Rock fields spec §4 "Performance": REPORTS the mid band's per-camera build
// cost in a vast full-density belt; the only assertion is the sprite cap.
#include <gtest/gtest.h>
#include <renderer/rock_mid.h>
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <glm/gtc/matrix_transform.hpp>

using namespace renderer;

TEST(MidBench, VastBelt) {
    // Density 1 everywhere out to 1e6 GU from the star, flat in z near the
    // plane, no noise.
    far::DiscSource b; b.id = 5; b.seed = 1; b.table = {{0.0f, 1.0f}, {1.0e6f, 1.0f}};
    b.scale_height_min_gu = 1.0e6f;
    std::vector<rockfield::MidCollection> cols;
    for (int v = 0; v < 3; ++v)
        for (int i = 0; i < 16; ++i) cols.push_back({v * 16 + i, v});
    rockfield::MidField f;
    f.set_collections(cols);
    f.set_view_dirs(renderer::far::oct_view_dirs(8));
    f.set_sources({b});

    rockfield::MidBuildInput in;
    in.proj = glm::perspective(glm::radians(35.0f), 16.0f / 9.0f, 0.1f, 1.0e7f);
    in.viewport_h = 1080.0f;
    rockfield::MidOutput out;
    constexpr int kBuilds = 20;
    const glm::vec3 points[] = {{10000.0f, 0.0f, 0.0f}, {500000.0f, 0.0f, 0.0f},
                                {300000.0f, 400000.0f, 2000.0f}};
    // The defaults (cap 4000; it does not bind: ~150 tiles in a 35 degree
    // view), then a stress set with every tile a quarter the size (~3,250
    // tiles: each level's span is clamped to 33 tiles per axis) and a cap of
    // 2,000, which MUST bind.
    rockfield::MidDials stress;
    stress.l0_tile_gu /= 4.0f; stress.l1_tile_gu /= 4.0f; stress.l2_tile_gu /= 4.0f;
    stress.max_sprites = 2000;
    const rockfield::MidDials sets[] = {rockfield::MidDials{}, stress};
    const char* names[] = {"defaults", "quarter tiles"};
    for (int k = 0; k < 2; ++k) {
        const rockfield::MidDials& d = sets[k];
        f.set_dials(d);
        for (const glm::vec3& eye : points) {
            in.view = glm::lookAt(eye, eye + glm::vec3(0, 1, 0), glm::vec3(0, 0, 1));
            double total = 0.0, worst = 0.0;
            for (int i = 0; i < kBuilds; ++i) {
                const auto t0 = std::chrono::steady_clock::now();
                f.build(in, out);
                const double ms = std::chrono::duration<double, std::milli>(
                    std::chrono::steady_clock::now() - t0).count();
                total += ms; worst = std::max(worst, ms);
            }
            std::printf("[mid bench] %s, eye (%.0f, %.0f, %.0f): build mean=%.3f ms "
                        "worst=%.3f ms sprites=%d tiles=%d (cap %d)\n",
                        names[k], eye.x, eye.y, eye.z, total / kBuilds, worst, out.count,
                        out.tiles, d.max_sprites);
            int n = 0;
            for (const auto* list : {&out.sprites, &out.sprites_fading})   // solid + translucent
                for (const auto& bin : *list) n += static_cast<int>(bin.items.size());
            EXPECT_GT(n, 0) << "the belt drew nothing";
            EXPECT_EQ(n, out.count);
            EXPECT_LE(n, d.max_sprites);
            if (k == 1) {   // the cap binds: more tiles than sprites, exactly the cap drawn
                EXPECT_GT(out.tiles, d.max_sprites);
                EXPECT_EQ(n, d.max_sprites);
            }
        }
    }
}

// The live load Mark profiled ("Rock Fields: inside Beol 4", ee82c35c):
// inside (300 GU in from the edge, looking at the centre) and outside
// (6,000 GU off, looking at the field). REPORTS MidField::build per call.
#include "rock_scenario.h"
TEST(MidBench, InsideAndOutsideBeol4) {
    rockfield::MidField f;
    f.set_collections(rock_scenario::mid_collections());
    f.set_view_dirs(rock_scenario::view_dirs64());
    f.set_sources({rock_scenario::beol4_field()});
    rockfield::MidBuildInput in;
    in.viewport_h = 1080.0f;
    rockfield::MidOutput out;
    struct Case { const char* name; glm::vec3 eye; };
    const Case cases[] = {{"inside", {0, -700, 0}}, {"outside", {0, -6000, 0}}};
    for (const Case& cs : cases) {
        constexpr int kBuilds = 120;
        double total = 0, worst = 0;
        for (int i = 0; i < kBuilds; ++i) {
            const glm::vec3 eye = cs.eye + glm::vec3(0, 0.1f * i, 0);   // 6 GU/s
            in.view = glm::lookAt(eye, glm::vec3(0), glm::vec3(0, 0, 1));
            in.proj = glm::perspective(glm::radians(60.0f), 16.0f / 9.0f, 0.1f, 1.0e6f);
            // The live call pattern: far_set_frame re-pushes the same sources
            // every frame before the draw.
            const auto t0 = std::chrono::steady_clock::now();
            f.set_sources({rock_scenario::beol4_field()});
            f.build(in, out);
            const double ms = std::chrono::duration<double, std::milli>(
                std::chrono::steady_clock::now() - t0).count();
            total += ms; worst = std::max(worst, ms);
        }
        std::printf("[mid bench beol4] %s: build mean=%.3f ms worst=%.3f ms sprites=%d tiles=%d "
                    "bins=%zu\n", cs.name, total / kBuilds, worst, out.count, out.tiles,
                    out.sprites.size() + out.sprites_fading.size());
    }
    EXPECT_GE(out.count, 0);
}
