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

#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

#if defined(__APPLE__) || defined(__linux__)
#include <csignal>
#include <sys/resource.h>
#define DHV_TEST_HAVE_RLIMIT_FSIZE 1
#endif

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

// Byte-exact mirror of the .dhv layout write_dhv produces, field for field,
// so a test can hand-craft a header with one field deliberately wrong while
// keeping every other field -- and the dist payload's actual byte count --
// consistent with what a correct reader would expect. Defaults match
// sample_field()/sample_meta() so an unmodified RawHeader round-trips
// exactly like the fixture above.
struct RawHeader {
    std::uint16_t format        = 1;
    std::uint16_t baker_version = voxel::kBakerVersion;
    std::uint32_t source_size   = 123456;
    std::int64_t  source_mtime  = 1757000000;
    std::int32_t  dims[3]       = {3, 4, 5};
    float         origin[3]     = {-1.0f, -2.0f, -3.0f};
    float         cell[3]       = {7.0f, 7.0f, 7.0f};
    float         authored_res  = 10.0f;
    float         quality       = 2.0f;
    float         scale         = 0.25f;
    std::uint32_t plen          = 23;
    std::string   path          = "Ships/Galaxy/Galaxy.nif";
    std::vector<std::int8_t> dist = [] {
        std::vector<std::int8_t> d(3 * 4 * 5);
        for (std::size_t i = 0; i < d.size(); ++i)
            d[i] = static_cast<std::int8_t>(static_cast<int>(i) - 30);
        return d;
    }();
};

