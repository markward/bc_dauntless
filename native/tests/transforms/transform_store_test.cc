#include <gtest/gtest.h>
#include "dauntless/transform_store.h"

#include <glm/glm.hpp>

using dauntless::TransformStore;

TEST(TransformStoreTest, NewSlotIsIdentityAtOrigin) {
    TransformStore s;
    auto [i, g] = s.alloc();
    auto p = s.position(i, g);
    EXPECT_DOUBLE_EQ(p[0], 0.0);
    EXPECT_DOUBLE_EQ(p[1], 0.0);
    EXPECT_DOUBLE_EQ(p[2], 0.0);
    auto r = s.rotation(i, g);
    EXPECT_DOUBLE_EQ(r[0], 1.0);
    EXPECT_DOUBLE_EQ(r[4], 1.0);
    EXPECT_DOUBLE_EQ(r[8], 1.0);
}

TEST(TransformStoreTest, ReusedIndexGetsNewGeneration) {
    TransformStore s;
    auto [i1, g1] = s.alloc();
    s.free(i1, g1);
    auto [i2, g2] = s.alloc();
    EXPECT_EQ(i2, i1);
    EXPECT_NE(g2, g1);
    EXPECT_FALSE(s.valid(i1, g1));
    EXPECT_TRUE(s.valid(i2, g2));
}

TEST(TransformStoreTest, GrowthPreservesExistingSlots) {
    TransformStore s;
    std::vector<std::pair<std::uint32_t, std::uint32_t>> handles;
    for (int n = 0; n < 500; ++n) {
        auto h = s.alloc();
        s.set_position(h.first, h.second,
                       static_cast<double>(n), 0.0, 0.0);
        handles.push_back(h);
    }
    for (int n = 0; n < 500; ++n) {
        auto p = s.position(handles[n].first, handles[n].second);
        EXPECT_DOUBLE_EQ(p[0], static_cast<double>(n));
    }
}

TEST(TransformStoreTest, RotationColReadsColumns) {
    TransformStore s;
    auto [i, g] = s.alloc();
    const std::array<double, 9> m{1, 2, 3, 4, 5, 6, 7, 8, 9};
    s.set_rotation(i, g, m);
    auto c1 = s.rotation_col(i, g, 1);
    EXPECT_DOUBLE_EQ(c1[0], 2.0);
    EXPECT_DOUBLE_EQ(c1[1], 5.0);
    EXPECT_DOUBLE_EQ(c1[2], 8.0);
}

TEST(TransformStoreTest, FreeListIsReused) {
    TransformStore s;
    for (int n = 0; n < 1000; ++n) {
        auto h = s.alloc();
        s.free(h.first, h.second);
    }
    EXPECT_EQ(s.live_count(), 0u);
    EXPECT_LE(s.capacity(), 4u);
}

TEST(TransformStoreTest, RecycledSlotDoesNotInheritPriorTransform) {
    TransformStore s;
    auto [i1, g1] = s.alloc();
    s.set_position(i1, g1, 42.0, -7.0, 3.5);
    const std::array<double, 9> distinctive{2, 0, 0, 0, 2, 0, 0, 0, 2};
    s.set_rotation(i1, g1, distinctive);
    s.free(i1, g1);

    auto [i2, g2] = s.alloc();
    ASSERT_EQ(i2, i1);
    auto p = s.position(i2, g2);
    EXPECT_DOUBLE_EQ(p[0], 0.0);
    EXPECT_DOUBLE_EQ(p[1], 0.0);
    EXPECT_DOUBLE_EQ(p[2], 0.0);
    auto r = s.rotation(i2, g2);
    EXPECT_DOUBLE_EQ(r[0], 1.0);
    EXPECT_DOUBLE_EQ(r[1], 0.0);
    EXPECT_DOUBLE_EQ(r[4], 1.0);
    EXPECT_DOUBLE_EQ(r[8], 1.0);
    s.free(i2, g2);
}

TEST(TransformStoreTest, RotationColOutOfRangeThrows) {
    TransformStore s;
    auto [i, g] = s.alloc();
    EXPECT_THROW(s.rotation_col(i, g, -1), std::out_of_range);
    EXPECT_THROW(s.rotation_col(i, g, 3), std::out_of_range);
    s.free(i, g);
}

// ── compose_world_matrix ─────────────────────────────────────────────────────
// The renderer's TRS composition. Must reproduce
// engine/host_loop.py:_world_matrix_from element for element: rotation
// (row-major) times uniform scale, translation in the fourth column, bottom
// row 0,0,0,1 — no transpose, no reflection.

