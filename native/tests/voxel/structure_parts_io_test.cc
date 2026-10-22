// native/tests/voxel/structure_parts_io_test.cc -- the `.sps` structure-parts
// disk cache (layered damage phase 4 §2.2).
#include <voxel/structure_parts_io.h>

#include <gtest/gtest.h>

#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <string>
#include <thread>
#include <vector>

namespace fs = std::filesystem;

namespace {

fs::path scratch(const std::string& name) {
    const fs::path dir = fs::temp_directory_path() / "dauntless_sps_test";
    fs::create_directories(dir);
    const fs::path p = dir / name;
    std::error_code ec;
    fs::remove(p, ec);
    return p;
}

// A hand-built segmentation exercising every encoding case: empty voxels,
// labelled solid voxels, and a SOLID voxel no part claimed (label -1).
voxel::StructureSegmentation sample() {
    voxel::StructureSegmentation s;
    s.vol.dims = {4, 3, 2};
    s.vol.origin = {-1.5f, 2.25f, -0.125f};
    s.vol.cell = {0.5f, 0.75f, 1.25f};
    const std::size_t n = 24;
    s.vol.occ.assign(n, 0);
    s.label.assign(n, -1);
    for (std::size_t i = 3; i < 11; ++i) { s.vol.occ[i] = 1; s.label[i] = 0; }
    for (std::size_t i = 11; i < 20; ++i) { s.vol.occ[i] = 1; s.label[i] = 1; }
    s.vol.occ[21] = 1;                                   // solid, no part
    voxel::StructurePart a;
    a.kind = voxel::PartKind::Disc;
    a.centre = {0.1f, -2.5f, 3.75f};
    a.axis[0] = {0.0f, 0.0f, 1.0f};
    a.axis[1] = {0.6f, 0.8f, 0.0f};
    a.axis[2] = {-0.8f, 0.6f, 0.0f};
    a.half_extent = {0.3f, 4.5f, 4.25f};
    a.voxels = 8;
    a.peak_depth = 1.875f;
    a.spread = {2.5f, 2.25f, 0.125f};
    voxel::StructurePart b;
    b.kind = voxel::PartKind::Cylinder;
    b.centre = {-7.0f, 1e-3f, 12345.5f};
    b.half_extent = {9.0f, 1.0f, 1.5f};
    b.voxels = 9;
    b.peak_depth = 0.5f;
    b.spread = {3.0f, 0.75f, 0.7f};
    s.parts = {a, b};
    return s;
}

void expect_equal(const voxel::StructureSegmentation& got,
                  const voxel::StructureSegmentation& want) {
    EXPECT_EQ(got.vol.dims, want.vol.dims);
    EXPECT_EQ(got.vol.origin, want.vol.origin);
    EXPECT_EQ(got.vol.cell, want.vol.cell);
    EXPECT_EQ(got.vol.occ, want.vol.occ);
    EXPECT_EQ(got.label, want.label);
    EXPECT_TRUE(got.depth.empty());
    ASSERT_EQ(got.parts.size(), want.parts.size());
    for (std::size_t i = 0; i < want.parts.size(); ++i) {
        const voxel::StructurePart& g = got.parts[i];
        const voxel::StructurePart& w = want.parts[i];
        EXPECT_EQ(g.kind, w.kind) << i;
        EXPECT_EQ(g.centre, w.centre) << i;
        for (int k = 0; k < 3; ++k) EXPECT_EQ(g.axis[k], w.axis[k]) << i << " axis " << k;
        EXPECT_EQ(g.half_extent, w.half_extent) << i;
        EXPECT_EQ(g.voxels, w.voxels) << i;
        EXPECT_EQ(g.peak_depth, w.peak_depth) << i;
        EXPECT_EQ(g.spread, w.spread) << i;
    }
}

std::string slurp(const fs::path& p) {
    std::ifstream s(p, std::ios::binary);
    return std::string(std::istreambuf_iterator<char>(s), {});
}

void spit(const fs::path& p, const std::string& bytes) {
    std::ofstream s(p, std::ios::binary | std::ios::trunc);
    s.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
}

// Re-seal a doctored payload with a VALID trailing FNV-1a 64, so a test can
// prove a rejection is for its own reason, not the checksum.
std::string reseal(std::string bytes) {
    bytes.resize(bytes.size() - 8);
    std::uint64_t h = 14695981039346656037ull;
    for (unsigned char c : bytes) { h ^= c; h *= 1099511628211ull; }
    for (int i = 0; i < 8; ++i) bytes.push_back(static_cast<char>((h >> (8 * i)) & 0xff));
    return bytes;
}

}  // namespace

