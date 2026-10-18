// native/tests/voxel/field_brush_test.cc
//
// The subtractive brush. CSG subtraction on a signed distance field is
// d_new = max(d_old, -d_brush): a point is in (hull MINUS brush) iff it is
// inside the hull AND outside the brush.
//
// The brush is an OBLATE ellipsoid, not a sphere -- full lateral radius, and
// kCarveDepthFactor of it along the hit normal. That is the shape opaque.frag
// already clips, and the breach scoop still derives from the sphere list this
// plan does not remove, so carving the same shape keeps hole and scoop aligned.
#include <gtest/gtest.h>

#include <voxel/distance_field.h>
#include <voxel/field_brush.h>

#include <cmath>
#include <limits>
#include <vector>

namespace {

// A solid block: every cell reads -20 model units (deep inside), cell 1 unit,
// origin at 0, so cell (i,j,k)'s centre is (i+0.5, j+0.5, k+0.5).
voxel::DistanceField solid_block(int n) {
    voxel::DistanceField f;
    f.dims   = glm::ivec3(n, n, n);
    f.origin = glm::vec3(0.0f);
    f.cell   = glm::vec3(1.0f);
    f.scale  = 0.25f;                       // 127 * 0.25 ~= 31.75 units of range
    f.dist.assign(static_cast<std::size_t>(n) * n * n,
                  static_cast<std::int8_t>(-80));   // -20 units
    return f;
}

glm::ivec3 cell_of(const voxel::DistanceField& f, glm::vec3 p) {
    const glm::vec3 g = (p - f.origin) / f.cell;
    return glm::ivec3(int(std::floor(g.x)), int(std::floor(g.y)), int(std::floor(g.z)));
}

const glm::vec3 kUp(0.0f, 0.0f, 1.0f);

}  // namespace

TEST(FieldBrush, CentreOfTheCarveBecomesOutside) {
    voxel::DistanceField f = solid_block(40);
    voxel::field_carve_oblate(f, glm::vec3(20.0f, 20.0f, 20.0f), kUp, 6.0f);
    const glm::ivec3 c = cell_of(f, glm::vec3(20.0f, 20.0f, 20.0f));
    EXPECT_GT(f.distance_at(c.x, c.y, c.z), 0.0f)
        << "the carve centre must read as outside the hull";
}

TEST(FieldBrush, MaterialWellOutsideTheCarveIsUntouched) {
    voxel::DistanceField f = solid_block(40);
    const glm::ivec3 far = cell_of(f, glm::vec3(35.0f, 35.0f, 20.0f));
    const float before = f.distance_at(far.x, far.y, far.z);
    voxel::field_carve_oblate(f, glm::vec3(20.0f, 20.0f, 20.0f), kUp, 6.0f);
    EXPECT_FLOAT_EQ(f.distance_at(far.x, far.y, far.z), before)
        << "a carve must not modify material outside its own reach";
}

TEST(FieldBrush, ShapeIsOblateNotSpherical) {
    // Lateral reach is the full radius; along the normal it is kCarveDepthFactor
    // of it. At 0.8*r laterally the point is carved; at 0.8*r along the normal
    // (which exceeds 0.45*r) it is not.
    voxel::DistanceField f = solid_block(40);
    const glm::vec3 c(20.0f, 20.0f, 20.0f);
    const float r = 8.0f;
    voxel::field_carve_oblate(f, c, kUp, r);

    const glm::ivec3 lat = cell_of(f, c + glm::vec3(0.8f * r, 0.0f, 0.0f));
    EXPECT_GT(f.distance_at(lat.x, lat.y, lat.z), 0.0f) << "lateral reach too short";

    const glm::ivec3 along = cell_of(f, c + kUp * (0.8f * r));
    EXPECT_LT(f.distance_at(along.x, along.y, along.z), 0.0f)
        << "carve reaches too deep along the normal -- it is not oblate";
}

TEST(FieldBrush, OverlappingCarvesUnionRatherThanReplace) {
    // The whole point of the field over a sphere list: two overlapping carves
    // leave ONE cavity, and neither undoes the other. This test discriminates by
    // checking the VALUE at x=19 (centre 19.5), where both carves visit and
    // disagree. Cell (19,20,20) has centre (19.5, 20.5, 20.5), accounting for
    // y/z offsets that affect the ellipsoid distance. Correct max() gives 2.25,
    // overwrite bug gives 1.75. EXPECT_NEAR with tolerance 0.13 catches this.
    //
    // The expected VALUE (not the 0.5 gap that gives this test its teeth) moved
    // from 0.5 when the brush became conservative: the lateral half-extent grew
    // to radius*(1+kCarveRimAmp), the half-depth is floored at
    // kCarveDepthFloorCells cells, and kCarveFieldOffsetCells dilates the
    // result. Both branches shifted by the same amount, so the overwrite bug is
    // still 0.5 below the correct answer and still outside the tolerance --
    // measured, not assumed.
    voxel::DistanceField f = solid_block(40);
    voxel::field_carve_oblate(f, glm::vec3(16.0f, 20.0f, 20.0f), kUp, 5.0f);
    voxel::field_carve_oblate(f, glm::vec3(24.0f, 20.0f, 20.0f), kUp, 5.0f);

    const glm::ivec3 overlap_point = cell_of(f, glm::vec3(19.0f, 20.0f, 20.0f));
    EXPECT_NEAR(f.distance_at(overlap_point.x, overlap_point.y, overlap_point.z), 2.25f, 0.13f)
        << "x=19 is in the overlap region where carves differ; "
        "correct max() gives 2.25, overwrite bug gives 1.75";

    // Also verify the endpoints are carved.
    const glm::ivec3 c1 = cell_of(f, glm::vec3(16.0f, 20.0f, 20.0f));
    EXPECT_GT(f.distance_at(c1.x, c1.y, c1.z), 0.0f)
        << "carve 1 centre should be inside the cavity";
    const glm::ivec3 c2 = cell_of(f, glm::vec3(24.0f, 20.0f, 20.0f));
    EXPECT_GT(f.distance_at(c2.x, c2.y, c2.z), 0.0f)
        << "carve 2 centre should be inside the cavity";
}

