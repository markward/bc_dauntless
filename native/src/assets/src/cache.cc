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

    // Memoizes whether a given (mesh_fix_dir, fix hash) pair's fix actually
    // APPLIES against the real nif content it was matched to -- not just
    // that a fix file matched and parsed. Keyed by "<dir>|fix:<hash>" (the
    // same fix_key computed below, prefixed with the directory so two
    // directories that happen to hold a same-named-but-different fix file
    // don't share a memo entry). Populated lazily: the first load that
    // needs the answer pays for one real nif::load + apply_mesh_fix trial;
    // every later load of the same (dir, fix) reads the cached bool instead
    // of repeating it, which is what keeps a cache HIT free of any
    // additional parsing.
    std::unordered_map<std::string, bool> fix_apply_ok;
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

// Same reasoning as replacements_key: folds each decal's shape + resolved
// mask path into the cache key so distinct registries (distinct mask paths)
// on the same NIF land in distinct entries, while an empty list is
// byte-identical to the no-decal key.
std::string decals_key(const std::vector<DecalRequest>& decals) {
    if (decals.empty()) return {};
    std::string key = "|decals:";
    for (const auto& d : decals) {
        key += d.shape;
        key += '=';
        key += d.mask.string();
        key += ';';
    }
    return key;
}

// The "no decals requested / no decals attached" sentinel `effective_decals`
// binds to as a const&, so ungating a load never copies its (usually empty)
// vector.
const std::vector<DecalRequest> kNoDecals;

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
    return load(nif_path, search_paths, texture_replacements, {});
}

ModelHandle AssetCache::load(
    const fs::path& nif_path,
    const std::vector<fs::path>& search_paths,
    const std::vector<TextureReplacement>& texture_replacements,
    const std::vector<DecalRequest>& decals) {
    // Decided BEFORE the cache lookup, so the fix (if any) can change the
    // cache key: a fixed and an unfixed load of the same nif_path land in
    // different entries. This does NOT avoid re-reading the NIF on a cache
    // hit -- read_file_bytes(nif_path) below runs on every call, hit or
    // miss, to compute the fix lookup hash; a miss then reads it a second
    // time via nif::load. In practice this is bounded by
    // host_bindings.cc's g_loaded_models dedupe, which calls in here at
    // most once per (path, registry) variant.
    std::optional<MeshFix> fix;
    std::string fix_key;
    fs::path fix_dir;
    if (impl_->config.mesh_fix_dir) {
        fix_dir = impl_->config.mesh_fix_dir();
        if (!fix_dir.empty()) {
            auto nif_bytes = read_file_bytes(nif_path);
            if (auto found = find_mesh_fix(fix_dir, nif_path, nif_bytes)) {
                fix_key = "|fix:" + found->second;
                fix     = std::move(found->first);
            }
        }
    }

    // Decals attach ONLY on top of a mesh the fix actually patched
    // (Controller Ruling G item 1): a refit copy with a mismatched hash, a
    // missing mesh_fix_dir, or a fix that parsed but was refused all still
    // carry BC's own "ID" patch geometry, so a decal on top would paint the
    // name twice. Whether the matched-and-parsed `fix` (if any) actually
    // applies is memoized per (dir, fix hash) in impl_->fix_apply_ok so a
    // cache HIT never pays for a trial nif::load -- only the first load of
    // a given fix does, and that trial's already-patched (or refused, still
    // unpatched) File is reused below instead of loading nif_path twice.
    bool fix_applied = false;
    std::optional<nif::File> preloaded;
    if (fix) {
        const std::string apply_key = fix_dir.string() + fix_key;
        auto memo = impl_->fix_apply_ok.find(apply_key);
        if (memo != impl_->fix_apply_ok.end()) {
            fix_applied = memo->second;
        } else {
            auto trial = nif::load(nif_path);
            auto reason = apply_mesh_fix(trial, *fix);
            fix_applied = reason.empty();
            impl_->fix_apply_ok[apply_key] = fix_applied;
            if (!fix_applied) {
                static std::unordered_set<std::string> apply_warned;
                // fix_key is "|fix:<hash>"; strip the prefix for the message.
                auto hash = fix_key.substr(5);
                if (apply_warned.insert(hash).second) {
                    std::cerr << "mesh fix " << hash << ".json for " << nif_path.string()
                               << " refused: " << reason << "; loading unpatched\n";
                }
            }
            preloaded = std::move(trial);
        }
    }

    const std::vector<DecalRequest>& effective_decals =
        fix_applied ? decals : kNoDecals;
    if (!decals.empty() && !fix_applied) {
        static std::unordered_set<std::string> decal_warned;
        if (decal_warned.insert(nif_path.string()).second) {
            std::cerr << "hull decals skipped for " << nif_path.string()
                       << ": no mesh fix applied (non-stock mesh)\n";
        }
    }

    auto canon = fs::weakly_canonical(nif_path).string()
                 + replacements_key(texture_replacements) + decals_key(effective_decals)
                 + fix_key;
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

    // preloaded already carries the fix applied (fix_applied == true) or is
    // the untouched trial load (fix_applied == false, reason already
    // warned above) -- either way it must NOT be re-patched here.
    nif::File file = preloaded ? std::move(*preloaded) : nif::load(nif_path);
    if (fix && !preloaded) {
        // fix_applied came from the memo, already known true: apply now for
        // this build. (Ignoring the return: a memoized "true" cannot refuse
        // again against the same content.)
        apply_mesh_fix(file, *fix);
    }

    detail::ModelBuildContext ctx;
    ctx.resolver              = &impl_->resolver;
    ctx.texture_search_paths  = search_paths;
    ctx.texture_uploader      = impl_->config.texture_uploader;
    ctx.mesh_uploader         = impl_->config.mesh_uploader;
    ctx.keep_cpu_data         = impl_->config.keep_cpu_data;
    ctx.texture_replacements  = texture_replacements;
    ctx.decals                = effective_decals;

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