TEST(StructurePartsIo, RoundTripsASegmentation) {
    const auto want = sample();
    const fs::path p = scratch("round_trip.sps");
    ASSERT_TRUE(voxel::write_structure_parts(p, want));
    EXPECT_FALSE(fs::exists(fs::path(p.string() + ".tmp"))) << "temp file left behind";
    const auto got = voxel::read_structure_parts(p);
    ASSERT_TRUE(got.has_value());
    expect_equal(*got, want);
}

TEST(StructurePartsIo, RoundTripsADetectedSegmentation) {
    // A real detector output, not just the hand-built sample: a 6 x 2 x 2 bar.
    std::vector<voxel::Tri> tris;
    const glm::vec3 lo(-3.0f, -1.0f, -1.0f), hi(3.0f, 1.0f, 1.0f);
    const glm::vec3 c[8] = {
        {lo.x, lo.y, lo.z}, {hi.x, lo.y, lo.z}, {hi.x, hi.y, lo.z}, {lo.x, hi.y, lo.z},
        {lo.x, lo.y, hi.z}, {hi.x, lo.y, hi.z}, {hi.x, hi.y, hi.z}, {lo.x, hi.y, hi.z}};
    const int f[12][3] = {{0, 2, 1}, {0, 3, 2}, {4, 5, 6}, {4, 6, 7}, {0, 1, 5}, {0, 5, 4},
                          {2, 3, 7}, {2, 7, 6}, {1, 2, 6}, {1, 6, 5}, {0, 4, 7}, {0, 7, 3}};
    for (const auto& t : f) tris.push_back({c[t[0]], c[t[1]], c[t[2]]});
    voxel::StructureParams params;
    params.long_axis_cells = 32;
    auto want = voxel::detect_structure_parts(tris, params);
    ASSERT_FALSE(want.parts.empty());
    want.depth.clear();
    const fs::path p = scratch("detected.sps");
    ASSERT_TRUE(voxel::write_structure_parts(p, want));
    const auto got = voxel::read_structure_parts(p);
    ASSERT_TRUE(got.has_value());
    expect_equal(*got, want);
}

TEST(StructurePartsIo, CorruptCacheFileIsRebuilt) {
    // "Rebuilt" at this layer = read refuses it; the cache then detects and
    // rewrites (renderer::structure_segmentation_for).
    const fs::path p = scratch("corrupt.sps");
    ASSERT_TRUE(voxel::write_structure_parts(p, sample()));
    const std::string good = slurp(p);
    ASSERT_GT(good.size(), 16u);
    ASSERT_TRUE(voxel::read_structure_parts(p).has_value()) << "baseline must read";

    std::string flipped = good;
    flipped[good.size() / 2] ^= 0x5a;
    spit(p, flipped);
    EXPECT_FALSE(voxel::read_structure_parts(p).has_value()) << "bad checksum";

    spit(p, good.substr(0, good.size() - 3));
    EXPECT_FALSE(voxel::read_structure_parts(p).has_value()) << "truncated";

    spit(p, good.substr(0, 6));
    EXPECT_FALSE(voxel::read_structure_parts(p).has_value()) << "truncated header";

    std::string version = good;
    version[4] = static_cast<char>(voxel::kStructurePartsVersion + 1);  // u32 LE at 4
    spit(p, reseal(version));
    EXPECT_FALSE(voxel::read_structure_parts(p).has_value()) << "wrong version";

    std::string magic = good;
    magic[3] = '9';
    spit(p, reseal(magic));
    EXPECT_FALSE(voxel::read_structure_parts(p).has_value()) << "bad magic";

    spit(p, reseal(good + std::string(8, '\0')));
    EXPECT_FALSE(voxel::read_structure_parts(p).has_value()) << "trailing bytes";

    fs::remove(p);
    EXPECT_FALSE(voxel::read_structure_parts(p).has_value()) << "missing file";
}

