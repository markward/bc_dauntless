#include <gtest/gtest.h>
#include "dauntless/transform_store.h"

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