TEST(ComposeWorldMatrixTest, RowMajorTrsMatchesHostLoopFormula) {
    TransformStore::Transform t{};
    t.pos[0] = 3.0; t.pos[1] = -4.0; t.pos[2] = 5.5;
    // Deliberately NOT orthonormal: the composition must copy the rotation
    // through untouched rather than re-derive or normalise it.
    const double r[9] = {0.11, 0.22, 0.33,
                         0.44, 0.55, 0.66,
                         0.77, 0.88, 0.99};
    for (int i = 0; i < 9; ++i) t.rot[i] = r[i];

    const double scale = 2.5;
    float m[16];
    dauntless::compose_world_matrix(t, scale, m);

    for (int row = 0; row < 3; ++row) {
        for (int col = 0; col < 3; ++col) {
            // Multiply in double, round to float once — matching
            // _world_matrix_from's `rot.m00*s` (Python floats are doubles).
            EXPECT_FLOAT_EQ(m[row * 4 + col],
                            static_cast<float>(r[row * 3 + col] * scale))
                << "row " << row << " col " << col;
        }
    }
    EXPECT_FLOAT_EQ(m[3],  3.0f);
    EXPECT_FLOAT_EQ(m[7],  -4.0f);
    EXPECT_FLOAT_EQ(m[11], 5.5f);
    EXPECT_FLOAT_EQ(m[12], 0.0f);
    EXPECT_FLOAT_EQ(m[13], 0.0f);
    EXPECT_FLOAT_EQ(m[14], 0.0f);
    EXPECT_FLOAT_EQ(m[15], 1.0f);
}

TEST(ComposeWorldMatrixTest, ScaleStaysDoublePrecisionThroughTheMultiply) {
    // Regression guard for the truncate-scale-to-float32-before-the-multiply
    // bug: if `scale` were rounded to a float BEFORE this multiply (as it was
    // when compose_world_matrix and its callers took `float scale`), this
    // exact (rotation, scale) pair rounds to a different float result than
    // multiplying in full double precision and rounding once at the end —
    // which is what _world_matrix_from does in Python (doubles throughout).
    // Values found by brute-force search for a pair whose two roundings
    // diverge by exactly one ULP.
    TransformStore::Transform t{};
    t.rot[0] = -1.0849511149181894;
    const double scale = 1890.541938400889;

    float m[16];
    dauntless::compose_world_matrix(t, scale, m);

    const float correct_double_precision_result =
        static_cast<float>(t.rot[0] * scale);
    const float wrong_truncate_first_result =
        static_cast<float>(t.rot[0] * static_cast<double>(
            static_cast<float>(scale)));
    ASSERT_NE(correct_double_precision_result, wrong_truncate_first_result)
        << "the chosen (rotation, scale) pair no longer straddles a float "
           "rounding boundary; pick new values";
    EXPECT_EQ(m[0], correct_double_precision_result);
}

TEST(ComposeWorldMatrixTest, DoesNotReflectTheXColumn) {
    // Regression guard: the pre-2026-06-18 determinant-normalisation flip
    // negated body X and drew every hull mirror-imaged. Identity in, positive
    // scale on the diagonal out.
    TransformStore s;
    auto [i, g] = s.alloc();
    float m[16];
    dauntless::compose_world_matrix(s.at(i), 3.0, m);
    EXPECT_FLOAT_EQ(m[0], 3.0f);
    EXPECT_FLOAT_EQ(m[5], 3.0f);
    EXPECT_FLOAT_EQ(m[10], 3.0f);
    s.free(i, g);
}

// ── compose_world_linear_translation ─────────────────────────────────────────
// The floating-render-origin composer: the SAME rotation·scale as
// compose_world_matrix, but the translation is handed back in DOUBLE, never
// narrowed. The narrowing happens later, once per frame, AFTER the render
// origin has been subtracted (World::resolve_render_space) — so a ship 1e6 GU
// out keeps its quarter-GU.

TEST(ComposeWorldLinearTranslationTest, TranslationSurvivesInDoubleExactly) {
    TransformStore::Transform t{};
    t.pos[0] = 1e6 + 0.25; t.pos[1] = -3e5; t.pos[2] = 7.5;
    glm::mat3 linear(0.0f);
    glm::dvec3 translation(0.0);
    dauntless::compose_world_linear_translation(t, 1.0, linear, translation);
    EXPECT_EQ(translation.x, 1e6 + 0.25);
    EXPECT_EQ(translation.y, -3e5);
    EXPECT_EQ(translation.z, 7.5);

    // 1e6 + 0.25 happens to be a float too (ulp at 1e6 is 0.0625). 1e6 + 0.3
    // is not — the value a float translation would have silently moved.
    t.pos[0] = 1e6 + 0.3;
    ASSERT_NE(static_cast<double>(static_cast<float>(t.pos[0])), t.pos[0]);
    dauntless::compose_world_linear_translation(t, 1.0, linear, translation);
    EXPECT_EQ(translation.x, 1e6 + 0.3);
}