TEST(FieldBrush, CarvingIsMonotonic) {
    // Re-carving the same place must never restore material.
    voxel::DistanceField f = solid_block(40);
    const glm::vec3 c(20.0f, 20.0f, 20.0f);
    voxel::field_carve_oblate(f, c, kUp, 8.0f);
    const glm::ivec3 q = cell_of(f, c + glm::vec3(6.0f, 0.0f, 0.0f));
    const float after_big = f.distance_at(q.x, q.y, q.z);
    voxel::field_carve_oblate(f, c, kUp, 2.0f);      // smaller, same centre
    EXPECT_GE(f.distance_at(q.x, q.y, q.z), after_big)
        << "a later smaller carve must not heal the hull";
}

TEST(FieldBrush, EmptyFieldIsANoOp) {
    voxel::DistanceField f;                  // dims {0,0,0}
    voxel::field_carve_oblate(f, glm::vec3(0.0f), kUp, 5.0f);
    EXPECT_TRUE(f.empty());
}

TEST(FieldBrush, NonPositiveRadiusIsANoOp) {
    voxel::DistanceField f = solid_block(20);
    const std::vector<std::int8_t> before = f.dist;
    voxel::field_carve_oblate(f, glm::vec3(10.0f), kUp, 0.0f);
    EXPECT_EQ(f.dist, before);
    voxel::field_carve_oblate(f, glm::vec3(10.0f), kUp, -3.0f);
    EXPECT_EQ(f.dist, before);
}

TEST(FieldBrush, DegenerateNormalDoesNotProduceNaN) {
    voxel::DistanceField f = solid_block(20);
    voxel::field_carve_oblate(f, glm::vec3(10.0f), glm::vec3(0.0f), 4.0f);
    for (std::int8_t v : f.dist) EXPECT_TRUE(v >= -127 && v <= 127);
}

TEST(FieldBrush, CarveOutsideTheGridDoesNotWriteOutOfBounds) {
    voxel::DistanceField f = solid_block(20);
    const std::vector<std::int8_t> before = f.dist;
    voxel::field_carve_oblate(f, glm::vec3(500.0f, 500.0f, 500.0f), kUp, 5.0f);
    EXPECT_EQ(f.dist, before);
}

TEST(FieldBrush, NonFiniteRadiusIsANoOp) {
    voxel::DistanceField f = solid_block(20);
    const std::vector<std::int8_t> before = f.dist;
    voxel::field_carve_oblate(f, glm::vec3(10.0f), kUp, std::numeric_limits<float>::infinity());
    EXPECT_EQ(f.dist, before);
    voxel::field_carve_oblate(f, glm::vec3(10.0f), kUp, std::numeric_limits<float>::quiet_NaN());
    EXPECT_EQ(f.dist, before);
}

TEST(FieldBrush, NonFiniteCentreComponentIsANoOp) {
    voxel::DistanceField f = solid_block(20);
    const std::vector<std::int8_t> before = f.dist;
    voxel::field_carve_oblate(f, glm::vec3(std::numeric_limits<float>::infinity(), 10.0f, 10.0f), kUp, 4.0f);
    EXPECT_EQ(f.dist, before);
    voxel::field_carve_oblate(f, glm::vec3(10.0f, std::numeric_limits<float>::quiet_NaN(), 10.0f), kUp, 4.0f);
    EXPECT_EQ(f.dist, before);
    voxel::field_carve_oblate(f, glm::vec3(10.0f, 10.0f, -std::numeric_limits<float>::infinity()), kUp, 4.0f);
    EXPECT_EQ(f.dist, before);
}

TEST(FieldBrush, NonFiniteNormalComponentIsANoOp) {
    voxel::DistanceField f = solid_block(20);
    const std::vector<std::int8_t> before = f.dist;
    voxel::field_carve_oblate(f, glm::vec3(10.0f), glm::vec3(std::numeric_limits<float>::infinity(), 0.0f, 0.0f), 4.0f);
    EXPECT_EQ(f.dist, before);
    voxel::field_carve_oblate(f, glm::vec3(10.0f), glm::vec3(0.0f, std::numeric_limits<float>::quiet_NaN(), 0.0f), 4.0f);
    EXPECT_EQ(f.dist, before);
    voxel::field_carve_oblate(f, glm::vec3(10.0f), glm::vec3(0.0f, 0.0f, -std::numeric_limits<float>::infinity()), 4.0f);
    EXPECT_EQ(f.dist, before);
}

