// native/tests/renderer/structure_parts_cache_test.cc -- the structure-parts
// cache's DISK half (layered damage phase 4 §2.2): a cache file named by the
// hull NIF's content hash is read instead of detecting, and a missing or
// corrupt one is detected and rewritten. No GL.
#include <gtest/gtest.h>

#include <chrono>
#include <filesystem>
#include <fstream>
#include <string>
#include <thread>

#include <assets/mesh_fix.h>
#include <renderer/structure_parts_cache.h>
#include <voxel/structure_parts_io.h>

#include "support/content_root.h"

namespace fs = std::filesystem;

namespace {

fs::path fresh_dir(const std::string& name) {
    const fs::path d = fs::temp_directory_path() / "dauntless_sps_cache_test" / name;
    std::error_code ec;
    fs::remove_all(d, ec);
    fs::create_directories(d);
    return d;
}

void spit(const fs::path& p, const std::string& bytes) {
    std::ofstream s(p, std::ios::binary | std::ios::trunc);
    s.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
}

const voxel::StructureSegmentation* wait_for(const fs::path& source) {
    const auto t0 = std::chrono::steady_clock::now();
    const voxel::StructureSegmentation* seg = nullptr;
    while ((seg = renderer::structure_segmentation_for(source)) == nullptr &&
           std::chrono::steady_clock::now() - t0 < std::chrono::seconds(60))
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    return seg;
}

// Every test leaves the process-global root as it found it: unset.
struct RootGuard {
    ~RootGuard() { renderer::set_structure_parts_cache_root({}); }
};

}  // namespace

TEST(StructurePartsCache, NoRootMeansNoCacheFile) {
    const fs::path dir = fresh_dir("no_root");
    const fs::path src = dir / "hull.nif";
    spit(src, "bytes");
    renderer::set_structure_parts_cache_root({});
    EXPECT_TRUE(renderer::structure_parts_cache_file(src).empty());
}

TEST(StructurePartsCache, FileIsNamedByTheNifBytesAndVersion) {
    RootGuard guard;
    const fs::path dir = fresh_dir("naming");
    const fs::path src = dir / "hull.nif";
    spit(src, "some nif bytes");
    renderer::set_structure_parts_cache_root(dir / "root");
    EXPECT_EQ(renderer::structure_parts_cache_file(src),
              dir / "root" / (assets::fnv1a64_hex("some nif bytes") + "-v" +
                              std::to_string(voxel::kStructurePartsVersion) + ".sps"));
    // Same bytes under another name: the same file (a content hash, not a path).
    const fs::path copy = dir / "copy.nif";
    spit(copy, "some nif bytes");
    EXPECT_EQ(renderer::structure_parts_cache_file(copy),
              renderer::structure_parts_cache_file(src));
    // A scaled load or a glTF rock is never cached (lazy detection, as before).
    EXPECT_TRUE(renderer::structure_parts_cache_file(src.string() + "#s=2").empty());
    const fs::path rock = dir / "rock.glb";
    spit(rock, "glb");
    EXPECT_TRUE(renderer::structure_parts_cache_file(rock).empty());
    // An unreadable source has no hash, so no file.
    EXPECT_TRUE(renderer::structure_parts_cache_file(dir / "missing.nif").empty());
}

TEST(StructurePartsCache, CacheHitIsReadInsteadOfDetected) {
    RootGuard guard;
    const fs::path dir = fresh_dir("hit");
    // Not a NIF at all: only a cache hit can give this source parts.
    const fs::path src = dir / "not_a_nif.nif";
    spit(src, "not a nif");
    renderer::set_structure_parts_cache_root(dir / "root");

    voxel::StructureSegmentation want;
    want.vol.dims = {2, 2, 2};
    want.vol.occ.assign(8, 1);
    want.label.assign(8, 0);
    want.parts.resize(1);
    want.parts[0].kind = voxel::PartKind::Cylinder;
    want.parts[0].voxels = 8;
    want.parts[0].peak_depth = 4.5f;
    ASSERT_TRUE(voxel::write_structure_parts(renderer::structure_parts_cache_file(src), want));

    renderer::prefetch_structure_parts(src);
    const voxel::StructureSegmentation* got = wait_for(src);
    ASSERT_NE(got, nullptr);
    ASSERT_EQ(got->parts.size(), 1u);
    EXPECT_EQ(got->parts[0].kind, voxel::PartKind::Cylinder);
    EXPECT_EQ(got->parts[0].peak_depth, 4.5f);
    EXPECT_EQ(got->label, want.label);
}

TEST(StructurePartsCache, CorruptFileIsDetectedAndRewritten) {
    RootGuard guard;
    const fs::path nif = test_support::game_root() / "data/Models/Ships/Ambassador/Ambassador.nif";
    if (!fs::exists(nif)) GTEST_SKIP() << "no BC content at " << nif;
    const fs::path dir = fresh_dir("rebuild");
    // A private copy: a fresh source string, so no earlier test's entry answers.
    const fs::path src = dir / "Ambassador.nif";
    fs::copy_file(nif, src);
    renderer::set_structure_parts_cache_root(dir / "root");
    const fs::path file = renderer::structure_parts_cache_file(src);
    ASSERT_FALSE(file.empty());
    fs::create_directories(file.parent_path());
    spit(file, "SPS1 garbage that fails its checksum");

    renderer::prefetch_structure_parts(src);
    const voxel::StructureSegmentation* seg = wait_for(src);
    ASSERT_NE(seg, nullptr) << "detection never landed";
    ASSERT_FALSE(seg->parts.empty());

    const auto on_disk = voxel::read_structure_parts(file);
    ASSERT_TRUE(on_disk.has_value()) << "the corrupt file was not rewritten";
    EXPECT_EQ(on_disk->vol.dims, seg->vol.dims);
    EXPECT_EQ(on_disk->vol.occ, seg->vol.occ);
    EXPECT_EQ(on_disk->label, seg->label);
    ASSERT_EQ(on_disk->parts.size(), seg->parts.size());
    for (std::size_t i = 0; i < seg->parts.size(); ++i) {
        EXPECT_EQ(on_disk->parts[i].centre, seg->parts[i].centre) << i;
        EXPECT_EQ(on_disk->parts[i].voxels, seg->parts[i].voxels) << i;
    }
}
