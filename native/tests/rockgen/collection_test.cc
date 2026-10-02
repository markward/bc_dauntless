// Baked rock-collection impostors (rock-fields plan Task 9): one sprite of a
// whole arranged cluster of catalogue rocks, rasterised by the SAME bake as a
// single rock's impostor.
#include <gtest/gtest.h>
#include <assets/mesh.h>
#include <rockgen/collection.h>
#include <rockgen/impostor.h>
#include <rockgen/recipe.h>
#include <rockgen/shape.h>
#include <rockgen/surface.h>

#include "mini_recipe.h"

#include <glm/glm.hpp>

#include <fstream>
#include <map>
#include <sstream>
#include <string>
#include <vector>

namespace {

// kMini plus a small "collections" block: cheap enough to bake in a test.
constexpr const char* kMiniCollections = R"({"tool_version":1,"seed":7,"bound_radius_m":100,
 "impostor_view_size":32,"volume_dims":16,
 "major":{"lod_subdivisions":[3,2],"texture_size":64},
 "fragment":{"lod_subdivisions":[2,1],"texture_size":32,"cuts":[2,4]},
 "families":[{"name":"silicate","majors":2,"fragments":1,"palette":[[0.4,0.4,0.4],[0.5,0.5,0.5]],
   "gloss":0.12,"displace":0.35,"octaves":5,"noise_scale":2.3,"axis":[0.7,1.3],"craters":[2,4],
   "crater_radius":[0.1,0.25],"detail_octaves":3,"detail_scale":7,"normal_strength":2.5}],
 "collections":{"count":2,"family":"silicate","view_size":32,
   "variants":[{"name":"sparse","rocks":[20,30]},{"name":"medium","rocks":[30,45]},
               {"name":"dense","rocks":[45,60]}],
   "size":[0.03,0.15],"exponent":2.5}})";

std::string committed_recipe() {
    std::ifstream f(std::string(OPEN_STBC_PROJECT_ROOT) + "/native/assets/rocks/recipe.json",
                    std::ios::binary);
    std::ostringstream ss;
    ss << f.rdbuf();
    return ss.str();
}

double mean_alpha(const assets::Image& img) {
    double sum = 0.0;
    for (std::size_t i = 3; i < img.pixels.size(); i += 4) sum += img.pixels[i];
    return sum / static_cast<double>(img.pixels.size() / 4);
}

const rockgen::CollectionSpec& find(const std::vector<rockgen::CollectionSpec>& cs,
                                    const std::string& id) {
    for (const auto& c : cs)
        if (c.id == id) return c;
    throw std::runtime_error("no collection " + id);
}

/// Bakes collection `id` of `r` with every part's lod1 + surface.
rockgen::Impostor bake(const rockgen::Recipe& r, const std::string& id) {
    const auto rocks = rockgen::expand_recipe(r);
    const auto cols = rockgen::expand_collections(r);
    const auto parts = rockgen::arrange_collection(r, rocks, find(cols, id));
    std::map<std::size_t, std::pair<assets::MeshCpu, rockgen::RockSurface>> cache;
    for (const auto& p : parts) {
        if (cache.count(p.rock)) continue;
        cache[p.rock] = {rockgen::generate_rock_lods(rocks[p.rock]).at(1),
                         rockgen::generate_rock_surface(rocks[p.rock])};
    }
    std::vector<rockgen::ImpostorPart> ip;
    for (const auto& p : parts) {
        const auto& e = cache.at(p.rock);
        ip.push_back({&e.first, &e.second, rockgen::part_xform(p, rocks[p.rock].bound_radius_m)});
    }
    return rockgen::bake_impostor_parts(ip, r.collections.view_size);
}

}  // namespace

TEST(CollectionBake, SinglePartEqualsBakeImpostor) {
    auto r = rockgen::parse_recipe(kMini);
    auto s = rockgen::expand_recipe(r);
    ASSERT_TRUE(s[2].fragment);
    auto lods = rockgen::generate_rock_lods(s[2]);
    auto surf = rockgen::generate_rock_surface(s[2]);
    auto a = rockgen::bake_impostor(lods[1], surf, 32);
    auto b = rockgen::bake_impostor_parts({{&lods[1], &surf, glm::mat4(1.0f)}}, 32);
    ASSERT_EQ(a.albedo.width, b.albedo.width);
    EXPECT_EQ(a.albedo.pixels, b.albedo.pixels);
    EXPECT_EQ(a.normal.pixels, b.normal.pixels);
    EXPECT_EQ(a.view_dirs, b.view_dirs);
}

TEST(CollectionBake, ArrangementIsDeterministicAndInsideTheUnitBall) {
    auto r = rockgen::parse_recipe(committed_recipe());
    auto rocks = rockgen::expand_recipe(r);
    auto a = rockgen::expand_collections(r);
    auto b = rockgen::expand_collections(r);
    ASSERT_EQ(a.size(), 48u);
    EXPECT_EQ(a[0].id, "collections/sparse_00");
    EXPECT_EQ(a[47].id, "collections/dense_15");
    for (std::size_t i = 0; i < a.size(); ++i) {
        EXPECT_EQ(a[i].id, b[i].id);
        EXPECT_EQ(a[i].variant, b[i].variant);
        EXPECT_EQ(a[i].seed, b[i].seed);
        EXPECT_EQ(a[i].rocks, b[i].rocks);
        auto pa = rockgen::arrange_collection(r, rocks, a[i]);
        auto pb = rockgen::arrange_collection(r, rocks, b[i]);
        ASSERT_EQ(pa.size(), static_cast<std::size_t>(a[i].rocks)) << a[i].id;
        ASSERT_EQ(pa.size(), pb.size());
        float bound = 0.0f;
        for (std::size_t k = 0; k < pa.size(); ++k) {
            EXPECT_EQ(pa[k].rock, pb[k].rock);
            EXPECT_EQ(pa[k].centre, pb[k].centre);
            EXPECT_EQ(pa[k].radius, pb[k].radius);
            EXPECT_EQ(pa[k].rotation, pb[k].rotation);
            EXPECT_EQ(rocks[pa[k].rock].family->name, r.collections.family);
            const float reach = glm::length(pa[k].centre) + pa[k].radius;
            EXPECT_LE(reach, 1.0f + 1e-5f) << a[i].id << " part " << k;
            bound = std::max(bound, reach);
        }
        EXPECT_NEAR(bound, 1.0f, 1e-5f) << a[i].id;   // framed exactly on the unit ball
    }
}

TEST(CollectionBake, CoverageGrowsWithVariant) {
    auto r = rockgen::parse_recipe(kMiniCollections);
    auto sparse = bake(r, "collections/sparse_00");
    auto dense = bake(r, "collections/dense_00");
    EXPECT_GT(mean_alpha(dense.albedo), mean_alpha(sparse.albedo));
    EXPECT_GT(mean_alpha(sparse.albedo), 0.0);
}

TEST(CollectionBake, AvgAlbedoIsCoverageWeighted) {
    rockgen::Impostor imp;
    imp.albedo.width = 2; imp.albedo.height = 1;
    imp.albedo.format = assets::Image::Format::RGBA8;
    // One covered red pixel, one uncovered white pixel: only the red counts.
    imp.albedo.pixels = {255, 0, 0, 255,   255, 255, 255, 0};
    const glm::vec3 m = rockgen::impostor_avg_albedo(imp);
    EXPECT_FLOAT_EQ(m.r, 1.0f);
    EXPECT_FLOAT_EQ(m.g, 0.0f);
    EXPECT_FLOAT_EQ(m.b, 0.0f);
}