// Trilinear reconstruction on CELL CENTRES, matching opaque.frag's
// sample_hull_field: it offsets by -0.5 cell, so an integer sample
// coordinate lands exactly on a stored cell's centre. Returns the value in
// STORED int8 units; the shader's `> 0.5/255` after its /255 normalisation
// is this function's `> 0.5`.
static float trilinear_int8(const voxel::DistanceField& f, const glm::vec3& p) {
    const glm::vec3 g = (p - f.origin) / f.cell - 0.5f;
    const glm::ivec3 i0(int(std::floor(g.x)), int(std::floor(g.y)),
                        int(std::floor(g.z)));
    const glm::vec3 t = g - glm::vec3(i0);
    float acc = 0.0f;
    for (int dz = 0; dz < 2; ++dz)
    for (int dy = 0; dy < 2; ++dy)
    for (int dx = 0; dx < 2; ++dx) {
        const glm::ivec3 ii = glm::clamp(i0 + glm::ivec3(dx, dy, dz),
                                         glm::ivec3(0), f.dims - 1);
        const float w = (dx ? t.x : 1.0f - t.x) * (dy ? t.y : 1.0f - t.y)
                      * (dz ? t.z : 1.0f - t.z);
        acc += w * static_cast<float>(f.dist[f.index(ii.x, ii.y, ii.z)]);
    }
    return acc;
}

// A carve far smaller than one cell must still leave a REPRESENTABLE hole:
// the field, reconstructed the way the shaders reconstruct it, must read
// "damaged" across the whole footprint opaque.frag would cut. Before the
// conservative brush this read -127 everywhere but (at best) one cell, which
// is exactly why breach.frag:335 bailed and holes showed space.
TEST(FieldBrushConservative, SubCellCarveSurvivesReconstruction) {
    voxel::DistanceField f;
    f.dims   = glm::ivec3(24, 24, 24);
    f.cell   = glm::vec3(5.0f, 5.0f, 5.0f);   // Galaxy: authored_res 10 / quality 2
    f.origin = glm::vec3(-60.0f, -60.0f, -60.0f);
    f.scale  = 4.0f * 5.0f / 127.0f;          // kDefaultBandCells * cell / 127
    f.dist.assign(24u * 24u * 24u, static_cast<std::int8_t>(-127));

    // Carve centre deliberately at a cell CORNER -- the worst placement, and
    // the one the coverage sweep found reading 0%.
    const glm::vec3 c(0.0f, 0.0f, 0.0f);
    const glm::vec3 n(0.0f, 0.0f, 1.0f);
    const float radius = 3.0f;                 // a fresh combat hit
    voxel::field_carve_oblate(f, c, n, radius);

    // Sample the hole opaque.frag would cut: the disc at along = 0 out to the
    // UNPERTURBED radius (a strict subset of its noise-perturbed rim).
    int total = 0, damaged = 0;
    for (int i = 0; i < 64; ++i) {
        const float th = 6.28318530718f * float(i) / 64.0f;
        for (int j = 1; j <= 8; ++j) {
            const float rad = radius * float(j) / 8.0f;
            const glm::vec3 p(rad * std::cos(th), rad * std::sin(th), 0.0f);
            ++total;
            if (trilinear_int8(f, p) > 0.5f) ++damaged;
        }
    }
    EXPECT_EQ(damaged, total)
        << "hole fragments with no damage behind them: " << (total - damaged)
        << " of " << total;
}

