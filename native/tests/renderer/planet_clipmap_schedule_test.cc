#include <gtest/gtest.h>
#include <renderer/planet_clipmap_schedule.h>
#include <climits>
#include <cstdio>
#include <random>
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

// T4: the toroidal content invariant. Simulates each level's 1024x1026 band
// from the emitted BakeRects (a texel records the ABSOLUTE texel last baked
// into it) and asserts, under motion, that every texel in valid(L) holds its
// own absolute texel -- including both guard rows -- through diagonal,
// backwards-diagonal (negative abs coords), straight-down (crossing toroidal
// rows 0/1023), random-jump and settle (unbounded budget, must complete)
// phases. Every frame checks a stride-7 subgrid plus each valid rect's edge
// rows/columns (where a move exposes stale texels first); every 8th frame and
// every phase end checks every texel.
namespace {
int tor(int a) { const int r = a % 1024; return r < 0 ? r + 1024 : r; }
struct Cell { int ax = INT_MIN, ay = INT_MIN; };
}  // namespace

TEST(ClipmapSchedule, ValidRegionContentInvariantUnderMotion) {
    constexpr int kLevels = 5, kPhaseFrames = 50, kCycles = 2;
    ClipmapSchedule s(0.1f, oct5());
    std::vector<std::vector<Cell>> band(kLevels, std::vector<Cell>(1024 * 1026));
    std::mt19937 rng(7);
    std::uniform_real_distribution<float> jump(-20.0f, 20.0f);
    glm::vec2 n(-3.0f, -5.0f);
    long long bad = 0;
    auto fail = [&](const char* what, int f, int L, int x, int y, Cell c) {
        if (bad++ < 10)
            ADD_FAILURE() << what << ": frame " << f << " L" << L << " abs (" << x << "," << y
                          << ") holds (" << c.ax << "," << c.ay << ")";
    };
    auto check = [&](int f, int L, int x, int y) {
        const Cell c = band[L][(tor(y) + 1) * 1024 + tor(x)];
        if (c.ax != x || c.ay != y) fail("stale content", f, L, x, y, c);
        if (tor(y) == 1023) {   // band row 0 mirrors toroidal row 1023
            const Cell g = band[L][tor(x)];
            if (g.ax != x || g.ay != y) fail("stale guard row 0", f, L, x, y, g);
        }
        if (tor(y) == 0) {      // band row 1025 mirrors toroidal row 0
            const Cell g = band[L][1025 * 1024 + tor(x)];
            if (g.ax != x || g.ay != y) fail("stale guard row 1025", f, L, x, y, g);
        }
    };
    int f = 0;
    for (int cycle = 0; cycle < kCycles; ++cycle) {
        for (int mode = 0; mode < 5; ++mode) {
            for (int i = 0; i < kPhaseFrames; ++i, ++f) {
                if (mode == 0) n += glm::vec2(1.3f, 1.1f);             // diagonal
                else if (mode == 1) n += glm::vec2(-2.7f, -0.9f);      // backwards diagonal
                else if (mode == 2) n += glm::vec2(0.0f, -6.6f);       // straight down
                else if (mode == 3) n += glm::vec2(jump(rng), jump(rng));   // random jumps
                // mode 4: settle in place, unbounded budget
                const long long budget = mode == 4 ? (1LL << 40) : 65536LL * 8;
                std::vector<BakeRect> out;
                const long long c = s.update(n, budget, out);
                if (mode != 4) EXPECT_LE(c, budget + 3 * 1024LL * 9) << "frame " << f;
                for (const auto& r : out) {
                    for (int y = 0; y < r.h; ++y) {
                        const int br = r.band_row + y, tr = tor(r.abs_y + y);
                        const bool row_ok = (br >= 1 && br <= 1024) ? tr + 1 == br
                                          : br == 0 ? tr == 1023 : br == 1025 ? tr == 0 : false;
                        if (!row_ok) ++bad;
                        for (int x = 0; x < r.w; ++x) {
                            const int tx = r.tor_x + x;
                            if (tx < 0 || tx >= 1024 || br < 0 || br >= 1026) { ++bad; continue; }
                            if (tor(r.abs_x + x) != tx) ++bad;
                            band[r.level][br * 1024 + tx] = {r.abs_x + x, r.abs_y + y};
                        }
                    }
                }
                const bool full = f % 8 == 0 || i == kPhaseFrames - 1;
                for (int L = 0; L < kLevels; ++L) {
                    const Rect V = s.valid(L);
                    if (V.empty()) continue;
                    if (full) {
                        for (int y = V.y0; y < V.y1; ++y)
                            for (int x = V.x0; x < V.x1; ++x) check(f, L, x, y);
                        continue;
                    }
                    for (int y = V.y0; y < V.y1; y += 7)
                        for (int x = V.x0; x < V.x1; x += 7) check(f, L, x, y);
                    for (int x = V.x0; x < V.x1; ++x) { check(f, L, x, V.y0); check(f, L, x, V.y1 - 1); }
                    for (int y = V.y0; y < V.y1; ++y) { check(f, L, V.x0, y); check(f, L, V.x1 - 1, y); }
                    // Both guard rows whenever the rect spans them.
                    for (int y = V.y0; y < V.y1; ++y)
                        if (tor(y) == 0 || tor(y) == 1023)
                            for (int x = V.x0; x < V.x1; ++x) check(f, L, x, y);
                }
            }
            if (mode == 4) EXPECT_TRUE(s.complete(n)) << "not complete after settle, frame " << f;
        }
    }
    EXPECT_EQ(bad, 0) << "final nadir (" << n.x << "," << n.y << ")";
}