TEST(ComposeWorldLinearTranslationTest, LinearEqualsComposeWorldMatrixUpperLeft) {
    TransformStore::Transform t{};
    t.pos[0] = 12.0; t.pos[1] = 34.0; t.pos[2] = 56.0;
    const double r[9] = {0.11, 0.22, 0.33,
                         0.44, 0.55, 0.66,
                         0.77, 0.88, 0.99};
    for (int i = 0; i < 9; ++i) t.rot[i] = r[i];
    t.rot[0] = -1.0849511149181894;   // the one-ULP double-vs-float scale case
    const double scale = 1890.541938400889;

    float m[16];
    dauntless::compose_world_matrix(t, scale, m);
    glm::mat3 linear(0.0f);
    glm::dvec3 translation(0.0);
    dauntless::compose_world_linear_translation(t, scale, linear, translation);

    // compose_world_matrix is ROW-major; glm is column-major: linear[col][row].
    for (int row = 0; row < 3; ++row)
        for (int col = 0; col < 3; ++col)
            EXPECT_EQ(linear[col][row], m[row * 4 + col])
                << "row " << row << " col " << col;
    EXPECT_EQ(translation, glm::dvec3(12.0, 34.0, 56.0));
}

// within_radius backs ProximityManager.GetNearObjects: one flag per handle,
// set when the position lies within (or exactly on) the sphere. The compare
// must round as CPython's `dx*dx + dy*dy + dz*dz <= r2` does.
TEST(TransformStoreTest, WithinRadiusFlagsEachHandleInOrder) {
    TransformStore s;
    std::vector<std::uint32_t> flat;
    const double xs[] = {1.0, 50.0, 3.0, -2.9, 0.0};
    for (double x : xs) {
        auto h = s.alloc();
        s.set_position(h.first, h.second, x, 0.0, 0.0);
        flat.push_back(h.first);
        flat.push_back(h.second);
    }
    const double p[3] = {0.0, 0.0, 0.0};
    std::vector<std::uint8_t> out(5, 7);
    s.within_radius(flat.data(), 5, p, 9.0, out.data());
    EXPECT_EQ(out, (std::vector<std::uint8_t>{1, 0, 1, 1, 1}));
}

TEST(TransformStoreTest, WithinRadiusMatchesTheUnfusedDoubleCompare) {
    TransformStore s;
    const double px = 0.1, py = -0.7, pz = 0.3;
    std::vector<std::uint32_t> flat;
    std::vector<double> want_r2;
    std::uint64_t seed = 12345;
    auto next = [&] {
        seed = seed * 6364136223846793005ull + 1442695040888963407ull;
        return static_cast<double>(seed >> 11) / 9007199254740992.0 * 200.0 - 100.0;
    };
    for (int n = 0; n < 400; ++n) {
        auto h = s.alloc();
        const double x = next(), y = next(), z = next();
        s.set_position(h.first, h.second, x, y, z);
        flat.push_back(h.first);
        flat.push_back(h.second);
        volatile double dx = x - px, dy = y - py, dz = z - pz;
        volatile double a = dx * dx, b = dy * dy, c = dz * dz;
        volatile double ab = a + b;
        want_r2.push_back(ab + c);
    }
    const double p[3] = {px, py, pz};
    std::vector<std::uint8_t> out(400);
    for (std::size_t k = 0; k < want_r2.size(); ++k) {
        // The boundary itself: a fused multiply-add flips some of these.
        s.within_radius(flat.data(), 400, p, want_r2[k], out.data());
        for (std::size_t j = 0; j < want_r2.size(); ++j)
            ASSERT_EQ(out[j], want_r2[j] <= want_r2[k] ? 1 : 0) << k << " " << j;
    }
}

TEST(TransformStoreTest, WithinRadiusRejectsAStaleHandle) {
    TransformStore s;
    auto h = s.alloc();
    s.free(h.first, h.second);
    std::uint32_t flat[2] = {h.first, h.second};
    const double p[3] = {0.0, 0.0, 0.0};
    std::uint8_t out[1];
    EXPECT_ANY_THROW(s.within_radius(flat, 1, p, 1.0, out));
}