// The invariant the whole plan rests on: every point opaque.frag would
// discard as hull must read damaged in the field. Swept across BC's full
// authored resolution range (cell = authored_res/quality, authored_res 6-15,
// quality 2 => cell 3.0-7.5), the full carve radius range hit_feedback can
// produce (3-30 model units), and sub-cell placements -- because the defect
// this guards was placement-dependent and read 0% at cell corners.
TEST(FieldBrushConservative, HoleIsAlwaysBackedAcrossTheParameterRange) {
    const float cells[]   = {3.0f, 5.0f, 7.5f};
    const float radii[]   = {3.0f, 5.0f, 8.0f, 10.0f, 20.0f, 30.0f};
    // Sub-cell placements of the LATTICE relative to the carve. Which offset
    // puts the carve on a cell centre and which on a cell corner depends on
    // the parity of n, which varies across this sweep, so all four are swept
    // rather than trusting any one of them to be the worst case. Measured
    // against the pre-conservative brush at cell=3 radius=3: 576/576 hole
    // fragments un-backed at off=0.0, 208/576 at off=0.5.
    const float offsets[] = {0.0f, 0.25f, 0.5f, 0.75f};

    for (float cell : cells)
    for (float radius : radii)
    for (float off : offsets) {
        // Box big enough for the dilated brush plus a margin, on any axis.
        const int n = int(std::ceil((radius * 4.0f + cell * 8.0f) / cell)) + 4;
        voxel::DistanceField f;
        f.dims   = glm::ivec3(n, n, n);
        f.cell   = glm::vec3(cell);
        f.scale  = 4.0f * cell / 127.0f;
        f.origin = glm::vec3(-0.5f * float(n) * cell) + glm::vec3(off * cell);
        f.dist.assign(std::size_t(n) * n * n, static_cast<std::int8_t>(-127));

        voxel::field_carve_oblate(f, glm::vec3(0.0f),
                                  glm::vec3(0.0f, 0.0f, 1.0f), radius);

        // opaque.frag cuts where its perturbed rim allows, out to
        // radius * (1 + kShapeAmp) at the extreme. Sample that whole disc.
        const float rim = radius * (1.0f + voxel::kCarveRimAmp);
        int total = 0, undamaged = 0;
        for (int i = 0; i < 48; ++i) {
            const float th = 6.28318530718f * float(i) / 48.0f;
            for (int j = 1; j <= 12; ++j) {
                const float rad = rim * float(j) / 12.0f;
                const glm::vec3 p(rad * std::cos(th), rad * std::sin(th), 0.0f);
                ++total;
                if (trilinear_int8(f, p) <= 0.5f) ++undamaged;
            }
        }
        EXPECT_EQ(undamaged, 0)
            << "cell=" << cell << " radius=" << radius << " offset=" << off
            << ": " << undamaged << " of " << total
            << " hole fragments have no damage behind them";
    }
}

// A capsule cut must be backed by the field everywhere inside its nominal
// radius, across the authored cell range and the cascade's radius range --
// the same representability invariant plan 2c established for the oblate.
TEST(FieldBrushCapsule, CutIsAlwaysBackedAcrossTheParameterRange) {
    const float cells[] = {3.0f, 5.0f, 7.5f};
    const float radii[] = {30.0f, 60.0f, 100.0f};   // 0.3, 0.6, 1.0 GU
    for (float cell : cells)
    for (float radius : radii) {
        const int n = int(std::ceil((200.0f + radius * 4.0f + cell * 8.0f) / cell)) + 4;
        voxel::DistanceField f;
        f.dims = glm::ivec3(n, n / 2 + 8, n / 2 + 8);
        f.cell = glm::vec3(cell);
        f.scale = 4.0f * cell / 127.0f;
        f.origin = glm::vec3(-0.5f * float(n) * cell,
                             -0.5f * float(n / 2 + 8) * cell,
                             -0.5f * float(n / 2 + 8) * cell)
                 + glm::vec3(0.37f * cell);   // off-centre placement
        f.dist.assign(std::size_t(f.dims.x) * f.dims.y * f.dims.z,
                      static_cast<std::int8_t>(-127));

        const glm::vec3 p0(-100.0f, 0.0f, 0.0f), p1(100.0f, 0.0f, 0.0f);
        voxel::field_carve_capsule(f, p0, p1, radius);

        int total = 0, undamaged = 0;
        for (int i = 0; i <= 40; ++i) {              // along the segment
            const float t = float(i) / 40.0f;
            const glm::vec3 axis = p0 + (p1 - p0) * t;
            for (int j = 0; j < 12; ++j) {           // around it
                const float th = 6.28318530718f * float(j) / 12.0f;
                for (int k = 1; k <= 4; ++k) {       // out to the nominal radius
                    const float rad = radius * float(k) / 4.0f;
                    const glm::vec3 p = axis + glm::vec3(0.0f, rad * std::cos(th), rad * std::sin(th));
                    ++total;
                    if (trilinear_int8(f, p) <= 0.5f) ++undamaged;
                }
            }
        }
        EXPECT_EQ(undamaged, 0) << "cell=" << cell << " radius=" << radius
                                << ": " << undamaged << " of " << total
                                << " capsule points have no damage";
    }
}

TEST(FieldBrushCapsule, IsMonotonicAndLeavesFarCellsUntouched) {
    voxel::DistanceField f;
    f.dims = glm::ivec3(40, 20, 20);
    f.cell = glm::vec3(5.0f);
    f.scale = 4.0f * 5.0f / 127.0f;
    f.origin = glm::vec3(-100.0f, -50.0f, -50.0f);
    f.dist.assign(40u * 20u * 20u, static_cast<std::int8_t>(-127));
    voxel::field_carve_capsule(f, glm::vec3(-40, 0, 0), glm::vec3(40, 0, 0), 10.0f);
    // A cell far from the capsule is untouched.
    EXPECT_EQ(f.dist[f.index(39, 19, 19)], -127);
    // Carving the same capsule again changes nothing (idempotent under max).
    const auto before = f.dist;
    voxel::field_carve_capsule(f, glm::vec3(-40, 0, 0), glm::vec3(40, 0, 0), 10.0f);
    EXPECT_EQ(f.dist, before);
    // A smaller capsule inside it cannot restore material.
    voxel::field_carve_capsule(f, glm::vec3(-10, 0, 0), glm::vec3(10, 0, 0), 2.0f);
    for (std::size_t i = 0; i < f.dist.size(); ++i) EXPECT_GE(f.dist[i], before[i]);
}

