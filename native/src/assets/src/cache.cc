#include <assets/cache.h>
#include <assets/path_resolver.h>

#include "model_build.h"

#include <nif/file.h>

#include <unordered_map>

namespace fs = std::filesystem;

namespace assets {

struct AssetCache::Impl {
    Config config;
    PathResolver resolver;

    struct Entry {
        std::weak_ptr<const Model>   live;
        std::shared_ptr<const Model> pinned;
        std::vector<fs::path>        search_paths;
    };
    std::unordered_map<std::string, Entry> entries;
};

AssetCache::AssetCache() : AssetCache(Config{}) {}

AssetCache::AssetCache(Config cfg) : impl_(std::make_unique<Impl>()) {
    impl_->config = std::move(cfg);
}

AssetCache::~AssetCache() {
    // GL handles in entries are released here. Caller must ensure a current
    // GL context. (Documented in the header.)
    impl_->entries.clear();
}

ModelHandle AssetCache::load(const fs::path& nif_path,
                             const fs::path& search_path) {
    std::vector<fs::path> paths{search_path};
    return load(nif_path, paths);
}

ModelHandle AssetCache::load(const fs::path& nif_path,
                             const std::vector<fs::path>& search_paths) {
    auto canon = fs::weakly_canonical(nif_path).string();
    auto it = impl_->entries.find(canon);
    if (it != impl_->entries.end()) {
        if (auto live = it->second.live.lock()) {
            if (it->second.search_paths != search_paths) {
                throw AssetError(
                    "asset already loaded with different texture_search_paths: "
                    + canon);
            }
            return live;
        }
    }

    auto file = nif::load(nif_path);

    detail::ModelBuildContext ctx;
    ctx.resolver              = &impl_->resolver;
    ctx.texture_search_paths  = search_paths;
    ctx.texture_uploader      = impl_->config.texture_uploader;
    ctx.mesh_uploader         = impl_->config.mesh_uploader;
    ctx.keep_cpu_data         = impl_->config.keep_cpu_data;

    auto model = std::make_shared<const Model>(detail::build_model(file, ctx));

    Impl::Entry entry;
    entry.live         = model;
    entry.pinned       = model;
    entry.search_paths = search_paths;
    impl_->entries[canon] = std::move(entry);
    return model;
}

void AssetCache::evict(const fs::path& nif_path) {
    auto canon = fs::weakly_canonical(nif_path).string();
    auto it = impl_->entries.find(canon);
    if (it == impl_->entries.end()) return;
    it->second.pinned.reset();
}

void AssetCache::evict_unused() {
    for (auto& [_, entry] : impl_->entries) {
        if (entry.pinned && entry.pinned.use_count() == 1) entry.pinned.reset();
    }
}

}  // namespace assets
