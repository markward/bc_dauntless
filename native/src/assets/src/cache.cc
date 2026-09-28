#include <assets/cache.h>
#include <assets/mesh_fix.h>
#include <assets/path_resolver.h>

#include "model_build.h"

#include <nif/file.h>

#include <fstream>
#include <iostream>
#include <optional>
#include <sstream>
#include <unordered_map>
#include <unordered_set>

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
    return load(nif_path, search_paths, {});
}

namespace {

// Stable, collision-resistant suffix appended to the NIF-path cache key so a
// distinct registry yields a distinct entry while same-registry hulls share.
// An empty list yields an empty suffix => byte-identical key to the legacy
// no-replacement path.
std::string replacements_key(
    const std::vector<TextureReplacement>& reps) {
    if (reps.empty()) return {};
    std::string key = "|rep:";
    for (const auto& r : reps) {
        key += r.old_substring;
        key += '=';
        key += r.new_texture;
        key += ';';
    }
    return key;
}

std::string read_file_bytes(const fs::path& path) {
    std::ifstream in(path, std::ios::binary);
    std::ostringstream ss;
    ss << in.rdbuf();
    return ss.str();
}

// Looks up a mesh fix for `nif_path` (already-read `nif_bytes`) under `dir`.
// Returns the parsed fix and its hash on success. On a parse failure, warns
// once per hash to stderr and returns nullopt (caller loads unpatched).
std::optional<std::pair<MeshFix, std::string>> find_mesh_fix(
    const fs::path& dir, const fs::path& nif_path, const std::string& nif_bytes) {
    if (dir.empty()) return std::nullopt;
    auto hash = fnv1a64_hex(nif_bytes);
    auto fix_path = dir / (hash + ".json");
    std::error_code ec;
    if (!fs::exists(fix_path, ec)) return std::nullopt;

    static std::unordered_set<std::string> warned;
    auto text = read_file_bytes(fix_path);
    std::string error;
    auto fix = parse_mesh_fix(text, &error);
    if (!fix) {
        if (warned.insert(hash).second) {
            std::cerr << "mesh fix " << hash << ".json for " << nif_path.string()
                       << " refused: " << error << "; loading unpatched\n";
        }
        return std::nullopt;
    }
    return std::make_pair(std::move(*fix), std::move(hash));
}

}  // namespace

ModelHandle AssetCache::load(
    const fs::path& nif_path,
    const std::vector<fs::path>& search_paths,
    const std::vector<TextureReplacement>& texture_replacements) {
    // Decided BEFORE the cache lookup, so a cache hit never re-reads or
    // re-parses the NIF: a fix that parses changes the key, so a fixed and
    // an unfixed load of the same nif_path land in different entries.
    std::optional<MeshFix> fix;
    std::string fix_key;
    if (impl_->config.mesh_fix_dir) {
        auto dir = impl_->config.mesh_fix_dir();
        if (!dir.empty()) {
            auto nif_bytes = read_file_bytes(nif_path);
            if (auto found = find_mesh_fix(dir, nif_path, nif_bytes)) {
                fix_key = "|fix:" + found->second;
                fix     = std::move(found->first);
            }
        }
    }

    auto canon = fs::weakly_canonical(nif_path).string()
                 + replacements_key(texture_replacements) + fix_key;
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

    if (fix) {
        static std::unordered_set<std::string> apply_warned;
        auto reason = apply_mesh_fix(file, *fix);
        if (!reason.empty()) {
            // fix_key is "|fix:<hash>"; strip the prefix for the message.
            auto hash = fix_key.substr(5);
            if (apply_warned.insert(hash).second) {
                std::cerr << "mesh fix " << hash << ".json for " << nif_path.string()
                           << " refused: " << reason << "; loading unpatched\n";
            }
        }
    }

    detail::ModelBuildContext ctx;
    ctx.resolver              = &impl_->resolver;
    ctx.texture_search_paths  = search_paths;
    ctx.texture_uploader      = impl_->config.texture_uploader;
    ctx.mesh_uploader         = impl_->config.mesh_uploader;
    ctx.keep_cpu_data         = impl_->config.keep_cpu_data;
    ctx.texture_replacements  = texture_replacements;

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
