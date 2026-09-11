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