// The five no-op guards field_carve_capsule documents, one test each, mirroring
// the oblate brush's guard tests (FieldBrush.EmptyFieldIsANoOp etc. above) shape
// for shape -- so a future refactor cannot silently drop one.

TEST(FieldBrushCapsule, EmptyFieldIsANoOp) {
    voxel::DistanceField f;                  // dims {0,0,0}
    voxel::field_carve_capsule(f, glm::vec3(0.0f), glm::vec3(1.0f, 0.0f, 0.0f), 5.0f);
    EXPECT_TRUE(f.empty());
}

TEST(FieldBrushCapsule, NonPositiveRadiusIsANoOp) {
    voxel::DistanceField f = solid_block(20);
    const std::vector<std::int8_t> before = f.dist;
    voxel::field_carve_capsule(f, glm::vec3(8.0f, 10.0f, 10.0f), glm::vec3(12.0f, 10.0f, 10.0f), 0.0f);
    EXPECT_EQ(f.dist, before);
    voxel::field_carve_capsule(f, glm::vec3(8.0f, 10.0f, 10.0f), glm::vec3(12.0f, 10.0f, 10.0f), -3.0f);
    EXPECT_EQ(f.dist, before);
}

TEST(FieldBrushCapsule, NonFiniteRadiusIsANoOp) {
    voxel::DistanceField f = solid_block(20);
    const std::vector<std::int8_t> before = f.dist;
    voxel::field_carve_capsule(f, glm::vec3(8.0f, 10.0f, 10.0f), glm::vec3(12.0f, 10.0f, 10.0f),
                               std::numeric_limits<float>::infinity());
    EXPECT_EQ(f.dist, before);
    voxel::field_carve_capsule(f, glm::vec3(8.0f, 10.0f, 10.0f), glm::vec3(12.0f, 10.0f, 10.0f),
                               std::numeric_limits<float>::quiet_NaN());
    EXPECT_EQ(f.dist, before);
}

TEST(FieldBrushCapsule, NonFiniteEndpointComponentIsANoOp) {
    voxel::DistanceField f = solid_block(20);
    const std::vector<std::int8_t> before = f.dist;
    const float inf = std::numeric_limits<float>::infinity();
    const float nan = std::numeric_limits<float>::quiet_NaN();
    voxel::field_carve_capsule(f, glm::vec3(inf, 10.0f, 10.0f), glm::vec3(12.0f, 10.0f, 10.0f), 4.0f);
    EXPECT_EQ(f.dist, before);
    voxel::field_carve_capsule(f, glm::vec3(8.0f, nan, 10.0f), glm::vec3(12.0f, 10.0f, 10.0f), 4.0f);
    EXPECT_EQ(f.dist, before);
    voxel::field_carve_capsule(f, glm::vec3(8.0f, 10.0f, -inf), glm::vec3(12.0f, 10.0f, 10.0f), 4.0f);
    EXPECT_EQ(f.dist, before);
    voxel::field_carve_capsule(f, glm::vec3(8.0f, 10.0f, 10.0f), glm::vec3(inf, 10.0f, 10.0f), 4.0f);
    EXPECT_EQ(f.dist, before);
    voxel::field_carve_capsule(f, glm::vec3(8.0f, 10.0f, 10.0f), glm::vec3(12.0f, nan, 10.0f), 4.0f);
    EXPECT_EQ(f.dist, before);
    voxel::field_carve_capsule(f, glm::vec3(8.0f, 10.0f, 10.0f), glm::vec3(12.0f, 10.0f, -inf), 4.0f);
    EXPECT_EQ(f.dist, before);
}

TEST(FieldBrushCapsule, CarveOutsideTheGridDoesNotWriteOutOfBounds) {
    // The segment (and its r+offset reach) sit entirely beyond the field's
    // [0,20] bounds on every axis -- wholly off-grid.
    voxel::DistanceField f = solid_block(20);
    const std::vector<std::int8_t> before = f.dist;
    voxel::field_carve_capsule(f, glm::vec3(500.0f, 500.0f, 500.0f),
                               glm::vec3(510.0f, 500.0f, 500.0f), 5.0f);
    EXPECT_EQ(f.dist, before);
}

TEST(FieldBrushCapsule, DegenerateSegmentBehavesAsSphereAndDoesNotProduceNaN) {
    // p0 == p1: the segment collapses to a point, so the capsule must behave
    // as a sphere of radius `radius` centred there, not a no-op and not NaN.
    voxel::DistanceField f = solid_block(20);
    const glm::vec3 p(10.0f, 10.0f, 10.0f);
    voxel::field_carve_capsule(f, p, p, 4.0f);
    for (std::int8_t v : f.dist) EXPECT_TRUE(v >= -127 && v <= 127);
    const glm::ivec3 c = cell_of(f, p);
    EXPECT_GT(f.distance_at(c.x, c.y, c.z), 0.0f)
        << "a degenerate segment must still carve a sphere at p0, not no-op";
}

// ── Touched-cell box ────────────────────────────────────────────────────────
// Both brushes return the inclusive cell box they wrote, so the atlas upload
// and the severance check can work on that box instead of the whole lattice.
// The contract is "every changed cell lies inside the box", not "the box is
// tight" -- an over-wide box costs a few extra texels, an under-wide one
// silently leaves stale texels on the GPU.

