// native/src/renderer/include/renderer/system_nebula_cache.h
#pragma once

#include "renderer/nebula_atmosphere.h"

#include <glm/glm.hpp>

#include <cstddef>
#include <cstdint>
#include <functional>
#include <future>
#include <memory>
#include <unordered_map>
#include <vector>

namespace renderer::atmosphere {

/// Everything SystemNebulaPass::set_profile uploads, built on the CPU.
struct BuiltProfile {
    std::vector<glm::vec2> radial;      // build_radial_texels
    std::vector<glm::vec3> tau;         // tau_from_table(table)
    std::vector<glm::vec3> inscatter;   // table.inscatter
};

/// FNV-1a 64 over the bytes of every field of (profile, look), including the
/// row counts. Equal inputs give equal keys; any changed row, colour or look
/// dial gives a new key (and so a new table).
std::uint64_t profile_key(const RadialProfile& profile, const LookParams& look);

/// The CPU half of set_profile: radial texels + far-field table as optical
/// depth and inscatter. Pure -- no GL, no globals -- so it is safe on a
/// worker thread. ~7 s in a Debug build.
BuiltProfile build_profile(const RadialProfile& profile, const LookParams& look);

/// Per-session cache of built tables keyed by profile_key, with an async
/// prebuild so a warp can build the destination's table during the tunnel
/// instead of stalling the arrival frame.
///
/// Main-thread only: every member function must be called from one thread.
/// Only the Builder runs on a worker (std::async), on its own copies of the
/// inputs. Entries are never evicted. Destroying the cache with a build
/// still pending blocks until that build finishes (std::async semantics).
class TableCache {
public:
    using Builder = std::function<BuiltProfile(const RadialProfile&, const LookParams&)>;

    explicit TableCache(Builder b = build_profile);

    /// Start building (profile, look) on a worker. No-op if it is already
    /// cached or already pending.
    void prebuild(const RadialProfile& profile, const LookParams& look);
    /// True if cached, or if its pending build has finished (which moves the
    /// result into the cache). Never blocks.
    bool ready(const RadialProfile& profile, const LookParams& look);
    /// The built table: a cache hit; else wait on its pending build; else
    /// build synchronously on the calling thread. Never null.
    std::shared_ptr<const BuiltProfile> get(const RadialProfile& profile,
                                            const LookParams& look);
    /// Number of CACHED (finished and collected) tables; pending builds are
    /// not counted.
    std::size_t size() const { return cache_.size(); }

private:
    std::shared_ptr<const BuiltProfile> collect(std::uint64_t key);

    Builder builder_;
    std::unordered_map<std::uint64_t, std::shared_ptr<const BuiltProfile>> cache_;
    std::unordered_map<std::uint64_t, std::shared_future<BuiltProfile>> pending_;
};

}  // namespace renderer::atmosphere
