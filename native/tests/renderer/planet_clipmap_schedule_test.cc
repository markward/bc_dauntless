#include <gtest/gtest.h>
#include <renderer/planet_clipmap_schedule.h>
#include <set>
#include <utility>
using namespace renderer::planet_detail;

static std::vector<int> oct5() { return {9, 8, 7, 6, 5}; }

// Every (level, toroidal x, toroidal row) written, counting guard rows separately.
static void paint(const std::vector<BakeRect>& rs, std::vector<std::set<std::pair<int,int>>>& px) {
    for (auto& r : rs) for (int y = 0; y < r.h; ++y) for (int x = 0; x < r.w; ++x)
        px[r.level].insert({r.tor_x + x, r.band_row + y});
}

TEST(ClipmapSchedule, LevelCountCapsForSmallPlanets) {
    EXPECT_EQ(level_count_for(3600.0f, 0.1f), 5);
    EXPECT_EQ(level_count_for(140.0f, 0.1f), 2);    // 51.2*2^1=102.4 <= 140 < 204.8
    EXPECT_EQ(level_count_for(10.0f, 0.1f), 1);
}

TEST(ClipmapSchedule, ReanchorThreshold) {
    EXPECT_FALSE(needs_reanchor({1799.0f, 0.0f}, 3600.0f));
    EXPECT_TRUE(needs_reanchor({1300.0f, 1300.0f}, 3600.0f));
}

TEST(ClipmapSchedule, ColdFillCompletesAndCoversEveryTexelOnce) {
    ClipmapSchedule s(0.1f, oct5());
    std::vector<std::set<std::pair<int,int>>> px(5);
    long long total = 0; int frames = 0;
    const long long budget = 65536LL * 8;
    while (!s.complete({0, 0}) && frames < 1000) {
        std::vector<BakeRect> out;
        long long c = s.update({0, 0}, budget, out);
        EXPECT_LE(c, budget + 1024LL * 9 + 2 * 1024LL * 9);   // one strip (+ its guard rows) of slack
        total += c; paint(out, px); ++frames;
    }
    ASSERT_TRUE(s.complete({0, 0}));
    for (int L = 0; L < 5; ++L) EXPECT_EQ(px[L].size(), 1024u * 1026u) << L;   // 1024 rows + 2 guards
    EXPECT_GT(frames, 20); EXPECT_LT(frames, 200);
}

TEST(ClipmapSchedule, NoOverlapWithinOneColdFill) {
    ClipmapSchedule s(0.1f, oct5());
    std::vector<std::multiset<std::pair<int,int>>> seen(5);
    for (int f = 0; f < 1000 && !s.complete({0, 0}); ++f) {
        std::vector<BakeRect> out; s.update({0, 0}, 65536LL * 8, out);
        for (auto& r : out) for (int y = 0; y < r.h; ++y) for (int x = 0; x < r.w; ++x)
            seen[r.level].insert({r.tor_x + x, r.band_row + y});
    }
    for (int L = 0; L < 5; ++L)
        for (auto& p : seen[L]) ASSERT_EQ(seen[L].count(p), 1u) << L;
}

TEST(ClipmapSchedule, OneTexelMoveBakesOneColumnPerLevelThatMoved) {
    ClipmapSchedule s(0.1f, oct5());
    for (int f = 0; f < 1000 && !s.complete({0.05f, 0.05f}); ++f) { std::vector<BakeRect> o; s.update({0.05f, 0.05f}, 1LL << 40, o); }
    std::vector<BakeRect> out;
    s.update({0.15f, 0.05f}, 1LL << 40, out);     // level 0 nadir texel moves +1 in x
    long long l0 = 0; for (auto& r : out) if (r.level == 0) l0 += (long long)r.w * r.h;
    EXPECT_EQ(l0, 1024 + 2);                       // one column + its 2 guard texels
    for (auto& r : out) EXPECT_EQ(r.level, 0);     // coarser levels' nadir texel did not change
}

TEST(ClipmapSchedule, WrapSplitPiecesStayInsideTheBand) {
    ClipmapSchedule s(0.1f, oct5());
    for (float x = 0; x < 300.0f; x += 7.3f) {     // drive far enough to wrap every level
        std::vector<BakeRect> out; s.update({x, -x * 0.5f}, 65536LL * 8, out);
        for (auto& r : out) {
            EXPECT_GE(r.tor_x, 0); EXPECT_LE(r.tor_x + r.w, 1024);
            EXPECT_GE(r.band_row, 0); EXPECT_LE(r.band_row + r.h, 1026);
        }
    }
}

TEST(ClipmapSchedule, GuardRowsMirrorEdgeRows) {
    ClipmapSchedule s(0.1f, oct5());
    std::vector<BakeRect> all;
    for (int f = 0; f < 1000 && !s.complete({0, 0}); ++f) s.update({0, 0}, 65536LL * 8, all);
    // band row 0 must carry the abs row whose toroidal row is 1023; band row 1025 the one at toroidal 0.
    for (auto& r : all) {
        if (r.band_row == 0) { EXPECT_EQ(r.h, 1); EXPECT_EQ(((r.abs_y % 1024) + 1024) % 1024, 1023); }
        if (r.band_row + r.h - 1 == 1025 && r.h == 1) EXPECT_EQ(((r.abs_y % 1024) + 1024) % 1024, 0);
    }
}

TEST(ClipmapSchedule, DashStarvesFineLevelsButCostStaysCapped) {
    ClipmapSchedule s(0.1f, oct5());
    float x = 0;
    for (int f = 0; f < 300; ++f) {
        x += 400.0f / 60.0f;
        std::vector<BakeRect> out;
        EXPECT_LE(s.update({x, 0}, 65536LL * 8, out), 65536LL * 8 + 3 * 1024LL * 9);
    }
    EXPECT_FALSE(s.complete({x, 0}));
}