namespace {
struct ProxPairs {
    std::vector<std::uint32_t> anchors, objects;
    std::vector<double> r2;
    std::vector<std::uint8_t> want;
    void add(std::pair<std::uint32_t, std::uint32_t> a,
             std::pair<std::uint32_t, std::uint32_t> o, double r, std::uint8_t w) {
        anchors.push_back(a.first); anchors.push_back(a.second);
        objects.push_back(o.first); objects.push_back(o.second);
        r2.push_back(r);
        want.push_back(w);
    }
    std::vector<std::uint32_t> report(const TransformStore& s, std::size_t start) const {
        std::vector<std::uint32_t> out;
        s.proximity_report(anchors.data(), objects.data(), r2.data(), want.data(),
                           want.size(), start, out);
        return out;
    }
};
}  // namespace

TEST(TransformStoreTest, ProximityReportListsMatchingPairsFromStart) {
    TransformStore s;
    auto centre = s.alloc();
    s.set_position(centre.first, centre.second, 10.0, 0.0, 0.0);
    auto near = s.alloc();
    s.set_position(near.first, near.second, 12.0, 0.0, 0.0);
    auto far = s.alloc();
    s.set_position(far.first, far.second, 50.0, 0.0, 0.0);
    auto edge = s.alloc();
    s.set_position(edge.first, edge.second, 13.0, 0.0, 0.0);
    ProxPairs p;
    p.add(centre, near, 9.0, 0);   // inside, wants inside: report
    p.add(centre, far, 9.0, 0);
    p.add(centre, near, 9.0, 1);
    p.add(centre, far, 9.0, 1);    // outside, wants outside: report
    p.add(centre, edge, 9.0, 0);   // on the sphere is inside: report
    p.add(centre, edge, 9.0, 1);
    p.add({0, 0}, {0, 0}, 0.0, 2); // always, handles unread
    p.add(centre, near, 9.0, 3);   // never
    EXPECT_EQ(p.report(s, 0), (std::vector<std::uint32_t>{0, 3, 4, 6}));
    EXPECT_EQ(p.report(s, 4), (std::vector<std::uint32_t>{4, 6}));
    EXPECT_EQ(p.report(s, 8), (std::vector<std::uint32_t>{}));
}

TEST(TransformStoreTest, ProximityReportListsAStaleHandleInsteadOfThrowing) {
    TransformStore s;
    auto live = s.alloc();
    auto gone = s.alloc();
    s.free(gone.first, gone.second);
    ProxPairs p;
    p.add(live, gone, 1.0, 3);
    p.add(gone, live, 1.0, 3);
    p.add(live, live, 1.0, 3);
    p.add(live, {999, 0}, 1.0, 3);
    EXPECT_EQ(p.report(s, 0), (std::vector<std::uint32_t>{0, 1, 3}));
}

TEST(TransformStoreTest, ProximityReportMatchesTheUnfusedDoubleCompare) {
    TransformStore s;
    std::uint64_t seed = 777;
    auto next = [&] {
        seed = seed * 6364136223846793005ull + 1442695040888963407ull;
        return static_cast<double>(seed >> 11) / 9007199254740992.0 * 200.0 - 100.0;
    };
    std::vector<std::pair<std::uint32_t, std::uint32_t>> hs;
    std::vector<std::array<double, 3>> pts;
    for (int n = 0; n < 40; ++n) {
        auto h = s.alloc();
        const std::array<double, 3> q{next(), next(), next()};
        s.set_position(h.first, h.second, q[0], q[1], q[2]);
        hs.push_back(h);
        pts.push_back(q);
    }
    ProxPairs p;
    std::vector<double> d2s;
    for (int a = 0; a < 40; ++a) {
        for (int o = 0; o < 40; ++o) {
            volatile double dx = pts[o][0] - pts[a][0];
            volatile double dy = pts[o][1] - pts[a][1];
            volatile double dz = pts[o][2] - pts[a][2];
            volatile double xx = dx * dx, yy = dy * dy, zz = dz * dz;
            volatile double xy = xx + yy;
            d2s.push_back(xy + zz);
        }
    }
    // Each radius sits exactly on some other pair's distance: a fused
    // multiply-add flips some of these.
    for (std::size_t k = 0; k < d2s.size(); ++k)
        p.add(hs[k / 40], hs[k % 40], d2s[(k * 7919) % d2s.size()], 0);
    std::vector<std::uint32_t> want;
    for (std::size_t k = 0; k < d2s.size(); ++k)
        if (d2s[k] <= p.r2[k]) want.push_back(static_cast<std::uint32_t>(k));
    EXPECT_EQ(p.report(s, 0), want);
}