TEST(FieldBrushBox, EveryChangedCellLiesInsideTheReportedBox) {
    voxel::DistanceField f = solid_block(40);
    const voxel::DistanceField before = f;
    const voxel::CellBox box =
        voxel::field_carve_oblate(f, glm::vec3(20.0f, 20.0f, 20.0f), kUp, 6.0f);
    ASSERT_FALSE(box.empty());
    for (int z = 0; z < 40; ++z) for (int y = 0; y < 40; ++y) for (int x = 0; x < 40; ++x) {
        const std::size_t i = f.index(x, y, z);
        if (f.dist[i] == before.dist[i]) continue;
        EXPECT_TRUE(box.contains(glm::ivec3(x, y, z)))
            << "cell (" << x << "," << y << "," << z << ") changed outside the box";
    }
    EXPECT_LT(box.hi.x - box.lo.x, 40 - 1) << "the box must not be the whole lattice";
}

TEST(FieldBrushBox, BoxIsClampedToTheLattice) {
    voxel::DistanceField f = solid_block(20);
    const voxel::CellBox box =
        voxel::field_carve_oblate(f, glm::vec3(0.5f, 0.5f, 0.5f), kUp, 6.0f);
    ASSERT_FALSE(box.empty());
    EXPECT_EQ(box.lo, glm::ivec3(0));
    EXPECT_LT(box.hi.x, 20);
}

TEST(FieldBrushBox, NoOpCarvesReportAnEmptyBox) {
    voxel::DistanceField f = solid_block(20);
    EXPECT_TRUE(voxel::field_carve_oblate(f, glm::vec3(10.0f), kUp, 0.0f).empty());
    EXPECT_TRUE(voxel::field_carve_oblate(f, glm::vec3(500.0f, 10.0f, 10.0f), kUp, 2.0f).empty())
        << "wholly off-grid";
    voxel::DistanceField empty;
    EXPECT_TRUE(voxel::field_carve_oblate(empty, glm::vec3(10.0f), kUp, 2.0f).empty());
}

TEST(FieldBrushBox, CapsuleReportsItsBoxToo) {
    voxel::DistanceField f = solid_block(40);
    const voxel::DistanceField before = f;
    const voxel::CellBox box = voxel::field_carve_capsule(
        f, glm::vec3(10.0f, 20.0f, 20.0f), glm::vec3(30.0f, 20.0f, 20.0f), 3.0f);
    ASSERT_FALSE(box.empty());
    for (int z = 0; z < 40; ++z) for (int y = 0; y < 40; ++y) for (int x = 0; x < 40; ++x) {
        const std::size_t i = f.index(x, y, z);
        if (f.dist[i] != before.dist[i])
            EXPECT_TRUE(box.contains(glm::ivec3(x, y, z)));
    }
    EXPECT_TRUE(voxel::field_carve_capsule(f, glm::vec3(10.0f), glm::vec3(30.0f), 0.0f).empty());
}

TEST(FieldBrushBox, UnionGrowsToCoverBoth) {
    voxel::CellBox a{glm::ivec3(2, 3, 4), glm::ivec3(5, 6, 7)};
    voxel::CellBox b{glm::ivec3(0, 4, 9), glm::ivec3(3, 9, 9)};
    a.include(b);
    EXPECT_EQ(a.lo, glm::ivec3(0, 3, 4));
    EXPECT_EQ(a.hi, glm::ivec3(5, 9, 9));
    voxel::CellBox e;
    ASSERT_TRUE(e.empty());
    e.include(b);
    EXPECT_EQ(e.lo, b.lo);
    EXPECT_EQ(e.hi, b.hi);
    b.include(voxel::CellBox{});
    EXPECT_EQ(b.lo, glm::ivec3(0, 4, 9)) << "including an empty box changes nothing";
}

// ── Tight box, and no work where nothing can change (perf-register P-4) ─────
// A carve returns the box of cells it actually CHANGED, not the brush's
// reach. The upload and the severance check both key off that box, so a
// carve that changes nothing -- a brush landing on material already fully
// carved (+127, the ceiling of the monotonic max) -- must report an empty
// box. Measured: a dead Haven station's wreck took six 35 GU carves, each
// covering the whole 13.4 M-cell lattice; the first saturated every cell,
// the other five changed none yet cost 1.5 s of brush plus a full re-upload
// and a full-lattice BFS each.

