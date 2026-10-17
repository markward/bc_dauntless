// native/src/renderer/system_nebula_cache.cc
#include "renderer/system_nebula_cache.h"

#include <chrono>
#include <utility>

namespace renderer::atmosphere {

namespace {

constexpr std::uint64_t kFnvOffset = 0xcbf29ce484222325ull;
constexpr std::uint64_t kFnvPrime = 0x100000001b3ull;

void fnv_bytes(std::uint64_t& h, const void* data, std::size_t n) {
    const auto* p = static_cast<const unsigned char*>(data);
    for (std::size_t i = 0; i < n; ++i) {
        h ^= p[i];
        h *= kFnvPrime;
    }
}

template <typename T>
void fnv_value(std::uint64_t& h, const T& v) {
    fnv_bytes(h, &v, sizeof(v));
}

void fnv_floats(std::uint64_t& h, const std::vector<float>& v) {
    fnv_value(h, static_cast<std::uint64_t>(v.size()));
    if (!v.empty()) fnv_bytes(h, v.data(), v.size() * sizeof(float));
}

void fnv_vec3(std::uint64_t& h, const glm::vec3& v) {
    fnv_value(h, v.x);
    fnv_value(h, v.y);
    fnv_value(h, v.z);
}

}  // namespace

std::uint64_t profile_key(const RadialProfile& profile, const LookParams& look) {
    std::uint64_t h = kFnvOffset;
    fnv_floats(h, profile.r);
    fnv_floats(h, profile.nebula);
    fnv_value(h, profile.k_sys);
    fnv_value(h, profile.star_radius);
    fnv_vec3(h, profile.cloud_rgb);
    fnv_vec3(h, profile.star_rgb);
    fnv_value(h, look.g);
    fnv_value(h, look.floor);
    fnv_value(h, look.scatter);
    fnv_value(h, look.far_gu);
    return h;
}

BuiltProfile build_profile(const RadialProfile& profile, const LookParams& look) {
    BuiltProfile out;
    out.radial = build_radial_texels(profile, look);
    Table table = build_table(profile, look);
    // Optical depth, never transmittance: see SystemNebulaPass / tau_from_table.
    out.tau = tau_from_table(table);
    out.inscatter = std::move(table.inscatter);
    return out;
}

TableCache::TableCache(Builder b) : builder_(std::move(b)) {}

void TableCache::prebuild(const RadialProfile& profile, const LookParams& look) {
    const std::uint64_t key = profile_key(profile, look);
    if (cache_.count(key) || pending_.count(key)) return;
    // The worker gets its own copies of the inputs and the builder; nothing
    // it touches is shared with the main thread.
    pending_.emplace(key, std::async(std::launch::async,
                                     [builder = builder_, profile, look]() {
                                         return builder(profile, look);
                                     }).share());
}

std::shared_ptr<const BuiltProfile> TableCache::collect(std::uint64_t key) {
    // Erase the pending entry before get(): a throwing build propagates and
    // leaves no stale future behind for the next call to trip over.
    std::shared_future<BuiltProfile> fut = std::move(pending_.at(key));
    pending_.erase(key);
    auto built = std::make_shared<const BuiltProfile>(fut.get());
    cache_.emplace(key, built);
    return built;
}

bool TableCache::ready(const RadialProfile& profile, const LookParams& look) {
    const std::uint64_t key = profile_key(profile, look);
    if (cache_.count(key)) return true;
    const auto it = pending_.find(key);
    if (it == pending_.end()) return false;
    if (it->second.wait_for(std::chrono::seconds(0)) != std::future_status::ready)
        return false;
    collect(key);
    return true;
}

std::shared_ptr<const BuiltProfile> TableCache::get(const RadialProfile& profile,
                                                    const LookParams& look) {
    const std::uint64_t key = profile_key(profile, look);
    if (const auto hit = cache_.find(key); hit != cache_.end()) return hit->second;
    if (pending_.count(key)) return collect(key);
    auto built = std::make_shared<const BuiltProfile>(builder_(profile, look));
    cache_.emplace(key, built);
    return built;
}

}  // namespace renderer::atmosphere
