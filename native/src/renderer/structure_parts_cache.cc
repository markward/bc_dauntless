// native/src/renderer/structure_parts_cache.cc -- see structure_parts_cache.h (SPIKE).
#include "renderer/structure_parts_cache.h"

#include <chrono>
#include <cstdio>
#include <future>
#include <memory>
#include <mutex>
#include <string>
#include <unordered_map>

#include <voxel/voxelize.h>

namespace renderer {
namespace {

struct Entry {
    std::future<std::vector<voxel::StructurePart>> job;
    std::vector<voxel::StructurePart> parts;
    bool ready = false;
};

std::mutex g_mu;
std::unordered_map<std::string, std::unique_ptr<Entry>> g_cache;

}  // namespace

const std::vector<voxel::StructurePart>* structure_parts_for(
    const std::filesystem::path& source) {
    if (source.empty()) return nullptr;
    std::lock_guard<std::mutex> lock(g_mu);
    auto& slot = g_cache[source.string()];
    if (!slot) {
        slot = std::make_unique<Entry>();
        slot->job = std::async(std::launch::async, [source]() {
            try {
                const auto tris = voxel::collect_hull_triangles_from_source(source);
                return voxel::detect_structure_parts(tris).parts;
            } catch (...) {
                std::fprintf(stderr, "[plating] structure detection failed for %s\n",
                             source.string().c_str());
                return std::vector<voxel::StructurePart>{};
            }
        });
        return nullptr;
    }
    if (!slot->ready) {
        if (slot->job.wait_for(std::chrono::seconds(0)) != std::future_status::ready)
            return nullptr;
        slot->parts = slot->job.get();
        slot->ready = true;
        std::fprintf(stderr, "[plating] %zu structure parts for %s\n",
                     slot->parts.size(), source.string().c_str());
    }
    return &slot->parts;
}

}  // namespace renderer