namespace {

// The brush loops exactly as they were before the fast paths: every cell in
// the reach box, no skip, no fill. The fast paths must match these byte for
// byte. The reach box is part of the behaviour, not just a bound: the oblate's
// distance is scaled by its SMALLEST half-extent, so outside the box it would
// still raise very deep cells -- the brush never writes there.
bool reach_cells(const voxel::DistanceField& f, glm::vec3 lo, glm::vec3 hi,
                 glm::ivec3& c0, glm::ivec3& c1) {
    auto to_cell = [&](const glm::vec3& p) {
        const glm::vec3 g = (p - f.origin) / f.cell;
        return glm::ivec3(int(std::floor(g.x)), int(std::floor(g.y)), int(std::floor(g.z)));
    };
    c0 = glm::max(to_cell(lo), glm::ivec3(0));
    c1 = glm::min(to_cell(hi), f.dims - 1);
    return !(c0.x > c1.x || c0.y > c1.y || c0.z > c1.z);
}

void reference_oblate(voxel::DistanceField& f, glm::vec3 c, glm::vec3 n,
                      float radius) {
    const float nl = glm::length(n);
    n = (nl > 1e-4f) ? n / nl : glm::vec3(0.0f, 0.0f, 1.0f);
    const float min_cell = std::min(f.cell.x, std::min(f.cell.y, f.cell.z));
    const float lat    = radius * (1.0f + voxel::kCarveRimAmp);
    const float depth  = std::max(voxel::kCarveDepthFactor * radius,
                                  voxel::kCarveDepthFloorCells * min_cell);
    const float offset = voxel::kCarveFieldOffsetCells * min_cell;
    const float reach = std::max(lat, depth) * (1.0f + offset / std::min(lat, depth));
    glm::ivec3 c0, c1;
    if (!reach_cells(f, c - glm::vec3(reach), c + glm::vec3(reach), c0, c1)) return;
    for (int z = c0.z; z <= c1.z; ++z)
    for (int y = c0.y; y <= c1.y; ++y)
    for (int x = c0.x; x <= c1.x; ++x) {
        const glm::vec3 p = f.origin + (glm::vec3(x, y, z) + 0.5f) * f.cell;
        const glm::vec3 v = p - c;
        const float along = glm::dot(v, n);
        const float ld = glm::length(v - along * n);
        const float u = ld / lat;
        const float w = along / depth;
        const float d_brush = (std::sqrt(u * u + w * w) - 1.0f) * std::min(lat, depth);
        const std::size_t i = f.index(x, y, z);
        const float d_new = std::max(static_cast<float>(f.dist[i]) * f.scale,
                                     -d_brush + offset);
        float q = std::round(d_new / f.scale);
        q = std::max(-127.0f, std::min(127.0f, q));
        f.dist[i] = static_cast<std::int8_t>(q);
    }
}

void reference_capsule(voxel::DistanceField& f, glm::vec3 p0, glm::vec3 p1,
                       float radius) {
    const float min_cell = std::min(f.cell.x, std::min(f.cell.y, f.cell.z));
    const float r      = std::max(radius, voxel::kCarveDepthFloorCells * min_cell);
    const float offset = voxel::kCarveFieldOffsetCells * min_cell;
    const glm::vec3 ab = p1 - p0;
    const float ab2 = glm::dot(ab, ab);
    glm::ivec3 c0, c1;
    if (!reach_cells(f, glm::min(p0, p1) - glm::vec3(r + offset),
                     glm::max(p0, p1) + glm::vec3(r + offset), c0, c1)) return;
    for (int z = c0.z; z <= c1.z; ++z)
    for (int y = c0.y; y <= c1.y; ++y)
    for (int x = c0.x; x <= c1.x; ++x) {
        const glm::vec3 p = f.origin + (glm::vec3(x, y, z) + 0.5f) * f.cell;
        const float t = (ab2 > 0.0f)
            ? std::max(0.0f, std::min(1.0f, glm::dot(p - p0, ab) / ab2)) : 0.0f;
        const float d_brush = glm::length(p - (p0 + ab * t)) - r;
        const std::size_t i = f.index(x, y, z);
        const float d_new = std::max(static_cast<float>(f.dist[i]) * f.scale,
                                     -d_brush + offset);
        float q = std::round(d_new / f.scale);
        q = std::max(-127.0f, std::min(127.0f, q));
        f.dist[i] = static_cast<std::int8_t>(q);
    }
}

// Deterministic mixed field: deep material, surface values, and some cells
// already at the +127 ceiling, so every branch of a fast path is exercised.
voxel::DistanceField mixed_field(glm::ivec3 dims) {
    voxel::DistanceField f;
    f.dims   = dims;
    f.origin = glm::vec3(-1.5f, 2.0f, 0.25f);
    f.cell   = glm::vec3(1.0f, 1.25f, 0.75f);
    f.scale  = 0.25f;
    f.dist.resize(static_cast<std::size_t>(dims.x) * dims.y * dims.z);
    std::uint32_t s = 12345u;
    for (auto& d : f.dist) {
        s = s * 1664525u + 1013904223u;
        const std::uint32_t r = s >> 24;
        d = (r < 40) ? std::int8_t(127) : static_cast<std::int8_t>(int(r % 255) - 127);
    }
    return f;
}

voxel::CellBox changed_box(const voxel::DistanceField& a, const voxel::DistanceField& b) {
    voxel::CellBox box;
    for (int z = 0; z < a.dims.z; ++z) for (int y = 0; y < a.dims.y; ++y)
    for (int x = 0; x < a.dims.x; ++x) {
        const std::size_t i = a.index(x, y, z);
        if (a.dist[i] != b.dist[i])
            box.include(voxel::CellBox{glm::ivec3(x, y, z), glm::ivec3(x, y, z)});
    }
    return box;
}

void expect_same_box(const voxel::CellBox& got, const voxel::CellBox& want) {
    ASSERT_EQ(got.empty(), want.empty());
    if (want.empty()) return;
    EXPECT_EQ(got.lo, want.lo);
    EXPECT_EQ(got.hi, want.hi);
}

}  // namespace

