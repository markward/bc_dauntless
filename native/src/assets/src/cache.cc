#include <assets/cache.h>
#include <assets/hull_source.h>
#include <assets/mesh_fix.h>
#include <assets/path_resolver.h>

#include "gltf_model_build.h"
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

std::string decal_request_key(const DecalRequest& d) {
    const float geom[13] = {
        d.origin.x, d.origin.y, d.origin.z,
        d.u_axis.x, d.u_axis.y, d.u_axis.z,
        d.v_axis.x, d.v_axis.y, d.v_axis.z,
        d.normal.x, d.normal.y, d.normal.z,
        d.depth};
    static const char kHex[] = "0123456789abcdef";
    std::string key = d.shape;
    key += '=';
    key += d.mask.string();
    key += '@';
    const auto* bytes = reinterpret_cast<const unsigned char*>(geom);
    for (std::size_t i = 0; i < sizeof(geom); ++i) {
        key += kHex[bytes[i] >> 4];
        key += kHex[bytes[i] & 0xF];
    }
    key += ';';
    return key;
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

// Same reasoning as replacements_key: folds each decal (shape, resolved mask
// path AND placement geometry, see decal_request_key) into the cache key so
// distinct registries or placements on the same NIF land in distinct
// entries, while an empty list is byte-identical to the no-decal key.
std::string decals_key(const std::vector<DecalRequest>& decals) {
    if (decals.empty()) return {};
    std::string key = "|decals:";
    for (const auto& d : decals) key += decal_request_key(d);
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
    return load(nif_path, search_paths, texture_replacements, {});
}

ModelHandle AssetCache::load(
    const fs::path& nif_path,
    const std::vector<fs::path>& search_paths,
    const std::vector<TextureReplacement>& texture_replacements,
    const std::vector<DecalRequest>& decals) {
    return load(nif_path, search_paths, texture_replacements, decals, 1.0f);
}

ModelHandle AssetCache::load(
    const fs::path& nif_path,
    const std::vector<fs::path>& search_paths,
    const std::vector<TextureReplacement>& texture_replacements,
    const std::vector<DecalRequest>& decals,
    float scale) {
    // glTF/GLB path: an entirely separate build (build_model_from_gltf), with
    // no mesh fixes, no texture replacements and no decals -- those are all
    // BC-NIF-specific features that don't apply to rock-catalogue meshes.
    // Handled up front, before the mesh-fix block below, so a glTF path never
    // pays for (or trips over) a nif::load / read_file_bytes(nif_path).
    if (is_gltf_path(nif_path)) {
        if (!texture_replacements.empty() || !decals.empty()) {
            static std::unordered_set<std::string> warned;
            if (warned.insert(nif_path.string()).second) {
                std::cerr << "AssetCache::load: texture_replacements/decals "
                             "are not supported for glTF paths ("
                          << nif_path.string() << "); ignoring\n";
            }
        }

        auto canon_path = fs::weakly_canonical(nif_path);
        auto canon = hull_source_string(canon_path, scale);
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

        detail::ModelBuildContext ctx;
        ctx.resolver             = &impl_->resolver;
        ctx.texture_search_paths = search_paths;
        ctx.texture_uploader     = impl_->config.texture_uploader;
        ctx.mesh_uploader        = impl_->config.mesh_uploader;
        ctx.keep_cpu_data        = impl_->config.keep_cpu_data;

        auto model = std::make_shared<const Model>(
            detail::build_model_from_gltf(nif_path, scale, ctx));

        Impl::Entry entry;
        entry.live         = model;
        entry.pinned       = model;
        entry.search_paths = search_paths;
        impl_->entries[canon] = std::move(entry);
        return model;
    }

    // No production caller needs a scaled NIF -- YAGNI, rather than silently
    // ignoring a scale nobody asked for.
    if (scale != 1.0f) {
        throw AssetError("scale is only supported for glTF");
    }

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

    // Decals attach whether or not a fix applied (spec
    // 2026-09-28-spv-decal-editing-design.md §2.1): they are an independent
    // per-class feature, not a follow-on to the "ID" patch merge.
    auto canon = fs::weakly_canonical(nif_path).string()
                 + replacements_key(texture_replacements) + decals_key(decals)
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
    ctx.decals                = decals;

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
