// native/src/assets/include/assets/cache.h
//
// Refcounted, NIF-path-keyed asset cache. Single-threaded by design;
// caller must ensure a current GL 3.3 core context is on the calling thread
// at load() time and at AssetCache destruction time (the destructor releases
// GL handles via Texture / Mesh dtors).
#pragma once

#include <assets/asset.h>
#include <assets/mesh.h>
#include <assets/model.h>
#include <assets/texture.h>

#include <filesystem>
#include <functional>
#include <memory>
#include <stdexcept>
#include <vector>

namespace assets {

class AssetError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

/// Dedupe-key fragment for ONE decal request: `shape=mask@<geometry>;`, where
/// <geometry> is the raw bytes of origin, u_axis, v_axis, normal and depth,
/// hex-encoded -- lossless, so any placement edit (the SPV's main edit, which
/// leaves shape and mask alone) yields a distinct key. Shared by
/// AssetCache's cache key and the host binding's load_model dedupe so the two
/// layers can never disagree about what "the same decal" means.
std::string decal_request_key(const DecalRequest& d);

class AssetCache {
public:
    struct Config {
        bool keep_cpu_data = false;
        // Test-only injection points. Production callers leave both empty;
        // the cache substitutes upload_image / upload_mesh.
        std::function<Texture(const Image&, bool)> texture_uploader;
        std::function<Mesh(MeshCpu)>               mesh_uploader;

        /// Directory holding mesh-fix files, evaluated at EACH load (resolve
        /// at use; the project asset root can be set after the cache is
        /// built). Empty function or empty path ⇒ no fixes.
        std::function<std::filesystem::path()> mesh_fix_dir;
    };

    AssetCache();                     // equivalent to AssetCache(Config{})
    explicit AssetCache(Config cfg);
    ~AssetCache();
    AssetCache(const AssetCache&) = delete;
    AssetCache& operator=(const AssetCache&) = delete;

    /// Synchronous load. Identical (nif_path, texture_search_paths) returns
    /// the same handle. Different texture_search_paths with the same nif_path
    /// throws AssetError. The list is searched first-match-wins, mirroring
    /// BC's per-ship-dir + shared-dir lookup. The single-path overload is a
    /// convenience wrapper that wraps `texture_search_path` in a 1-element
    /// vector.
    ModelHandle load(const std::filesystem::path& nif_path,
                     const std::filesystem::path& texture_search_path);
    ModelHandle load(const std::filesystem::path& nif_path,
                     const std::vector<std::filesystem::path>& texture_search_paths);

    /// Load with Federation registry / hull-name texture swaps applied
    /// (BC ObjectClass::ReplaceTexture). The replacement list is folded into
    /// the cache key, so distinct registries on the same NIF yield distinct
    /// model variants while same-registry hulls share one. An empty list is
    /// equivalent to the plain overload.
    ModelHandle load(const std::filesystem::path& nif_path,
                     const std::vector<std::filesystem::path>& texture_search_paths,
                     const std::vector<TextureReplacement>& texture_replacements);

    /// Load with hull-name decals applied on top of any registry swap (BC has
    /// no native equivalent; see DecalRequest in model.h). The decal list is
    /// also folded into the cache key -- like texture_replacements, an empty
    /// list is byte-identical to the 3-argument overload, so this is a pure
    /// addition with no behaviour change for existing callers.
    ModelHandle load(const std::filesystem::path& nif_path,
                     const std::vector<std::filesystem::path>& texture_search_paths,
                     const std::vector<TextureReplacement>& texture_replacements,
                     const std::vector<DecalRequest>& decals);

    void evict(const std::filesystem::path& nif_path);
    void evict_unused();

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace assets