TEST(FieldBrushTight, OblateMatchesTheReferenceAndReportsOnlyChangedCells) {
    struct Case { glm::vec3 c; glm::vec3 n; float r; const char* what; };
    const Case cases[] = {
        {{10.0f, 14.0f, 9.0f}, {0.0f, 0.0f, 1.0f}, 4.0f,   "small, interior"},
        {{2.0f, 30.0f, 3.0f},  {0.3f, -0.4f, 0.8f}, 9.0f,  "touches the lattice edge"},
        {{10.0f, 18.0f, 10.0f}, {0.0f, 1.0f, 0.0f}, 400.0f, "swallows the lattice"},
        {{10.0f, 18.0f, 10.0f}, {1.0f, 0.0f, 0.0f}, 20.0f, "large, partly saturating"},
        {{-30.0f, 18.0f, 10.0f}, {1.0f, 0.0f, 0.0f}, 3.0f, "wholly off-grid"},
    };
    for (const Case& k : cases) {
        voxel::DistanceField got = mixed_field(glm::ivec3(21, 27, 25));
        voxel::DistanceField want = got;
        const voxel::DistanceField before = got;
        const voxel::CellBox box = voxel::field_carve_oblate(got, k.c, k.n, k.r);
        reference_oblate(want, k.c, k.n, k.r);
        EXPECT_TRUE(got.dist == want.dist) << k.what << ": values differ from the reference";
        expect_same_box(box, changed_box(before, got));
        if (::testing::Test::HasFailure()) { ADD_FAILURE() << "case: " << k.what; return; }
    }
}

TEST(FieldBrushTight, CapsuleMatchesTheReferenceAndReportsOnlyChangedCells) {
    struct Case { glm::vec3 a; glm::vec3 b; float r; const char* what; };
    const Case cases[] = {
        {{4.0f, 10.0f, 8.0f}, {14.0f, 20.0f, 8.0f}, 2.0f,   "thin cut"},
        {{-5.0f, 5.0f, 5.0f}, {30.0f, 40.0f, 20.0f}, 6.0f,  "crosses the lattice"},
        {{8.0f, 18.0f, 9.0f}, {9.0f, 19.0f, 9.0f}, 300.0f,  "swallows the lattice"},
    };
    for (const Case& k : cases) {
        voxel::DistanceField got = mixed_field(glm::ivec3(21, 27, 25));
        voxel::DistanceField want = got;
        const voxel::DistanceField before = got;
        const voxel::CellBox box = voxel::field_carve_capsule(got, k.a, k.b, k.r);
        reference_capsule(want, k.a, k.b, k.r);
        EXPECT_TRUE(got.dist == want.dist) << k.what << ": values differ from the reference";
        expect_same_box(box, changed_box(before, got));
        if (::testing::Test::HasFailure()) { ADD_FAILURE() << "case: " << k.what; return; }
    }
}

TEST(FieldBrushTight, CarvingFullyCarvedMaterialChangesNothingAndReportsEmpty) {
    voxel::DistanceField f = solid_block(30);
    std::fill(f.dist.begin(), f.dist.end(), static_cast<std::int8_t>(127));
    const voxel::DistanceField before = f;
    EXPECT_TRUE(voxel::field_carve_oblate(f, glm::vec3(15.0f), kUp, 500.0f).empty())
        << "a lattice-swallowing carve on a fully carved field";
    EXPECT_TRUE(voxel::field_carve_oblate(f, glm::vec3(15.0f), kUp, 3.0f).empty())
        << "a small carve on a fully carved field";
    EXPECT_TRUE(voxel::field_carve_capsule(f, glm::vec3(5.0f), glm::vec3(25.0f), 4.0f).empty());
    EXPECT_TRUE(f.dist == before.dist);
}

TEST(FieldBrushTight, BoxStopsAtMaterialThatIsAlreadyFullyCarved) {
    voxel::DistanceField f = solid_block(40);
    for (int z = 0; z < 40; ++z) for (int y = 0; y < 40; ++y)
        for (int x = 20; x < 40; ++x) f.dist[f.index(x, y, z)] = 127;
    const voxel::DistanceField before = f;
    const voxel::CellBox box =
        voxel::field_carve_oblate(f, glm::vec3(20.0f, 20.0f, 20.0f), kUp, 6.0f);
    ASSERT_FALSE(box.empty());
    expect_same_box(box, changed_box(before, f));
    EXPECT_LT(box.hi.x, 20) << "the carved half cannot change, so it is not in the box";

    voxel::DistanceField g = before;
    const voxel::CellBox cbox = voxel::field_carve_capsule(
        g, glm::vec3(10.0f, 20.0f, 20.0f), glm::vec3(30.0f, 20.0f, 20.0f), 3.0f);
    ASSERT_FALSE(cbox.empty());
    expect_same_box(cbox, changed_box(before, g));
    EXPECT_LT(cbox.hi.x, 20);
}