TEST(StructurePartsIo, LabelNamingNoPartIsRejected) {
    auto s = sample();
    s.parts.pop_back();   // voxels labelled 1 now name no part
    const fs::path p = scratch("dangling_label.sps");
    ASSERT_TRUE(voxel::write_structure_parts(p, s));
    EXPECT_FALSE(voxel::read_structure_parts(p).has_value());
}

TEST(StructurePartsIo, WriteFailureIsReportedOnce) {
    // A regular file where the cache directory should be: every write fails.
    const fs::path blocker = scratch("blocker");
    spit(blocker, "not a directory");
    const fs::path p = blocker / "hull-v1.sps";
    const std::string line = "[dauntless] could not write " + p.string() + ": ";

    testing::internal::CaptureStderr();
    const bool first = voxel::write_structure_parts(p, sample());
    const bool second = voxel::write_structure_parts(p, sample());
    const std::string err = testing::internal::GetCapturedStderr();

    EXPECT_FALSE(first);
    EXPECT_FALSE(second);
    const auto at = err.find(line);
    ASSERT_NE(at, std::string::npos) << err;
    EXPECT_EQ(err.find(line, at + 1), std::string::npos) << "reported twice:\n" << err;
    // The reason follows the path: never an empty "why".
    const auto eol = err.find('\n', at);
    EXPECT_GT(eol, at + line.size()) << err;
}

TEST(StructurePartsIo, EmptySegmentationIsNotWrittenOrReported) {
    const fs::path p = scratch("empty.sps");
    testing::internal::CaptureStderr();
    EXPECT_FALSE(voxel::write_structure_parts(p, voxel::StructureSegmentation{}));
    EXPECT_EQ(testing::internal::GetCapturedStderr(), "");
    EXPECT_FALSE(fs::exists(p));
}

// Two writers of one path (same-bytes NIF copies hash to one cache file, and
// two hull loads can race) must never share a temp file: a shared
// `<path>.tmp` made one writer's rename fail with a spurious "could not
// write" line, which also burned the once-per-path report. A temp name
// another writer already holds -- here a DIRECTORY squatting `<path>.tmp` --
// cannot block a write.
TEST(StructurePartsIo, AnotherWritersTempFileNeverBlocksAWrite) {
    const fs::path p = scratch("squatted.sps");
    fs::path squat = p;
    squat += ".tmp";
    std::error_code ec;
    fs::remove_all(squat, ec);
    fs::create_directories(squat);
    testing::internal::CaptureStderr();
    const bool ok = voxel::write_structure_parts(p, sample());
    const std::string err = testing::internal::GetCapturedStderr();
    fs::remove_all(squat, ec);
    EXPECT_TRUE(ok);
    EXPECT_EQ(err, "");
    const auto back = voxel::read_structure_parts(p);
    ASSERT_TRUE(back.has_value());
    expect_equal(*back, sample());
}

TEST(StructurePartsIo, ConcurrentWritesOfOnePathBothSucceedSilently) {
    const fs::path dir = fs::temp_directory_path() / "dauntless_sps_test" / "concurrent";
    std::error_code ec;
    fs::remove_all(dir, ec);
    fs::create_directories(dir);
    const auto seg = sample();
    int failures = 0;
    testing::internal::CaptureStderr();
    for (int round = 0; round < 200; ++round) {
        // A fresh path per round: the once-per-path report cannot hide a race.
        const fs::path p = dir / ("hull-" + std::to_string(round) + ".sps");
        bool a = false, b = false;
        std::thread ta([&] { a = voxel::write_structure_parts(p, seg); });
        std::thread tb([&] { b = voxel::write_structure_parts(p, seg); });
        ta.join();
        tb.join();
        failures += (a ? 0 : 1) + (b ? 0 : 1);
    }
    const std::string err = testing::internal::GetCapturedStderr();
    EXPECT_EQ(failures, 0);
    EXPECT_EQ(err, "");
    int files = 0;
    for (const auto& e : fs::directory_iterator(dir)) {
        ++files;
        EXPECT_EQ(e.path().extension(), ".sps") << "left behind: " << e.path();
    }
    EXPECT_EQ(files, 200);
    fs::remove_all(dir, ec);
}
