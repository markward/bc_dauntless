// native/src/renderer/structure_parts_cache.cc -- see structure_parts_cache.h (SPIKE).
#include "renderer/structure_parts_cache.h"

#include <chrono>
#include <cstdio>
#include <fstream>
#include <future>
#include <iterator>
#include <memory>
#include <mutex>
#include <string>
#include <unordered_map>

#include <assets/hull_source.h>
#include <assets/mesh_fix.h>
#include <voxel/structure_parts_io.h>
#include <voxel/voxelize.h>

namespace renderer {
namespace {

struct Entry {
    std::future<voxel::StructureSegmentation> job;
    voxel::StructureSegmentation seg;
    bool ready = false;
};

std::mutex g_mu;
std::unordered_map<std::string, std::unique_ptr<Entry>> g_cache;
std::filesystem::path g_root;   // guarded by g_mu; empty = no disk I/O
StructureDetector g_detector;   // guarded by g_mu; empty = the real detector

std::filesystem::path cache_file_under(const std::filesystem::path& root,
                                       const std::filesystem::path& source) {
    if (root.empty() || source.empty()) return {};
    const assets::HullSource h = assets::split_hull_source(source);
    if (h.scale != 1.0f || assets::is_gltf_path(h.path)) return {};
    std::ifstream s(h.path, std::ios::binary);
    if (!s) return {};
    const std::string bytes(std::istreambuf_iterator<char>(s), {});
    if (s.bad()) return {};
    return root / (assets::fnv1a64_hex(bytes) + "-v" +
                   std::to_string(voxel::kStructurePartsVersion) + ".sps");
}

// The worker: the cache file when it reads clean, else detect (and write it).
voxel::StructureSegmentation load_or_detect(const std::filesystem::path& source,
                                            const std::filesystem::path& root,
                                            const StructureDetector& detect) {
    const std::filesystem::path file = cache_file_under(root, source);
    if (!file.empty()) {
        if (auto cached = voxel::read_structure_parts(file)) return std::move(*cached);
    }
    voxel::StructureSegmentation seg;
    try {
        if (detect) {
            seg = detect(source);
        } else {
            const auto tris = voxel::collect_hull_triangles_from_source(source);
            seg = voxel::detect_structure_parts(tris);
        }
    } catch (...) {
        std::fprintf(stderr, "[plating] structure detection failed for %s\n",
                     source.string().c_str());
        return {};
    }
    std::vector<float>().swap(seg.depth);  // unused by readers; never stored
    // A hull with NO parts is still an answer (cached, nparts 0); a detection
    // that produced no grid (no triangles: unreadable or empty hull) is not,
    // and is tried again next launch. A throw returned above.
    const glm::ivec3 d = seg.vol.dims;
    if (!file.empty() && d.x > 0 && d.y > 0 && d.z > 0)
        voxel::write_structure_parts(file, seg);
    return seg;
}

// Start `source`'s job if it has none. Caller holds g_mu.
Entry& start_locked(const std::filesystem::path& source) {
    auto& slot = g_cache[source.string()];
    if (!slot) {
        slot = std::make_unique<Entry>();
        slot->job = std::async(std::launch::async,
                               [source, root = g_root, detect = g_detector]() {
                                   return load_or_detect(source, root, detect);
                               });
    }
    return *slot;
}

}  // namespace

void set_structure_parts_cache_root(const std::filesystem::path& root) {
    std::lock_guard<std::mutex> lock(g_mu);
    g_root = root;
}

std::filesystem::path structure_parts_cache_file(const std::filesystem::path& source) {
    std::filesystem::path root;
    {
        std::lock_guard<std::mutex> lock(g_mu);
        root = g_root;
    }
    return cache_file_under(root, source);
}

void prefetch_structure_parts(const std::filesystem::path& source) {
    if (source.empty()) return;
    if (assets::is_gltf_path(assets::split_hull_source(source).path)) return;
    std::lock_guard<std::mutex> lock(g_mu);
    start_locked(source);
}

const voxel::StructureSegmentation* structure_segmentation_for(
    const std::filesystem::path& source) {
    if (source.empty()) return nullptr;
    std::lock_guard<std::mutex> lock(g_mu);
    Entry& slot = start_locked(source);
    if (!slot.ready) {
        if (slot.job.wait_for(std::chrono::seconds(0)) != std::future_status::ready)
            return nullptr;
        slot.seg = slot.job.get();
        slot.ready = true;
        std::fprintf(stderr, "[plating] %zu structure parts for %s\n",
                     slot.seg.parts.size(), source.string().c_str());
    }
    return &slot.seg;
}

const std::vector<voxel::StructurePart>* structure_parts_for(
    const std::filesystem::path& source) {
    const auto* seg = structure_segmentation_for(source);
    return seg ? &seg->parts : nullptr;
}

void set_structure_detector_for_test(StructureDetector detect) {
    std::lock_guard<std::mutex> lock(g_mu);
    g_detector = std::move(detect);
}

void set_structure_segmentation_for_test(const std::filesystem::path& source,
                                         voxel::StructureSegmentation seg) {
    std::lock_guard<std::mutex> lock(g_mu);
    auto slot = std::make_unique<Entry>();
    slot->seg = std::move(seg);
    slot->ready = true;
    g_cache[source.string()] = std::move(slot);
}

}  // namespace renderer
