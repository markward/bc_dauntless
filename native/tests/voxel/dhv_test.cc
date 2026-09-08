// native/tests/voxel/dhv_test.cc
//
// The .dhv container. A cache file is untrusted input: it may be truncated by a
// crash mid-write, left behind by an older baker, or belong to a different
// hull. Every one of those must be REJECTED and rebaked, never half-read --
// a silently wrong hull volume is exactly the class of bug this subsystem
// exists to end.
#include <gtest/gtest.h>

#include <voxel/dhv.h>
#include <voxel/distance_field.h>

#include <cstdio>
#include <filesystem>
#include <fstream>
#include <vector>

namespace {

std::filesystem::path tmp_path(const char* name) {
    return std::filesystem::temp_directory_path() / name;
}

voxel::DistanceField sample_field() {
    voxel::DistanceField f;
    f.dims   = glm::ivec3(3, 4, 5);
    f.origin = glm::vec3(-1.0f, -2.0f, -3.0f);
    f.cell   = glm::vec3(7.0f, 7.0f, 7.0f);
    f.scale  = 0.25f;
    f.dist.resize(3 * 4 * 5);
    for (std::size_t i = 0; i < f.dist.size(); ++i)
        f.dist[i] = static_cast<std::int8_t>(static_cast<int>(i) - 30);
    return f;
}

voxel::HullVolumeMeta sample_meta() {
    voxel::HullVolumeMeta m;
    m.baker_version = voxel::kBakerVersion;
    m.source_size   = 123456;
    m.source_mtime  = 1757000000;
    m.authored_res  = 10.0f;
    m.quality       = 2.0f;
    m.source_path   = "Ships/Galaxy/Galaxy.nif";
    return m;
}

}  // namespace

TEST(Dhv, RoundTripPreservesFieldAndMeta) {
    const auto p = tmp_path("dauntless_roundtrip.dhv");
    const voxel::DistanceField in = sample_field();
    const voxel::HullVolumeMeta mi = sample_meta();
    ASSERT_TRUE(voxel::write_dhv(p, in, mi));

    voxel::DistanceField out;
    voxel::HullVolumeMeta mo;
    ASSERT_TRUE(voxel::read_dhv(p, out, mo));

    EXPECT_EQ(out.dims, in.dims);
    EXPECT_EQ(out.origin, in.origin);
    EXPECT_EQ(out.cell, in.cell);
    EXPECT_FLOAT_EQ(out.scale, in.scale);
    EXPECT_EQ(out.dist, in.dist);

    EXPECT_EQ(mo.baker_version, mi.baker_version);
    EXPECT_EQ(mo.source_size, mi.source_size);
    EXPECT_EQ(mo.source_mtime, mi.source_mtime);
    EXPECT_FLOAT_EQ(mo.authored_res, mi.authored_res);
    EXPECT_FLOAT_EQ(mo.quality, mi.quality);
    EXPECT_EQ(mo.source_path, mi.source_path);

    std::filesystem::remove(p);
}

TEST(Dhv, NegativeDistancesSurviveTheRoundTrip) {
    // int8 payload: a sign bug here inverts inside and outside, which would
    // read as "the whole ship is a hole".
    const auto p = tmp_path("dauntless_signs.dhv");
    voxel::DistanceField in = sample_field();
    in.dist[0] = -127;
    in.dist[1] = 127;
    in.dist[2] = 0;
    ASSERT_TRUE(voxel::write_dhv(p, in, sample_meta()));

    voxel::DistanceField out;
    voxel::HullVolumeMeta mo;
    ASSERT_TRUE(voxel::read_dhv(p, out, mo));
    EXPECT_EQ(out.dist[0], -127);
    EXPECT_EQ(out.dist[1], 127);
    EXPECT_EQ(out.dist[2], 0);

    std::filesystem::remove(p);
}

TEST(Dhv, MissingFileIsRejected) {
    voxel::DistanceField out;
    voxel::HullVolumeMeta mo;
    EXPECT_FALSE(voxel::read_dhv(tmp_path("dauntless_absent.dhv"), out, mo));
}

TEST(Dhv, WrongMagicIsRejected) {
    const auto p = tmp_path("dauntless_badmagic.dhv");
    ASSERT_TRUE(voxel::write_dhv(p, sample_field(), sample_meta()));
    {
        std::fstream s(p, std::ios::in | std::ios::out | std::ios::binary);
        s.seekp(0);
        s.write("XXXX", 4);
    }
    voxel::DistanceField out;
    voxel::HullVolumeMeta mo;
    EXPECT_FALSE(voxel::read_dhv(p, out, mo));
    std::filesystem::remove(p);
}

TEST(Dhv, TruncatedPayloadIsRejected) {
    const auto p = tmp_path("dauntless_short.dhv");
    ASSERT_TRUE(voxel::write_dhv(p, sample_field(), sample_meta()));
    const auto full = std::filesystem::file_size(p);
    std::filesystem::resize_file(p, full - 10);

    voxel::DistanceField out;
    voxel::HullVolumeMeta mo;
    EXPECT_FALSE(voxel::read_dhv(p, out, mo))
        << "a crash mid-write must not yield a half-read volume";
    std::filesystem::remove(p);
}

TEST(Dhv, OlderBakerVersionIsRejected) {
    const auto p = tmp_path("dauntless_oldbaker.dhv");
    voxel::HullVolumeMeta m = sample_meta();
    m.baker_version = static_cast<std::uint16_t>(voxel::kBakerVersion - 1);
    ASSERT_TRUE(voxel::write_dhv(p, sample_field(), m));

    voxel::DistanceField out;
    voxel::HullVolumeMeta mo;
    EXPECT_FALSE(voxel::read_dhv(p, out, mo))
        << "bumping kBakerVersion must invalidate every stale cache entry";
    std::filesystem::remove(p);
}