void write_raw(const std::filesystem::path& p, const RawHeader& h) {
    std::ofstream s(p, std::ios::binary | std::ios::trunc);
    auto put = [&](const auto& v) {
        s.write(reinterpret_cast<const char*>(&v), sizeof(v));
    };
    s.write("DHV1", 4);
    put(h.format);
    put(h.baker_version);
    put(h.source_size);
    put(h.source_mtime);
    put(h.dims[0]); put(h.dims[1]); put(h.dims[2]);
    put(h.origin[0]); put(h.origin[1]); put(h.origin[2]);
    put(h.cell[0]); put(h.cell[1]); put(h.cell[2]);
    put(h.authored_res);
    put(h.quality);
    put(h.scale);
    put(h.plen);
    s.write(h.path.data(), static_cast<std::streamsize>(h.path.size()));
    s.write(reinterpret_cast<const char*>(h.dist.data()),
            static_cast<std::streamsize>(h.dist.size()));
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

TEST(Dhv, WrongFormatVersionIsRejected) {
    // Distinct from baker_version: `format` is the container's own binary
    // layout version, checked before anything baker-specific is even read.
    const auto p = tmp_path("dauntless_wrongformat.dhv");
    RawHeader h;
    h.format = 2;  // everything else valid
    write_raw(p, h);

    voxel::DistanceField out;
    voxel::HullVolumeMeta mo;
    EXPECT_FALSE(voxel::read_dhv(p, out, mo))
        << "a container format bump must invalidate files written by an "
           "older reader/writer pair, independent of baker_version";
    std::filesystem::remove(p);
}

TEST(Dhv, SourcePathLengthImplausibleIsRejected) {
    // plen is read straight off an untrusted file and used to size a string
    // allocation before any other validation. A plen far beyond anything a
    // real asset path could need must be rejected outright, not merely
    // "handled" by running out of bytes to read -- so this crafts a file
    // that actually HAS 4097 well-formed bytes following plen, proving the
    // cap itself is what rejects it, not a short read.
    const auto p = tmp_path("dauntless_longpath.dhv");
    RawHeader h;
    h.path = std::string(4097, 'X');  // one past the 4096 cap
    h.plen = static_cast<std::uint32_t>(h.path.size());
    write_raw(p, h);

    voxel::DistanceField out;
    voxel::HullVolumeMeta mo;
    EXPECT_FALSE(voxel::read_dhv(p, out, mo))
        << "an implausible source_path length must be rejected outright";
    std::filesystem::remove(p);
}

TEST(Dhv, NonPositiveDimsIsRejected) {
    // A zero (or negative) axis is nonsensical for a grid and would also
    // make index()/distance_at() misbehave for any caller that trusted it.
    const auto p = tmp_path("dauntless_zerodim.dhv");
    RawHeader h;
    h.dims[0] = 0;
    write_raw(p, h);

    voxel::DistanceField out;
    voxel::HullVolumeMeta mo;
    EXPECT_FALSE(voxel::read_dhv(p, out, mo))
        << "a non-positive dimension must be rejected before any allocation";
    std::filesystem::remove(p);
}

TEST(Dhv, OversizedCellCountIsRejected) {
    // Individually plausible-looking dims whose straightforward product
    // (no overflow trickery needed) is already past kMaxCells -- the
    // "just too big" case, distinct from OverflowingDimsProductIsRejected's
    // wraparound case below. 500^3 == 125,000,000, versus the 64 Mi
    // (67,108,864) cap -- deliberately kept small enough (~125 MB as an
    // int8 vector) that a mutation test can safely disable the cap and let
    // the allocation actually happen, unlike a dims-in-the-thousands case
    // that would attempt a multi-terabyte allocation.
    //
    // The dist payload below is sized to the FULL 125,000,000 bytes the
    // header claims, not left at RawHeader's small default. With a short
    // default payload, disabling the cap check leaves the read rejected
    // anyway -- just by the unrelated gcount() truncation check -- which
    // would prove nothing about the cap specifically. A full-length payload
    // isolates the cap as the only thing standing between this file and a
    // successful (wrongly so) read.
    const auto p = tmp_path("dauntless_oversized.dhv");
    RawHeader h;
    h.dims[0] = 500;
    h.dims[1] = 500;
    h.dims[2] = 500;
    h.dist.assign(500ull * 500 * 500, std::int8_t{0});
    write_raw(p, h);

    voxel::DistanceField out;
    voxel::HullVolumeMeta mo;
    EXPECT_FALSE(voxel::read_dhv(p, out, mo))
        << "a cell count far beyond kMaxCells must be rejected, not "
           "attempted as a huge allocation";
    std::filesystem::remove(p);
}

TEST(Dhv, OverflowingDimsProductIsRejected) {
    // Regression test for a self-review finding: computing
    // dims.x*dims.y*dims.z as a single uint64 expression before comparing
    // to kMaxCells lets three individually-positive int32 dims overflow the
    // product and wrap back under the cap. 4194304 == 2^22, and
    // (2^22)^3 == 2^66 == 4 * 2^64, so a naive single-expression product
    // wraps to exactly 0 -- comfortably <= kMaxCells, which a vulnerable
    // implementation would accept. The fix must reject this at the first
    // pairwise multiply (dims.x*dims.y alone is already ~1.76e13, far past
    // kMaxCells) before ever reaching that wraparound.
    const auto p = tmp_path("dauntless_dimsoverflow.dhv");
    RawHeader h;
    h.dims[0] = 4194304;
    h.dims[1] = 4194304;
    h.dims[2] = 4194304;
    h.dist.clear();  // must never be reached: rejection happens before dist

    write_raw(p, h);

    voxel::DistanceField out;
    voxel::HullVolumeMeta mo;
    EXPECT_FALSE(voxel::read_dhv(p, out, mo))
        << "dims individually positive but overflowing as a single uint64 "
           "product must still be rejected, not accepted via wraparound";
    std::filesystem::remove(p);
}

#if defined(DHV_TEST_HAVE_RLIMIT_FSIZE)
TEST(Dhv, FailedWriteLeavesNoTempFile) {
    // Regression test for a self-review finding: write_dhv used to leave
    // its ".tmp" sibling behind when the write failed partway through.
    // Forces a genuine mid-write I/O failure (not an open failure -- an
    // open failure would never create the .tmp in the first place, so it
    // wouldn't exercise the cleanup path at all) via RLIMIT_FSIZE: cap the
    // process's max file size below what write_dhv needs, so the write
    // fails with EFBIG. This also exercises the companion fix for reading
    // write_ok before the stream is actually flushed: our whole payload
    // (~155 bytes) fits inside the filebuf's internal buffer, so the
    // individual s.write() calls above can't observe the failure -- only
    // the explicit close()/flush can, and write_ok must be decided after
    // that, not before.
    const auto p   = tmp_path("dauntless_writefail.dhv");
    const auto tmp = std::filesystem::path(p.string() + ".tmp");
    std::filesystem::remove(p);
    std::filesystem::remove(tmp);

    struct rlimit orig_lim {};
    ASSERT_EQ(getrlimit(RLIMIT_FSIZE, &orig_lim), 0);
    struct sigaction orig_action {};
    ASSERT_EQ(sigaction(SIGXFSZ, nullptr, &orig_action), 0);

    // SIGXFSZ ignored: exceeding RLIMIT_FSIZE then makes the write() call
    // fail and return EFBIG instead of killing the process outright.
    struct sigaction ign {};
    ign.sa_handler = SIG_IGN;
    sigemptyset(&ign.sa_mask);
    const bool signal_set = (sigaction(SIGXFSZ, &ign, nullptr) == 0);

    struct rlimit small_lim = orig_lim;
    small_lim.rlim_cur = 32;  // well under the ~155-byte payload
    const bool limit_set = signal_set && (setrlimit(RLIMIT_FSIZE, &small_lim) == 0);

    bool result = true;
    if (limit_set)
        result = voxel::write_dhv(p, sample_field(), sample_meta());

    // Restore process-global state BEFORE any assertion, so a failing
    // EXPECT can't skip cleanup and wedge later tests in this binary.
    setrlimit(RLIMIT_FSIZE, &orig_lim);
    sigaction(SIGXFSZ, &orig_action, nullptr);

    ASSERT_TRUE(limit_set) << "setrlimit/sigaction unavailable here";
    EXPECT_FALSE(result) << "the capped file size must make the write fail";
    EXPECT_FALSE(std::filesystem::exists(tmp))
        << "a failed write must not leave the .tmp sibling behind";
    EXPECT_FALSE(std::filesystem::exists(p))
        << "a failed write must not leave a (short) file at the real path";

    std::filesystem::remove(p);
    std::filesystem::remove(tmp);
}
#endif  // DHV_TEST_HAVE_RLIMIT_FSIZE
